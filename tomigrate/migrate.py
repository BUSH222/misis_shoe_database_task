import sys
import os
from datetime import datetime
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.database import engine, SessionLocal  # noqa: E402
from src.models import (Base, Role, User, Category, Supplier, Manufacturer,  # noqa: E402
                        Unit, Product, PickupPoint, Order, OrderItem)  # noqa: E402


def parse_date(date_str):
    """Parse date from multiple possible formats"""
    if pd.isna(date_str):
        return None
    date_str = str(date_str).strip()

    # Try format: m/d/yy or m/d/yyyy
    try:
        return datetime.strptime(date_str, '%m/%d/%y').date()
    except ValueError:
        pass

    # Try format: dd.mm.yyyy
    try:
        return datetime.strptime(date_str, '%d.%m.%Y').date()
    except ValueError:
        pass

    # Try format: yyyy-mm-dd (pandas default)
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        pass

    # Try format: yyyy-mm-dd hh:mm:ss (pandas default with time)
    try:
        return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S').date()
    except ValueError:
        pass

    # are you stupid? why 30th of february?
    if date_str == '30.02.2025':
        return datetime(2025, 2, 28).date()

    print(f"Warning: Could not parse date '{date_str}'")


def get_or_create(session, model, **kwargs):
    """Get existing instance or create new one"""
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance
    instance = model(**kwargs)
    session.add(instance)
    session.flush()
    return instance


def import_pickup_points(session, file_path):
    """Import pickup points from Excel"""
    df = pd.read_excel(file_path, header=None)

    for address in df[0]:
        if pd.notna(address):
            pickup_point = PickupPoint(address=address.strip())
            session.add(pickup_point)

    session.commit()
    print(f"Imported {len(df)} pickup points")


def import_users(session, file_path):
    """Import users and roles from Excel"""
    df = pd.read_excel(file_path)

    # Create roles
    roles_set = set(df['Роль сотрудника'].unique())
    for role_name in roles_set:
        get_or_create(session, Role, name=role_name)

    session.commit()

    # Create users
    for _, row in df.iterrows():
        role = session.query(Role).filter_by(name=row['Роль сотрудника']).first()
        user = User(
            full_name=row['ФИО'],
            login=row['Логин'],
            password=row['Пароль'],
            role_id=role.id
        )
        session.add(user)

    session.commit()
    print(f"Imported {len(df)} users and {len(roles_set)} roles")


def import_products(session, file_path):
    """Import products with related data from Excel"""
    df = pd.read_excel(file_path)

    for _, row in df.iterrows():
        # Get or create category
        category = get_or_create(session, Category, name=row['Категория товара'])

        # Get or create supplier
        supplier = get_or_create(session, Supplier, name=row['Поставщик'])

        # Get or create manufacturer
        manufacturer = get_or_create(session, Manufacturer, name=row['Производитель'])

        # Get or create unit
        unit = get_or_create(session, Unit, name=row['Единица измерения'])

        # Create product
        photo = row['Фото'] if pd.notna(row['Фото']) else None

        product = Product(
            article=row['Артикул'],
            name=row['Наименование товара'],
            description=row['Описание товара'] if pd.notna(row['Описание товара']) else '',
            price=float(row['Цена']),
            discount=int(row['Действующая скидка']),
            stock_quantity=int(row['Кол-во на складе']),
            photo=photo,
            category_id=category.id,
            supplier_id=supplier.id,
            manufacturer_id=manufacturer.id,
            unit_id=unit.id
        )
        session.add(product)

    session.commit()
    print(f"Imported {len(df)} products")


def import_orders(session, file_path):
    """Import orders with order items from Excel"""
    df = pd.read_excel(file_path)

    for _, row in df.iterrows():
        # Find user by full name
        user = session.query(User).filter_by(full_name=row['ФИО авторизированного клиента']).first()
        if not user:
            print(f"Warning: User '{row['ФИО авторизированного клиента']}' not found, skipping order")
            continue

        # Get pickup point by ID (row number in the Excel file)
        pickup_point_id = int(row['Адрес пункта выдачи'])
        pickup_point = session.query(PickupPoint).filter_by(id=pickup_point_id).first()
        if not pickup_point:
            print(f"Warning: Pickup point {pickup_point_id} not found, skipping order")
            continue

        # Parse dates
        order_date = parse_date(row['Дата заказа'])
        delivery_date = parse_date(row['Дата доставки'])

        # Create order
        order = Order(
            order_number=int(row['Номер заказа']),
            order_date=order_date,
            delivery_date=delivery_date,
            pickup_code=str(row['Код для получения']),
            status=row['Статус заказа'],
            user_id=user.id,
            pickup_point_id=pickup_point.id
        )
        session.add(order)
        session.flush()

        # Parse order items (alternating pattern: article, quantity, article, quantity)
        items_str = str(row['Артикул заказа'])
        items = [item.strip() for item in items_str.split(',')]

        for i in range(0, len(items), 2):
            if i + 1 < len(items):
                article = items[i]
                quantity = int(items[i + 1])

                product = session.query(Product).filter_by(article=article).first()
                if product:
                    order_item = OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        quantity=quantity
                    )
                    session.add(order_item)
                else:
                    print(f"Warning: Product with article '{article}' not found")

    session.commit()
    print(f"Imported {len(df)} orders")


def main():
    print("Starting database migration...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created")

    session = SessionLocal()

    try:
        import_pickup_points(session, 'tomigrate/Пункты выдачи_import.xlsx')
        import_users(session, 'tomigrate/user_import.xlsx')
        import_products(session, 'tomigrate/Tovar.xlsx')
        import_orders(session, 'tomigrate/Заказ_import.xlsx')

        print("\nMigration completed successfully!")

    except Exception as e:
        print(f"Error during migration: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == '__main__':
    main()
