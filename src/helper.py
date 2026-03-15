from fastapi import HTTPException
from sqlalchemy.orm import Session
from PIL import Image
import os
import uuid
import io

from src.models import User, Product, Category, Manufacturer, Supplier, OrderItem, Order
from fastapi import UploadFile


def is_admin(user: User) -> bool:
    return user.role.name == "Администратор"


def is_manager(user: User) -> bool:
    return user.role.name in ["Менеджер", "Администратор"]


def require_admin(user: User):
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Forbidden")


def set_flash_message(request, message: str, msg_type: str = "info"):
    request.session["flash_message"] = message
    request.session["flash_type"] = msg_type


def apply_product_filters(query, search, category, supplier_filter, sort):
    """Apply filters and sorting to product query"""
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Product.name.like(search_term))
            | (Product.description.like(search_term))
            | (Product.article.like(search_term))
            | (Category.name.like(search_term))
            | (Manufacturer.name.like(search_term))
            | (Supplier.name.like(search_term))
        )

    if category:
        query = query.filter(Product.category.has(name=category))
    if supplier_filter:
        query = query.filter(Product.supplier.has(name=supplier_filter))

    sort_map = {
        "price_asc": Product.price.asc(),
        "price_desc": Product.price.desc(),
        "name": Product.name.asc(),
        "discount": Product.discount.desc(),
        "stock_asc": Product.stock_quantity.asc(),
        "stock_desc": Product.stock_quantity.desc(),
    }
    if sort and sort in sort_map:
        query = query.order_by(sort_map[sort])

    return query


def parse_order_items(order_items_str: str, db: Session):
    """Parse order items string and return list of (product, quantity) tuples"""
    items = [item.strip() for item in order_items_str.split(',')]
    result = []
    for i in range(0, len(items), 2):
        if i + 1 < len(items):
            article = items[i]
            quantity = int(items[i+1])
            product = db.query(Product).filter(Product.article == article).first()
            if product:
                result.append((product, quantity))
    return result


def save_order_items(order: Order, order_items_str: str, db: Session):
    """Clear and recreate order items"""
    db.query(OrderItem).filter(OrderItem.order_id == order.id).delete()
    for product, quantity in parse_order_items(order_items_str, db):
        db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=quantity))


def remove_old_product_image(filename: str):
    """Remove old product image file"""
    if filename and filename != "picture.png":
        old_path = os.path.join("static", filename)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception as e:
                print(f"Error removing old image: {e}")


def get_or_create(session, model, **kwargs):
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance
    instance = model(**kwargs)
    session.add(instance)
    session.flush()
    return instance


async def process_image(photo: UploadFile):
    """Returns filename and optional warning message"""
    if not photo or not photo.filename:
        return None, None
    try:
        contents = await photo.read()
        if not contents:
            return None, None
        img = Image.open(io.BytesIO(contents))
        warning = None
        if img.size != (300, 200):
            img = img.resize((300, 200), Image.Resampling.LANCZOS)
            warning = "Изображение было автоматически изменено до размера 300x200."

        # is it safe? static? idk
        ext = os.path.splitext(photo.filename)[1]
        if not ext:
            ext = ".jpg"
        filename = f"{uuid.uuid4()}{ext}"
        filepath = os.path.join("static", filename)

        img.save(filepath)
        return filename, warning
    except Exception as e:
        print(f"Error processing image: {e}")
        return None, "Ошибка при обработке изображения."
