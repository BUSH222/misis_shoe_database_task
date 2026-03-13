from fastapi import FastAPI, Request, Depends, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from PIL import Image
import os
import uuid
import io
from datetime import datetime

from src.database import init_db, get_db
from src.models import User, Product, Order, Category, Supplier, Manufacturer, Unit, OrderItem, PickupPoint

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


app = FastAPI(title="Магазин обуви")

app.add_middleware(SessionMiddleware, secret_key="your-secret-key-here-change-in-production")
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
templates.env.filters["zip"] = lambda a, b: zip(a, b)


# kitty
def build_httpcat_page(request: Request, status_code: int, detail: str = "") -> HTMLResponse:
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "status_code": status_code,
        },
        status_code=status_code,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return build_httpcat_page(request, exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return build_httpcat_page(request, 422, "Validation error in request data.")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return build_httpcat_page(request, 500, "Internal server error.")


@app.on_event("startup")
def startup_event():
    init_db()


def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    return user


def require_login(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/login")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.login == login, User.password == password).first()

    if user:
        request.session["user_id"] = user.id
        return RedirectResponse(url="/products", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Неверный логин или пароль"}
    )


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")


@app.get("/guest")
async def guest_access(request: Request):
    request.session.clear()
    return RedirectResponse(url="/products")


@app.get("/products", response_class=HTMLResponse)
async def products_page(
    request: Request,
    db: Session = Depends(get_db),
    search: str = None,
    category: str = None,
    supplier_filter: str = None,
    sort: str = None
):
    current_user = get_current_user(request, db)
    is_manager = current_user and current_user.role.name in ["Менеджер", "Администратор"]
    is_admin = current_user and current_user.role.name == "Администратор"

    # Base query
    query = db.query(Product)

    # Needs to join for full text search if manager/admin
    if is_manager:
        query = query.outerjoin(Product.category).outerjoin(Product.manufacturer).outerjoin(Product.supplier)

    if is_manager:
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

        # Apply sorting
        if sort == "price_asc":
            query = query.order_by(Product.price.asc())
        elif sort == "price_desc":
            query = query.order_by(Product.price.desc())
        elif sort == "name":
            query = query.order_by(Product.name.asc())
        elif sort == "discount":
            query = query.order_by(Product.discount.desc())
        elif sort == "stock_asc":
            query = query.order_by(Product.stock_quantity.asc())
        elif sort == "stock_desc":
            query = query.order_by(Product.stock_quantity.desc())

    products = query.all()

    # Get data for filters and add/edit forms
    categories = db.query(Category).all()
    category_names = [cat.name for cat in categories]

    suppliers = db.query(Supplier).all()
    supplier_names = [sup.name for sup in suppliers]

    manufacturers = db.query(Manufacturer).all()

    # Retrieve flash message if any
    flash_message = request.session.pop("flash_message", None)
    flash_type = request.session.pop("flash_type", "info")

    return templates.TemplateResponse(
        "products.html",
        {
            "request": request,
            "user": current_user,
            "is_admin": is_admin,
            "is_manager": is_manager,
            "products": products,
            "categories": categories,
            "category_names": category_names,
            "supplier_names": supplier_names,
            "manufacturers": manufacturers,
            "current_search": search or "",
            "current_category": category or "",
            "current_supplier": supplier_filter or "",
            "current_sort": sort or "",
            "flash_message": flash_message,
            "flash_type": flash_type
        }
    )


@app.post("/orders/add")
async def add_order(
    request: Request,
    order_number: int = Form(...),
    status: str = Form(...),
    pickup_point_id: int = Form(...),
    order_date: str = Form(...),
    delivery_date: str = Form(...),
    user_id: int = Form(...),
    pickup_code: str = Form(...),
    order_items: str = Form(...),
    db: Session = Depends(get_db)
):
    current_user = require_login(request, db)
    if current_user.role.name != "Администратор":
        raise HTTPException(status_code=403, detail="Forbidden")

    # Check if order number exists
    existing = db.query(Order).filter(Order.order_number == order_number).first()
    if existing:
        request.session["flash_message"] = "Данный номер заказа уже существует."
        request.session["flash_type"] = "danger"
        return RedirectResponse(url="/orders", status_code=303)

    try:
        parsed_order_date = datetime.strptime(order_date, "%Y-%m-%d").date()
        parsed_delivery_date = datetime.strptime(delivery_date, "%Y-%m-%d").date()

        new_order = Order(
            order_number=order_number,
            order_date=parsed_order_date,
            delivery_date=parsed_delivery_date,
            pickup_code=pickup_code,
            status=status,
            user_id=user_id,
            pickup_point_id=pickup_point_id
        )
        db.add(new_order)
        db.flush()

        # Parse order items (article, quantity, article, quantity...)
        items = [item.strip() for item in order_items.split(',')]
        for i in range(0, len(items), 2):
            if i + 1 < len(items):
                article = items[i]
                quantity = int(items[i+1])
                product = db.query(Product).filter(Product.article == article).first()
                if product:
                    db.add(OrderItem(order_id=new_order.id, product_id=product.id, quantity=quantity))

        db.commit()
        request.session["flash_message"] = "Заказ успешно добавлен."
        request.session["flash_type"] = "success"
    except Exception as e:
        db.rollback()
        request.session["flash_message"] = f"Ошибка при добавлении заказа (проверьте формат товаров!). {e}"
        request.session["flash_type"] = "danger"

    return RedirectResponse(url="/orders", status_code=303)


@app.post("/orders/{order_id}/edit")
async def edit_order(
    request: Request,
    order_id: int,
    status: str = Form(...),
    pickup_point_id: int = Form(...),
    order_date: str = Form(...),
    delivery_date: str = Form(...),
    user_id: int = Form(...),
    pickup_code: str = Form(...),
    order_items: str = Form(...),
    db: Session = Depends(get_db)
):
    current_user = require_login(request, db)
    if current_user.role.name != "Администратор":
        raise HTTPException(status_code=403, detail="Forbidden")

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        order.status = status
        order.pickup_point_id = pickup_point_id
        order.order_date = datetime.strptime(order_date, "%Y-%m-%d").date()
        order.delivery_date = datetime.strptime(delivery_date, "%Y-%m-%d").date()
        order.user_id = user_id
        order.pickup_code = pickup_code

        # Re-create items parsing string list
        db.query(OrderItem).filter(OrderItem.order_id == order.id).delete()

        items = [item.strip() for item in order_items.split(',')]
        for i in range(0, len(items), 2):
            if i + 1 < len(items):
                article = items[i]
                quantity = int(items[i+1])
                product = db.query(Product).filter(Product.article == article).first()
                if product:
                    db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=quantity))

        db.commit()
        request.session["flash_message"] = "Заказ успешно обновлен."
        request.session["flash_type"] = "success"
    except Exception as e:
        db.rollback()
        request.session["flash_message"] = f"Ошибка при обновлении заказа (проверьте формат товаров!). {e}"
        request.session["flash_type"] = "danger"

    return RedirectResponse(url="/orders", status_code=303)


