# seed_db.py
from database import SessionLocal, Product

def seed_products():
    """Mengisi database dengan data produk awal."""
    db = SessionLocal()
    try:
        # Hapus produk lama jika ada
        db.query(Product).delete()

        # Tambahkan produk baru
        products = [
            Product(name="Kopi Robusta 250g", price=50000, stock=10, description="Biji kopi Robusta pilihan dari pegunungan."),
            Product(name="Teh Hijau Premium", price=75000, stock=15, description="Daun teh hijau kualitas ekspor."),
            Product(name="Madu Hutan Asli", price=120000, stock=5, description="Madu murni dari lebah liar hutan Sumatera.")
        ]
        db.add_all(products)
        db.commit()
        print("Products seeded successfully!")
    finally:
        db.close()

if __name__ == '__main__':
    seed_products()
