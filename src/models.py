from sqlalchemy import Column, Integer, String, Float, ForeignKey, Date, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Role(Base):
    __tablename__ = 'roles'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    users = relationship('User', back_populates='role')


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(200), nullable=False)
    login = Column(String(100), nullable=False, unique=True)
    password = Column(String(100), nullable=False)
    role_id = Column(Integer, ForeignKey('roles.id'), nullable=False)
    role = relationship('Role', back_populates='users')
    orders = relationship('Order', back_populates='user')


class Category(Base):
    __tablename__ = 'categories'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    products = relationship('Product', back_populates='category')


class Supplier(Base):
    __tablename__ = 'suppliers'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    products = relationship('Product', back_populates='supplier')


class Manufacturer(Base):
    __tablename__ = 'manufacturers'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    products = relationship('Product', back_populates='manufacturer')


class Unit(Base):
    __tablename__ = 'units'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True)
    products = relationship('Product', back_populates='unit')


class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True, autoincrement=True)
    article = Column(String(50), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    price = Column(Float, nullable=False)
    discount = Column(Integer, default=0)
    stock_quantity = Column(Integer, default=0)
    photo = Column(String(200))
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False)
    supplier_id = Column(Integer, ForeignKey('suppliers.id'), nullable=False)
    manufacturer_id = Column(Integer, ForeignKey('manufacturers.id'), nullable=False)
    unit_id = Column(Integer, ForeignKey('units.id'), nullable=False)
    category = relationship('Category', back_populates='products')
    supplier = relationship('Supplier', back_populates='products')
    manufacturer = relationship('Manufacturer', back_populates='products')
    unit = relationship('Unit', back_populates='products')
    order_items = relationship('OrderItem', back_populates='product')


class PickupPoint(Base):
    __tablename__ = 'pickup_points'
    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String(300), nullable=False)
    orders = relationship('Order', back_populates='pickup_point')


class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_number = Column(Integer, nullable=False, unique=True)
    order_date = Column(Date, nullable=False)
    delivery_date = Column(Date, nullable=False)
    pickup_code = Column(String(10), nullable=False)
    status = Column(String(50), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    pickup_point_id = Column(Integer, ForeignKey('pickup_points.id'), nullable=False)
    user = relationship('User', back_populates='orders')
    pickup_point = relationship('PickupPoint', back_populates='orders')
    order_items = relationship('OrderItem', back_populates='order', cascade='all, delete-orphan')


class OrderItem(Base):
    __tablename__ = 'order_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    quantity = Column(Integer, nullable=False)
    order_id = Column(Integer, ForeignKey('orders.id'), nullable=False)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    order = relationship('Order', back_populates='order_items')
    product = relationship('Product', back_populates='order_items')
