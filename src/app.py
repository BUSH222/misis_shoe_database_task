from fastapi import FastAPI, Request, Depends, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from datetime import datetime

from src.database import init_db, get_db
from src.models import User, Product, Order, Category, Supplier, Manufacturer, Unit, OrderItem, PickupPoint
from src import helper

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from secrets import token_urlsafe


app = FastAPI(title="Магазин обуви")

app.add_middleware(SessionMiddleware, secret_key=token_urlsafe(20))
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
    user_is_manager = current_user and helper.is_manager(current_user)
    user_is_admin = current_user and helper.is_admin(current_user)

    # Base query
    query = db.query(Product)

    # Needs to join for full text search if manager/admin
    if user_is_manager:
        query = query.outerjoin(Product.category).outerjoin(Product.manufacturer).outerjoin(Product.supplier)
        query = helper.apply_product_filters(query, search, category, supplier_filter, sort)

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
            "is_admin": user_is_admin,
            "is_manager": user_is_manager,
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
    helper.require_admin(current_user)

    # Check if order number exists
    existing = db.query(Order).filter(Order.order_number == order_number).first()
    if existing:
        helper.set_flash_message(request, "Данный номер заказа уже существует.", "danger")
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

        helper.save_order_items(new_order, order_items, db)
        db.commit()
        helper.set_flash_message(request, "Заказ успешно добавлен.", "success")
    except Exception as e:
        db.rollback()
        helper.set_flash_message(request, f"Ошибка при добавлении заказа (проверьте формат товаров!). {e}", "danger")

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
    helper.require_admin(current_user)

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

        helper.save_order_items(order, order_items, db)
        db.commit()
        helper.set_flash_message(request, "Заказ успешно обновлен.", "success")
    except Exception as e:
        db.rollback()
        helper.set_flash_message(request, f"Ошибка при обновлении заказа (проверьте формат товаров!). {e}", "danger")

    return RedirectResponse(url="/orders", status_code=303)


@app.post("/orders/{order_id}/delete")
async def delete_order(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = require_login(request, db)
    helper.require_admin(current_user)

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    try:
        db.delete(order)
        db.commit()
        helper.set_flash_message(request, "Заказ успешно удален.", "success")
    except Exception as e:
        db.rollback()
        helper.set_flash_message(request, f"Ошибка при удалении заказа: {e}", "danger")
    return RedirectResponse(url="/orders", status_code=303)


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
    helper.require_admin(current_user)

    if price < 0 or stock_quantity < 0 or discount < 0:
        helper.set_flash_message(request, "Цена, количество на складе/скидка не могут быть отрицательными.", "danger")
        return RedirectResponse(url="/products", status_code=303)

    # Image upload
    filename, warning = await helper.process_image(photo)

    # Get or create string-based relations
    supplier = helper.get_or_create(db, Supplier, name=supplier_name)
    unit = helper.get_or_create(db, Unit, name=unit_name)

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
        msg_type = "warning" if warning else "success"
        msg = warning if warning else "Товар успешно добавлен!"
        helper.set_flash_message(request, msg, msg_type)
    except Exception as e:
        print(f"Error adding product: {e}")
        db.rollback()
        helper.set_flash_message(request, "Ошибка при добавлении товара. Возможно, артикул уже существует.", "danger")

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
    helper.require_admin(current_user)

    if price < 0 or stock_quantity < 0 or discount < 0:
        helper.set_flash_message(request, "Цена, количество на складе/скидка не могут быть отрицательными.", "danger")
        return RedirectResponse(url="/products", status_code=303)

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    supplier = helper.get_or_create(db, Supplier, name=supplier_name)
    unit = helper.get_or_create(db, Unit, name=unit_name)

    # Process new photo if provided
    filename, warning = await helper.process_image(photo)
    if filename:
        helper.remove_old_product_image(product.photo)
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
        helper.set_flash_message(request, f"Товар обновлен. {warning}", "warning")
    else:
        helper.set_flash_message(request, "Товар успешно обновлен!", "success")

    return RedirectResponse(url="/products", status_code=303)


@app.post("/products/{product_id}/delete")
async def delete_product(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    current_user = require_login(request, db)
    helper.require_admin(current_user)

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if product is in any orders
    in_order = db.query(OrderItem).filter(OrderItem.product_id == product_id).first()
    if in_order:
        helper.set_flash_message(request, "Невозможно удалить товар, так как он присутствует в заказах.", "danger")
        return RedirectResponse(url="/products", status_code=303)

    helper.remove_old_product_image(product.photo)
    db.delete(product)
    db.commit()
    helper.set_flash_message(request, "Товар успешно удален.", "success")

    return RedirectResponse(url="/products", status_code=303)


@app.get("/orders", response_class=HTMLResponse)
async def orders_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    if not helper.is_manager(current_user):
        raise HTTPException(status_code=403, detail="Доступ запрещен")

    user_is_admin = helper.is_admin(current_user)

    orders = db.query(Order).all()
    pickup_points = db.query(PickupPoint).all() if user_is_admin else []
    users = db.query(User).all() if user_is_admin else []

    # Retrieve flash message if any
    flash_message = request.session.pop("flash_message", None)
    flash_type = request.session.pop("flash_type", "info")

    return templates.TemplateResponse(
        "orders.html",
        {
            "request": request,
            "user": current_user,
            "is_admin": user_is_admin,
            "orders": orders,
            "pickup_points": pickup_points,
            "users": users,
            "flash_message": flash_message,
            "flash_type": flash_type
        }
    )
