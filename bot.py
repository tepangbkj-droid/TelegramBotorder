# bot.py
import os
import logging
import threading
import hmac
import hashlib
from dotenv import load_dotenv


from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

import midtransclient
from database import SessionLocal, Product, Order

# --- Konfigurasi Awal ---
load_dotenv()
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MIDTRANS_SERVER_KEY = os.getenv("MIDTRANS_SERVER_KEY")
MIDTRANS_IS_PRODUCTION = os.getenv("MIDTRANS_IS_PRODUCTION", "False").lower() in ['true', '1', 't']
HOST_URL = os.getenv("HOST_URL") # URL publik untuk webhook

# Inisialisasi Klien Midtrans
try:
    snap = midtransclient.Snap(is_production=MIDTRANS_IS_PRODUCTION, server_key=MIDTRANS_SERVER_KEY)
except Exception as e:
    logging.error(f"Gagal menginisialisasi klien Midtrans: {e}")
    snap = None

# Inisialisasi aplikasi Flask untuk webhook
flask_app = Flask(__name__)

# --- Logika Bot Telegram ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengirim pesan selamat datang."""
    await update.message.reply_text("Selamat datang! Ketik /products untuk melihat produk kami.")

async def show_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengambil dan menampilkan produk yang tersedia."""
    if not snap:
        await update.message.reply_text("Maaf, layanan pembayaran tidak tersedia.")
        return
        
    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.stock > 0).all()
        if not products:
            await update.message.reply_text("Maaf, semua produk sedang habis.")
            return

        message = "Berikut adalah produk yang tersedia:\n\n"
        keyboard = []
        for product in products:
            message += f"*{product.name}*\n"
            message += f"Harga: Rp {product.price:,.0f}\n"
            message += f"Stok: {product.stock}\n"
            message += f"Deskripsi: {product.description}\n\n"
            keyboard.append([InlineKeyboardButton(f"Beli {product.name}", callback_data=f"buy_{product.id}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logging.error(f"Error showing products: {e}")
        await update.message.reply_text("Maaf, terjadi kesalahan saat mengambil data produk.")
    finally:
        db.close()

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani klik tombol inline."""
    query = update.callback_query
    await query.answer()

    data = query.data.split('_')
    if data[0] == "buy":
        product_id = int(data[1])
        user_id = query.from_user.id
        db = SessionLocal()
        try:
            product = db.query(Product).filter_by(id=product_id).first()

            if not product or product.stock <= 0:
                await query.edit_message_text("Maaf, produk ini sudah habis atau tidak ditemukan.")
                return

            # Buat Order ID yang unik
            order_id = f"TG-{user_id}-{product_id}-{hashlib.sha256(str(os.urandom(16)).encode()).hexdigest()[:6]}"

            # Buat order baru di database
            order = Order(id=order_id, user_id=user_id, product_id=product_id, status="pending")
            db.add(order)
            db.commit()

            # Siapkan detail transaksi Midtrans
            params = {
                "transaction_details": {
                    "order_id": order_id,
                    "gross_amount": product.price
                },
                "item_details": [{
                    "id": product.id,
                    "price": product.price,
                    "quantity": 1,
                    "name": product.name
                }],
                "customer_details": {
                    "first_name": query.from_user.first_name,
                    "last_name": query.from_user.last_name or "",
                    "email": f"{user_id}@telegram.com"
                },
                "callbacks": {
                    "finish": f"{HOST_URL}/checkout_finished?order_id={order_id}"
                }
            }

            snap_url = snap.create_transaction_token(params)
            await query.edit_message_text(f"Untuk melanjutkan pembayaran, silakan klik tautan berikut:\n{snap_url}")

        except Exception as e:
            logging.error(f"Error creating transaction: {e}")
            await query.edit_message_text("Maaf, terjadi kesalahan saat membuat transaksi. Silakan coba lagi.")
            db.rollback()
        finally:
            db.close()

# --- Logika Webhook Flask ---
@flask_app.route('/webhook', methods=['POST'])
def webhook_handler():
    """Menangani notifikasi pembayaran Midtrans."""
    
    # Keamanan: Validasi tanda tangan Midtrans
    signature_key = MIDTRANS_SERVER_KEY
    request_body = request.get_data(as_text=True)
    signature_hash = hmac.new(
        signature_key.encode(),
        request_body.encode(),
        hashlib.sha512
    ).hexdigest()

    midtrans_signature = request.headers.get('X-Midtrans-Signature')

    if midtrans_signature != signature_hash:
        logging.warning("Tanda tangan Midtrans tidak valid. Menolak permintaan webhook.")
        return jsonify({"status": "error", "message": "Invalid signature"}), 403

    notification = request.get_json()
    order_id = notification['order_id']
    transaction_status = notification['transaction_status']
    fraud_status = notification['fraud_status']
    
    logging.info(f"Menerima notifikasi Midtrans untuk order {order_id} dengan status {transaction_status}")

    db = SessionLocal()
    try:
        order = db.query(Order).filter_by(id=order_id).first()
        if not order:
            logging.warning(f"Order {order_id} tidak ditemukan di database.")
            return jsonify({"status": "error", "message": "Order not found"}), 404

        if order.status == 'pending' and transaction_status == 'settlement' and fraud_status == 'accept':
            order.status = 'paid'
            
            # Kurangi stok produk
            if order.product and order.product.stock > 0:
                order.product.stock -= 1
            else:
                logging.error(f"Stok produk untuk order {order_id} sudah 0 atau produk tidak ditemukan.")
            
            db.commit()
            logging.info(f"Pembayaran berhasil untuk {order_id}. Pengguna: {order.user_id}")

        elif transaction_status in ['deny', 'cancel', 'expire']:
            order.status = 'failed'
            db.commit()
            logging.info(f"Pembayaran untuk {order_id} gagal. Pengguna: {order.user_id}")

    except Exception as e:
        logging.error(f"Error memproses webhook untuk order {order_id}: {e}")
        db.rollback()
        return jsonify({"status": "error", "message": "Internal Server Error"}), 500
    finally:
        db.close()
        
    return jsonify({"status": "ok"}), 200

# --- Fungsi Utama ---
def run_flask():
    """Menjalankan server Flask di thread terpisah."""
    flask_app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 8080)))

def main() -> None:
    """Titik masuk aplikasi bot."""
    if not TELEGRAM_TOKEN:
        logging.error("Variabel lingkungan TELEGRAM_TOKEN tidak diatur.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("products", show_products))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Jalankan Flask di thread terpisah untuk webhook
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    logging.info("Memulai bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
