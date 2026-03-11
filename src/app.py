from fastapi import FastAPI, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
import os

from src.database import init_db, get_db
from src.models import User, Product, Order, Role, Category

app = FastAPI(title="Магазин обуви")

# Add session middleware
app.add_middleware(SessionMiddleware, secret_key="your-secret-key-here-change-in-production")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates")

# Initialize database on startup
@app.on_event("startup")
def startup_event():
    init_db()


# Dependency to get current user from session
def get_current_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    return user


# Dependency to require login
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
    sort: str = None
):
    current_user = get_current_user(request, db)
    
    # Base query
    query = db.query(Product)
    
    # Apply filters only if user is logged in (for now, all logged users have same access)
    if current_user:
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                (Product.name.like(search_term)) |
                (Product.description.like(search_term)) |
                (Product.article.like(search_term))
            )
        
        if category:
            query = query.join(Product.category).filter(Product.category.has(name=category))
        
        # Apply sorting
        if sort == "price_asc":
            query = query.order_by(Product.price.asc())
        elif sort == "price_desc":
            query = query.order_by(Product.price.desc())
        elif sort == "name":
            query = query.order_by(Product.name.asc())
        elif sort == "discount":
            query = query.order_by(Product.discount.desc())
    
    products = query.all()
    
    # Get categories for filter
    categories = db.query(Category).all()
    category_names = [cat.name for cat in categories]
    
    return templates.TemplateResponse(
        "products.html",
        {
            "request": request,
            "user": current_user,
            "products": products,
            "categories": category_names,
            "current_search": search or "",
            "current_category": category or "",
            "current_sort": sort or ""
        }
    )


@app.get("/orders", response_class=HTMLResponse)
async def orders_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_login)
):
    # For now, show all orders (will be restricted later)
    orders = db.query(Order).all()
    
    return templates.TemplateResponse(
        "orders.html",
        {
            "request": request,
            "user": current_user,
            "orders": orders
        }
    )
