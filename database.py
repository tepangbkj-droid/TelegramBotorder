# database.py
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import sessionmaker, relationship, declarative_base

DATABASE_URL = "sqlite:///store.db"
Base = declarative_base()

class Product(Base):
    """Menentukan skema tabel Produk."""
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=1)
    description = Column(String)

class Order(Base):
    """Menentukan skema tabel Pesanan."""
    __tablename__ = 'orders'
    id = Column(String, primary_key=True) # Akan diisi dengan Order ID dari Midtrans
    user_id = Column(Integer, nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'))
    status = Column(String, default='pending') # pending, paid, failed
    product = relationship("Product")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Menginisialisasi database dengan membuat semua tabel."""
    Base.metadata.create_all(bind=engine)

# Panggil init_db() untuk membuat file DB saat pertama kali dijalankan
if __name__ == '__main__':
    init_db()
    print("Database initialized.")