@app.post("/orders/{order_id}/delete")
async def delete_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = require_login(request, db)
    if current_user.role.name != "Администратор":
        raise HTTPException(status_code=403, detail="Forbidden")

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        db.delete(order)
        db.commit()
        request.session["flash_message"] = "Заказ успешно удален."
        request.session["flash_type"] = "success"
    except Exception as e:
        db.rollback()
        request.session["flash_message"] = f"Ошибка при удалении заказа: {e}"
        request.session["flash_type"] = "danger"
    return RedirectResponse(url="/orders", status_code=303)


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

        # Ensure it's static/ safe
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


@app.post("/products/add")
async def add_product(
    request: Request,
    article: str = Form(...),
    name: str = Form(...),
    category_id: int = Form(...),
    description: str = Form(""),
    manufacturer_id: int = Form(...),
    supplier_name: str = Form(...),
    price: float = Form(...),
    unit_name: str = Form(...),
    stock_quantity: int = Form(...),
    discount: int = Form(0),
    photo: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    current_user = require_login(request, db)
    if current_user.role.name != "Администратор":
        raise HTTPException(status_code=403, detail="Forbidden")

    if price < 0 or stock_quantity < 0 or discount < 0:
        request.session["flash_message"] = "Цена, количество на складе и скидка не могут быть отрицательными."
        request.session["flash_type"] = "danger"
        return RedirectResponse(url="/products", status_code=303)

    # Image upload
    filename, warning = await process_image(photo)

    # Get or create string-based relations
    supplier = get_or_create(db, Supplier, name=supplier_name)
    unit = get_or_create(db, Unit, name=unit_name)

    new_product = Product(
        article=article,
        name=name,
        category_id=category_id,
        description=description,
        manufacturer_id=manufacturer_id,
        supplier_id=supplier.id,
        price=price,
        unit_id=unit.id,
        stock_quantity=stock_quantity,
        discount=discount,
        photo=filename
    )

    try:
        db.add(new_product)
        db.commit()
        request.session["flash_message"] = warning if warning else "Товар успешно добавлен!"
        request.session["flash_type"] = "warning" if warning else "success"

    except Exception as e:
        print(f"Error adding product: {e}")
        db.rollback()
        request.session["flash_message"] = "Ошибка при добавлении товара. Возможно, артикул уже существует."
        request.session["flash_type"] = "danger"

    return RedirectResponse(url="/products", status_code=303)


@app.post("/products/{product_id}/edit")
async def edit_product(
    product_id: int,
    request: Request,
    name: str = Form(...),
    category_id: int = Form(...),
    description: str = Form(""),
    manufacturer_id: int = Form(...),
    supplier_name: str = Form(...),
    price: float = Form(...),
    unit_name: str = Form(...),
    stock_quantity: int = Form(...),
    discount: int = Form(0),
    photo: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    current_user = require_login(request, db)
    if current_user.role.name != "Администратор":
        raise HTTPException(status_code=403, detail="Forbidden")

    if price < 0 or stock_quantity < 0 or discount < 0:
        request.session["flash_message"] = "Цена, количество на складе и скидка не могут быть отрицательными."
        request.session["flash_type"] = "danger"
        return RedirectResponse(url="/products", status_code=303)

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    supplier = get_or_create(db, Supplier, name=supplier_name)
    unit = get_or_create(db, Unit, name=unit_name)

    # Process new photo if provided
    filename, warning = await process_image(photo)
    if filename:
        # Prevent deleting the placeholder image "picture.png" or other static non-uuid files if any
        if product.photo and product.photo != "picture.png":
            old_path = os.path.join("static", product.photo)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception as e:
                    print(f"Error removing old image: {e}")
        product.photo = filename

    product.name = name
    product.category_id = category_id
    product.description = description
    product.manufacturer_id = manufacturer_id
    product.supplier_id = supplier.id
    product.price = price
    product.unit_id = unit.id
    product.stock_quantity = stock_quantity
    product.discount = discount

    db.commit()
    if warning:
        request.session["flash_message"] = f"Товар обновлен. {warning}"
        request.session["flash_type"] = "warning"
    else:
        request.session["flash_message"] = "Товар успешно обновлен!"
        request.session["flash_type"] = "success"

    return RedirectResponse(url="/products", status_code=303)


@app.post("/products/{product_id}/delete")
async def delete_product(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = require_login(request, db)
    if current_user.role.name != "Администратор":
        raise HTTPException(status_code=403, detail="Forbidden")

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if product is in any orders
    in_order = db.query(OrderItem).filter(OrderItem.product_id == product_id).first()
    if in_order:
        request.session["flash_message"] = "Невозможно удалить товар, так как он присутствует в заказах."
        request.session["flash_type"] = "danger"
        return RedirectResponse(url="/products", status_code=303)

    if product.photo and product.photo != "picture.png":
        old_path = os.path.join("static", product.photo)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception as e:
                print(f"Error removing old image: {e}")

    db.delete(product)
    db.commit()

    request.session["flash_message"] = "Товар успешно удален."
    request.session["flash_type"] = "success"

    return RedirectResponse(url="/products", status_code=303)


@app.get("/orders", response_class=HTMLResponse)
async def orders_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    if current_user.role.name not in ["Администратор", "Менеджер"]:
        raise HTTPException(status_code=403, detail="Доступ запрещен")

    is_admin = current_user.role.name == "Администратор"

    orders = db.query(Order).all()
    pickup_points = db.query(PickupPoint).all() if is_admin else []
    users = db.query(User).all() if is_admin else []

    # Retrieve flash message if any
    flash_message = request.session.pop("flash_message", None)
    flash_type = request.session.pop("flash_type", "info")

    return templates.TemplateResponse(
        "orders.html",
        {
            "request": request,
            "user": current_user,
            "is_admin": is_admin,
            "orders": orders,
            "pickup_points": pickup_points,
            "users": users,
            "flash_message": flash_message,
            "flash_type": flash_type
        }
    )
