"""ShopWise: a FastAPI shop backend (Python), January to May 2026.

The story RepoMind should find:
  - a clean layered start: routers -> services -> repositories -> models
  - decisions: pydantic validation, Docker and CI, raw sqlite3 replaced by
    SQLAlchemy (+ Postgres in production), a Redis catalog cache, a payment
    gateway adapter, structlog
  - drift: a sales-report router reads the order repository directly (fixed a
    week later with a ReportService, health back to 100), then a stock
    endpoint and an admin listing call repositories from routers (still
    there at HEAD)
"""
from datetime import datetime

PRIYA = ("Priya Nair", "priya@shopwise.example")
MARCUS = ("Marcus Lee", "marcus@shopwise.example")
SAM = ("Sam Okafor", "sam@shopwise.example")

INIT = ""

# ------------------------------------------------------------------ v1: skeleton

MAIN_V1 = '''from fastapi import FastAPI

app = FastAPI(title="ShopWise")


@app.get("/health")
def health():
    return {"status": "ok"}
'''

CONFIG_V1 = '''import os


class Settings:
    def __init__(self):
        self.database_path = os.environ.get("SHOPWISE_DB", "shopwise.db")
        self.currency = os.environ.get("SHOPWISE_CURRENCY", "USD")


settings = Settings()
'''

PRODUCT_MODEL_V1 = '''from dataclasses import dataclass


@dataclass
class Product:
    id: int
    name: str
    price_cents: int
    stock: int
'''

USER_MODEL_V1 = '''from dataclasses import dataclass


@dataclass
class User:
    id: int
    email: str
    name: str
    is_admin: bool = False
'''

ORDER_MODEL_V1 = '''from dataclasses import dataclass, field


@dataclass
class OrderLine:
    product_id: int
    quantity: int
    unit_price_cents: int


@dataclass
class Order:
    id: int
    user_id: int
    lines: list = field(default_factory=list)
    status: str = "new"

    @property
    def total_cents(self) -> int:
        return sum(line.quantity * line.unit_price_cents for line in self.lines)
'''

# ------------------------------------------------------------------ sqlite repositories

DB_SQLITE = '''import sqlite3

from app.core.config import settings


def get_connection():
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn
'''

PRODUCT_REPO_SQLITE = '''from app.models.product import Product
from app.repositories.db import get_connection


def list_products():
    with get_connection() as conn:
        rows = conn.execute("SELECT id, name, price_cents, stock FROM products ORDER BY name").fetchall()
    return [Product(**dict(row)) for row in rows]


def get_product(product_id: int):
    with get_connection() as conn:
        row = conn.execute("SELECT id, name, price_cents, stock FROM products WHERE id = ?",
                           (product_id,)).fetchone()
    return Product(**dict(row)) if row else None


def update_stock(product_id: int, delta: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE products SET stock = stock + ? WHERE id = ?", (delta, product_id))
'''

PRODUCT_SERVICE_V1 = '''from app.models.product import Product
from app.repositories import product_repository


def list_catalog():
    return [p for p in product_repository.list_products() if p.stock > 0]


def get_product(product_id: int) -> Product:
    product = product_repository.get_product(product_id)
    if product is None:
        raise LookupError(f"product {product_id} not found")
    return product


def reserve_stock(product_id: int, quantity: int) -> Product:
    product = get_product(product_id)
    if product.stock < quantity:
        raise ValueError(f"only {product.stock} of {product.name} left")
    product_repository.update_stock(product_id, -quantity)
    return product
'''

PRODUCTS_ROUTER_V1 = '''from fastapi import APIRouter, HTTPException

from app.services import product_service

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def list_products():
    return product_service.list_catalog()


@router.get("/{product_id}")
def get_product(product_id: int):
    try:
        return product_service.get_product(product_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Product not found")
'''

MAIN_V2 = '''from fastapi import FastAPI

from app.routers import products

app = FastAPI(title="ShopWise")
app.include_router(products.router)


@app.get("/health")
def health():
    return {"status": "ok"}
'''

USER_REPO_SQLITE = '''from app.models.user import User
from app.repositories.db import get_connection


def get_user(user_id: int):
    with get_connection() as conn:
        row = conn.execute("SELECT id, email, name, is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    return User(**dict(row)) if row else None


def find_by_email(email: str):
    with get_connection() as conn:
        row = conn.execute("SELECT id, email, name, is_admin FROM users WHERE email = ?", (email,)).fetchone()
    return User(**dict(row)) if row else None


def create_user(email: str, name: str) -> User:
    with get_connection() as conn:
        cur = conn.execute("INSERT INTO users (email, name) VALUES (?, ?)", (email, name))
    return User(id=cur.lastrowid, email=email, name=name)
'''

USER_SERVICE_V1 = '''from app.repositories import user_repository


def register(email: str, name: str):
    email = email.strip().lower()
    if user_repository.find_by_email(email) is not None:
        raise ValueError("email already registered")
    return user_repository.create_user(email, name.strip())


def get_user(user_id: int):
    user = user_repository.get_user(user_id)
    if user is None:
        raise LookupError(f"user {user_id} not found")
    return user
'''

USERS_ROUTER_V1 = '''from fastapi import APIRouter, HTTPException

from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.post("")
def register(email: str, name: str):
    try:
        return user_service.register(email, name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/{user_id}")
def get_user(user_id: int):
    try:
        return user_service.get_user(user_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="User not found")
'''

MAIN_V3 = '''from fastapi import FastAPI

from app.routers import products, users

app = FastAPI(title="ShopWise")
app.include_router(products.router)
app.include_router(users.router)


@app.get("/health")
def health():
    return {"status": "ok"}
'''

ORDER_REPO_SQLITE = '''from app.models.order import Order, OrderLine
from app.repositories.db import get_connection


def create_order(user_id: int, lines: list) -> Order:
    with get_connection() as conn:
        cur = conn.execute("INSERT INTO orders (user_id, status) VALUES (?, 'new')", (user_id,))
        for line in lines:
            conn.execute("INSERT INTO order_lines (order_id, product_id, quantity, unit_price_cents) "
                         "VALUES (?, ?, ?, ?)", (cur.lastrowid, line.product_id, line.quantity,
                                                 line.unit_price_cents))
    return Order(id=cur.lastrowid, user_id=user_id, lines=lines)


def _load_lines(conn, order_id: int) -> list:
    rows = conn.execute("SELECT product_id, quantity, unit_price_cents FROM order_lines WHERE order_id = ?",
                        (order_id,)).fetchall()
    return [OrderLine(**dict(row)) for row in rows]


def orders_for_user(user_id: int) -> list:
    with get_connection() as conn:
        rows = conn.execute("SELECT id, user_id, status FROM orders WHERE user_id = ?", (user_id,)).fetchall()
        return [Order(lines=_load_lines(conn, row["id"]), **dict(row)) for row in rows]


def list_orders() -> list:
    with get_connection() as conn:
        rows = conn.execute("SELECT id, user_id, status FROM orders").fetchall()
        return [Order(lines=_load_lines(conn, row["id"]), **dict(row)) for row in rows]
'''

ORDER_SERVICE_V1 = '''from app.models.order import OrderLine
from app.repositories import order_repository
from app.services import product_service, user_service


def place_order(user_id: int, items: dict):
    """items: {product_id: quantity}."""
    user_service.get_user(user_id)
    lines = []
    for product_id, quantity in items.items():
        if quantity <= 0:
            raise ValueError("quantities must be positive")
        product = product_service.reserve_stock(product_id, quantity)
        lines.append(OrderLine(product_id=product_id, quantity=quantity, unit_price_cents=product.price_cents))
    return order_repository.create_order(user_id, lines)


def order_history(user_id: int) -> list:
    return order_repository.orders_for_user(user_id)
'''

ORDERS_ROUTER_V1 = '''from fastapi import APIRouter, HTTPException

from app.services import order_service

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("")
def place_order(user_id: int, items: dict):
    try:
        return order_service.place_order(user_id, {int(k): v for k, v in items.items()})
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/user/{user_id}")
def order_history(user_id: int):
    return order_service.order_history(user_id)
'''

MAIN_V4 = '''from fastapi import FastAPI

from app.routers import orders, products, users

app = FastAPI(title="ShopWise")
app.include_router(products.router)
app.include_router(users.router)
app.include_router(orders.router)


@app.get("/health")
def health():
    return {"status": "ok"}
'''

TEST_ORDER_SERVICE = '''import pytest

from app.models.order import Order
from app.models.product import Product
from app.models.user import User
from app.services import order_service


@pytest.fixture
def fake_store(monkeypatch):
    stock = {1: Product(id=1, name="Mug", price_cents=1200, stock=3)}
    created = []
    monkeypatch.setattr("app.repositories.product_repository.get_product", lambda pid: stock.get(pid))
    monkeypatch.setattr("app.repositories.product_repository.update_stock",
                        lambda pid, delta: setattr(stock[pid], "stock", stock[pid].stock + delta))
    monkeypatch.setattr("app.repositories.user_repository.get_user", lambda uid: User(id=uid, email="a@b.c", name="A"))
    monkeypatch.setattr("app.repositories.order_repository.create_order",
                        lambda uid, lines: created.append(Order(id=1, user_id=uid, lines=lines)) or created[-1])
    return stock


def test_order_reserves_stock_and_totals(fake_store):
    order = order_service.place_order(7, {1: 2})
    assert order.total_cents == 2400
    assert fake_store[1].stock == 1


def test_order_rejects_more_than_in_stock(fake_store):
    with pytest.raises(ValueError):
        order_service.place_order(7, {1: 5})
'''

# ------------------------------------------------------------------ pydantic models

PRODUCT_MODEL_PYD = '''from pydantic import BaseModel, Field


class Product(BaseModel):
    id: int
    name: str = Field(min_length=1, max_length=120)
    price_cents: int = Field(ge=0)
    stock: int = Field(ge=0)
'''

USER_MODEL_PYD = '''from pydantic import BaseModel, EmailStr


class User(BaseModel):
    id: int
    email: EmailStr
    name: str
    is_admin: bool = False
'''

ORDER_MODEL_PYD = '''from pydantic import BaseModel, Field


class OrderLine(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)


class Order(BaseModel):
    id: int
    user_id: int
    lines: list[OrderLine] = []
    status: str = "new"

    @property
    def total_cents(self) -> int:
        return sum(line.quantity * line.unit_price_cents for line in self.lines)
'''

DOCKERFILE = '''FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
'''

CI_WORKFLOW = '''name: tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pytest -q
'''

ORDER_SERVICE_V2 = '''from app.models.order import OrderLine
from app.repositories import order_repository
from app.services import product_service, user_service

ALLOWED_TRANSITIONS = {"new": {"paid", "cancelled"}, "paid": {"shipped", "refunded"}, "shipped": {"delivered"}}


def place_order(user_id: int, items: dict):
    """items: {product_id: quantity}."""
    user_service.get_user(user_id)
    lines = []
    for product_id, quantity in items.items():
        if quantity <= 0:
            raise ValueError("quantities must be positive")
        product = product_service.reserve_stock(product_id, quantity)
        lines.append(OrderLine(product_id=product_id, quantity=quantity, unit_price_cents=product.price_cents))
    return order_repository.create_order(user_id, lines)


def order_history(user_id: int) -> list:
    return order_repository.orders_for_user(user_id)


def change_status(order_id: int, new_status: str):
    order = order_repository.get_order(order_id)
    if order is None:
        raise LookupError(f"order {order_id} not found")
    if new_status not in ALLOWED_TRANSITIONS.get(order.status, set()):
        raise ValueError(f"can't move an order from {order.status} to {new_status}")
    return order_repository.set_status(order_id, new_status)
'''

ORDER_REPO_SQLITE_V2 = ORDER_REPO_SQLITE + '''

def get_order(order_id: int):
    with get_connection() as conn:
        row = conn.execute("SELECT id, user_id, status FROM orders WHERE id = ?", (order_id,)).fetchone()
        return Order(lines=_load_lines(conn, row["id"]), **dict(row)) if row else None


def set_status(order_id: int, status: str):
    with get_connection() as conn:
        conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    return get_order(order_id)
'''

ORDERS_ROUTER_V2 = ORDERS_ROUTER_V1 + '''

@router.patch("/{order_id}/status")
def change_status(order_id: int, status: str):
    try:
        return order_service.change_status(order_id, status)
    except LookupError:
        raise HTTPException(status_code=404, detail="Order not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
'''

# ------------------------------------------------------------------ SQLAlchemy

CONFIG_V2 = '''import os


class Settings:
    def __init__(self):
        self.database_url = os.environ.get("DATABASE_URL", "sqlite:///./shopwise.db")
        self.currency = os.environ.get("SHOPWISE_CURRENCY", "USD")
        self.redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self.payment_api_url = os.environ.get("PAYMENT_API_URL", "https://payments.example.com")
        self.payment_api_key = os.environ.get("PAYMENT_API_KEY", "")


settings = Settings()
'''

DB_SQLALCHEMY = '''from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session():
    return SessionLocal()
'''

TABLES = '''from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.repositories.db import Base


class ProductRow(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    price_cents: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer, default=0)


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class OrderRow(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="new")
    lines: Mapped[list["OrderLineRow"]] = relationship(cascade="all, delete-orphan")


class OrderLineRow(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)
'''

PRODUCT_REPO_SA = '''from sqlalchemy import select, update

from app.models.product import Product
from app.repositories.db import get_session
from app.repositories.tables import ProductRow


def _to_model(row: ProductRow) -> Product:
    return Product(id=row.id, name=row.name, price_cents=row.price_cents, stock=row.stock)


def list_products():
    with get_session() as session:
        return [_to_model(row) for row in session.scalars(select(ProductRow).order_by(ProductRow.name))]


def get_product(product_id: int):
    with get_session() as session:
        row = session.get(ProductRow, product_id)
        return _to_model(row) if row else None


def update_stock(product_id: int, delta: int) -> None:
    with get_session() as session:
        session.execute(update(ProductRow).where(ProductRow.id == product_id).values(stock=ProductRow.stock + delta))
        session.commit()
'''

USER_REPO_SA = '''from sqlalchemy import select

from app.models.user import User
from app.repositories.db import get_session
from app.repositories.tables import UserRow


def _to_model(row: UserRow) -> User:
    return User(id=row.id, email=row.email, name=row.name, is_admin=row.is_admin)


def get_user(user_id: int):
    with get_session() as session:
        row = session.get(UserRow, user_id)
        return _to_model(row) if row else None


def find_by_email(email: str):
    with get_session() as session:
        row = session.scalars(select(UserRow).where(UserRow.email == email)).first()
        return _to_model(row) if row else None


def create_user(email: str, name: str) -> User:
    with get_session() as session:
        row = UserRow(email=email, name=name)
        session.add(row)
        session.commit()
        return _to_model(row)
'''

USER_REPO_SA_V2 = USER_REPO_SA + '''

def list_users(limit: int = 100) -> list:
    with get_session() as session:
        return [_to_model(row) for row in session.scalars(select(UserRow).order_by(UserRow.id).limit(limit))]
'''

ORDER_REPO_SA = '''from sqlalchemy import select

from app.models.order import Order, OrderLine
from app.repositories.db import get_session
from app.repositories.tables import OrderLineRow, OrderRow


def _to_model(row: OrderRow) -> Order:
    lines = [OrderLine(product_id=l.product_id, quantity=l.quantity, unit_price_cents=l.unit_price_cents)
             for l in row.lines]
    return Order(id=row.id, user_id=row.user_id, status=row.status, lines=lines)


def create_order(user_id: int, lines: list) -> Order:
    with get_session() as session:
        row = OrderRow(user_id=user_id, lines=[OrderLineRow(product_id=l.product_id, quantity=l.quantity,
                                                            unit_price_cents=l.unit_price_cents) for l in lines])
        session.add(row)
        session.commit()
        return _to_model(row)


def get_order(order_id: int):
    with get_session() as session:
        row = session.get(OrderRow, order_id)
        return _to_model(row) if row else None


def set_status(order_id: int, status: str):
    with get_session() as session:
        row = session.get(OrderRow, order_id)
        row.status = status
        session.commit()
        return _to_model(row)


def orders_for_user(user_id: int) -> list:
    with get_session() as session:
        query = select(OrderRow).where(OrderRow.user_id == user_id).order_by(OrderRow.id.desc())
        return [_to_model(row) for row in session.scalars(query)]


def list_orders() -> list:
    with get_session() as session:
        return [_to_model(row) for row in session.scalars(select(OrderRow))]
'''

ORDER_REPO_SA_PAGED = ORDER_REPO_SA.replace('''def orders_for_user(user_id: int) -> list:
    with get_session() as session:
        query = select(OrderRow).where(OrderRow.user_id == user_id).order_by(OrderRow.id.desc())
        return [_to_model(row) for row in session.scalars(query)]''', '''def orders_for_user(user_id: int, offset: int = 0, limit: int = 50) -> list:
    with get_session() as session:
        query = select(OrderRow).where(OrderRow.user_id == user_id).order_by(OrderRow.id.desc())
        return [_to_model(row) for row in session.scalars(query.offset(offset).limit(limit))]''')

# ------------------------------------------------------------------ Redis cache

CACHE = '''import json

import redis

from app.core.config import settings

_client = redis.Redis.from_url(settings.redis_url, socket_timeout=0.5)
CATALOG_TTL_SECONDS = 300


def get_json(key: str):
    try:
        raw = _client.get(key)
    except redis.RedisError:
        return None              # the cache is an optimisation; never fail a request over it
    return json.loads(raw) if raw else None


def set_json(key: str, value, ttl: int = CATALOG_TTL_SECONDS) -> None:
    try:
        _client.set(key, json.dumps(value), ex=ttl)
    except redis.RedisError:
        pass


def invalidate(*keys: str) -> None:
    try:
        _client.delete(*keys)
    except redis.RedisError:
        pass
'''

PRODUCT_SERVICE_CACHED = '''from app.core import cache
from app.models.product import Product
from app.repositories import product_repository

CATALOG_KEY = "catalog:v1"


def list_catalog():
    cached = cache.get_json(CATALOG_KEY)
    if cached is not None:
        return [Product(**item) for item in cached]
    products = [p for p in product_repository.list_products() if p.stock > 0]
    cache.set_json(CATALOG_KEY, [p.model_dump() for p in products])
    return products


def get_product(product_id: int) -> Product:
    product = product_repository.get_product(product_id)
    if product is None:
        raise LookupError(f"product {product_id} not found")
    return product


def reserve_stock(product_id: int, quantity: int) -> Product:
    product = get_product(product_id)
    if product.stock < quantity:
        raise ValueError(f"only {product.stock} of {product.name} left")
    product_repository.update_stock(product_id, -quantity)
    cache.invalidate(CATALOG_KEY)
    return product
'''

# ------------------------------------------------------------------ payment adapter

PAYMENT_GATEWAY = '''from typing import Protocol

import httpx

from app.core.config import settings


class PaymentDeclined(Exception):
    pass


class PaymentGateway(Protocol):
    def charge(self, amount_cents: int, currency: str, token: str) -> str:
        """Charges the card behind `token`; returns the provider's charge id."""


class HttpPaymentGateway:
    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = base_url or settings.payment_api_url
        self.api_key = api_key or settings.payment_api_key

    def charge(self, amount_cents: int, currency: str, token: str) -> str:
        response = httpx.post(f"{self.base_url}/v1/charges", timeout=10,
                              headers={"Authorization": f"Bearer {self.api_key}"},
                              json={"amount": amount_cents, "currency": currency, "source": token})
        if response.status_code == 402:
            raise PaymentDeclined(response.json().get("message", "card declined"))
        response.raise_for_status()
        return response.json()["id"]
'''

FAKE_GATEWAY = '''class FakePaymentGateway:
    """In-memory gateway for tests and local development."""

    def __init__(self, decline_over_cents: int = None):
        self.decline_over_cents = decline_over_cents
        self.charges = []

    def charge(self, amount_cents: int, currency: str, token: str) -> str:
        if self.decline_over_cents is not None and amount_cents > self.decline_over_cents:
            from app.adapters.payment_gateway import PaymentDeclined
            raise PaymentDeclined("over the test limit")
        self.charges.append((amount_cents, currency, token))
        return f"fake_{len(self.charges)}"
'''

PAYMENT_SERVICE = '''from app.adapters.payment_gateway import HttpPaymentGateway, PaymentDeclined
from app.core.config import settings
from app.repositories import order_repository


class PaymentService:
    def __init__(self, gateway=None):
        self.gateway = gateway or HttpPaymentGateway()

    def pay_order(self, order_id: int, card_token: str):
        order = order_repository.get_order(order_id)
        if order is None:
            raise LookupError(f"order {order_id} not found")
        if order.status != "new":
            raise ValueError("only new orders can be paid")
        try:
            self.gateway.charge(order.total_cents, settings.currency, card_token)
        except PaymentDeclined as exc:
            raise ValueError(f"payment declined: {exc}")
        return order_repository.set_status(order_id, "paid")


payments = PaymentService()
'''

ORDERS_ROUTER_V3 = ORDERS_ROUTER_V2.replace(
    "from app.services import order_service\n",
    "from app.services import order_service\nfrom app.services.payment_service import payments\n") + '''

@router.post("/{order_id}/pay")
def pay(order_id: int, card_token: str):
    try:
        return payments.pay_order(order_id, card_token)
    except LookupError:
        raise HTTPException(status_code=404, detail="Order not found")
    except ValueError as exc:
        raise HTTPException(status_code=402, detail=str(exc))
'''

EMAIL_SENDER = '''import smtplib
from email.message import EmailMessage

from app.core.config import settings


class SmtpEmailSender:
    def __init__(self, host: str = "localhost", port: int = 25):
        self.host = host
        self.port = port

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = "ShopWise <orders@shopwise.example>"
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.send_message(message)


def format_amount(cents: int) -> str:
    return f"{cents / 100:.2f} {settings.currency}"
'''

NOTIFICATION_SERVICE = '''from app.adapters.email_sender import SmtpEmailSender, format_amount
from app.repositories import user_repository


class NotificationService:
    def __init__(self, sender=None):
        self.sender = sender or SmtpEmailSender()

    def send_receipt(self, order) -> None:
        user = user_repository.get_user(order.user_id)
        lines = "\\n".join(f"- {l.quantity} x product {l.product_id}: {format_amount(l.quantity * l.unit_price_cents)}"
                          for l in order.lines)
        self.sender.send(user.email, f"Your ShopWise order #{order.id}",
                         f"Thanks for your order!\\n\\n{lines}\\n\\nTotal: {format_amount(order.total_cents)}")


notifications = NotificationService()
'''

PAYMENT_SERVICE_V2 = PAYMENT_SERVICE.replace(
    "from app.repositories import order_repository\n",
    "from app.repositories import order_repository\nfrom app.services.notification_service import notifications\n").replace(
    '''        return order_repository.set_status(order_id, "paid")''',
    '''        paid = order_repository.set_status(order_id, "paid")
        notifications.send_receipt(paid)
        return paid''')

# ------------------------------------------------------------------ drift and its partial fix

REPORTS_ROUTER_DRIFT = '''from collections import Counter

from fastapi import APIRouter

from app.repositories import order_repository

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/sales")
def sales_report():
    # Quick fix for the finance team: read orders straight from the repository.
    orders = [o for o in order_repository.list_orders() if o.status in ("paid", "shipped", "delivered")]
    revenue = sum(o.total_cents for o in orders)
    by_status = Counter(o.status for o in orders)
    return {"orders": len(orders), "revenue_cents": revenue, "by_status": dict(by_status)}
'''

MAIN_V5 = '''from fastapi import FastAPI

from app.routers import orders, products, reports, users

app = FastAPI(title="ShopWise")
app.include_router(products.router)
app.include_router(users.router)
app.include_router(orders.router)
app.include_router(reports.router)


@app.get("/health")
def health():
    return {"status": "ok"}
'''

PRODUCTS_ROUTER_DRIFT = '''from fastapi import APIRouter, HTTPException

from app.repositories import product_repository
from app.services import product_service

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def list_products():
    return product_service.list_catalog()


@router.get("/{product_id}")
def get_product(product_id: int):
    try:
        return product_service.get_product(product_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Product not found")


@router.get("/{product_id}/stock")
def stock_level(product_id: int):
    # The product page polls this every few seconds; skip the service (and its cache) for fresh numbers.
    product = product_repository.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"product_id": product_id, "stock": product.stock, "low": product.stock < 5}
'''

REPORT_SERVICE = '''from collections import Counter

from app.repositories import order_repository

REVENUE_STATUSES = ("paid", "shipped", "delivered")


def sales_summary() -> dict:
    orders = [o for o in order_repository.list_orders() if o.status in REVENUE_STATUSES]
    return {
        "orders": len(orders),
        "revenue_cents": sum(o.total_cents for o in orders),
        "by_status": dict(Counter(o.status for o in orders)),
    }
'''

REPORTS_ROUTER_FIXED = '''from fastapi import APIRouter

from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/sales")
def sales_report():
    return report_service.sales_summary()
'''

LOGGING = '''import logging

import structlog


def configure(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(message)s")
    structlog.configure(processors=[structlog.processors.add_log_level, structlog.processors.TimeStamper(fmt="iso"),
                                    structlog.processors.JSONRenderer()])


def get_logger(name: str):
    return structlog.get_logger(name)
'''

MAIN_V6 = '''from fastapi import FastAPI

from app.core.logging import configure
from app.routers import orders, products, reports, users

configure()
app = FastAPI(title="ShopWise")
app.include_router(products.router)
app.include_router(users.router)
app.include_router(orders.router)
app.include_router(reports.router)


@app.get("/health")
def health():
    return {"status": "ok"}
'''

DISCOUNT_MODEL = '''from pydantic import BaseModel, Field


class Discount(BaseModel):
    code: str
    percent: int = Field(gt=0, le=90)
    active: bool = True
'''

DISCOUNT_REPO = '''from app.models.discount import Discount

# Codes are managed by marketing in a spreadsheet for now; loaded at startup.
_CODES = {"WELCOME10": Discount(code="WELCOME10", percent=10), "SPRING25": Discount(code="SPRING25", percent=25)}


def find_code(code: str):
    discount = _CODES.get(code.strip().upper())
    return discount if discount and discount.active else None
'''

DISCOUNT_SERVICE = '''from app.repositories import discount_repository


def apply_discount(total_cents: int, code: str = None) -> int:
    if not code:
        return total_cents
    discount = discount_repository.find_code(code)
    if discount is None:
        raise ValueError(f"unknown or expired discount code {code}")
    return total_cents - (total_cents * discount.percent) // 100
'''

ORDER_SERVICE_V3 = '''from app.core.logging import get_logger
from app.models.order import OrderLine
from app.repositories import order_repository
from app.services import discount_service, product_service, user_service

log = get_logger(__name__)
ALLOWED_TRANSITIONS = {"new": {"paid", "cancelled"}, "paid": {"shipped", "refunded"}, "shipped": {"delivered"}}


def place_order(user_id: int, items: dict, discount_code: str = None):
    """items: {product_id: quantity}."""
    user_service.get_user(user_id)
    lines = []
    for product_id, quantity in items.items():
        if quantity <= 0:
            raise ValueError("quantities must be positive")
        product = product_service.reserve_stock(product_id, quantity)
        lines.append(OrderLine(product_id=product_id, quantity=quantity, unit_price_cents=product.price_cents))
    order = order_repository.create_order(user_id, lines)
    payable = discount_service.apply_discount(order.total_cents, discount_code)
    log.info("order_placed", order_id=order.id, user_id=user_id, total_cents=order.total_cents, payable_cents=payable)
    return order


def order_history(user_id: int) -> list:
    return order_repository.orders_for_user(user_id)


def change_status(order_id: int, new_status: str):
    order = order_repository.get_order(order_id)
    if order is None:
        raise LookupError(f"order {order_id} not found")
    if new_status not in ALLOWED_TRANSITIONS.get(order.status, set()):
        raise ValueError(f"can't move an order from {order.status} to {new_status}")
    log.info("order_status_changed", order_id=order_id, old=order.status, new=new_status)
    return order_repository.set_status(order_id, new_status)
'''

ORDER_SERVICE_V4 = ORDER_SERVICE_V3.replace('''def order_history(user_id: int) -> list:
    return order_repository.orders_for_user(user_id)''', '''def order_history(user_id: int, page: int = 1, page_size: int = 20) -> list:
    page = max(page, 1)
    return order_repository.orders_for_user(user_id, offset=(page - 1) * page_size, limit=page_size)''')

ORDERS_ROUTER_V4 = ORDERS_ROUTER_V3.replace('''@router.post("")
def place_order(user_id: int, items: dict):
    try:
        return order_service.place_order(user_id, {int(k): v for k, v in items.items()})''', '''@router.post("")
def place_order(user_id: int, items: dict, discount_code: str = None):
    try:
        return order_service.place_order(user_id, {int(k): v for k, v in items.items()}, discount_code)''')

ORDERS_ROUTER_V5 = ORDERS_ROUTER_V4.replace('''@router.get("/user/{user_id}")
def order_history(user_id: int):
    return order_service.order_history(user_id)''', '''@router.get("/user/{user_id}")
def order_history(user_id: int, page: int = 1):
    return order_service.order_history(user_id, page)''')

USERS_ROUTER_DRIFT = USERS_ROUTER_V1.replace(
    "from app.services import user_service\n",
    "from app.repositories import user_repository\nfrom app.services import user_service\n") + '''

@router.get("/admin/all")
def list_all_users(limit: int = 100):
    # Admin dashboard needs everyone; there is no service method for this yet.
    return user_repository.list_users(limit)
'''

README = '''# ShopWise

Backend for the ShopWise web shop: products, users, orders, payments.

## Architecture

```
app/routers       HTTP endpoints (FastAPI) - call services only
app/services      business rules: stock, orders, payments, discounts, reports
app/repositories  persistence (SQLAlchemy; sqlite locally, Postgres in production)
app/adapters      outside systems: payment provider, email
app/models        pydantic models shared by every layer
app/core          configuration, cache (Redis), logging (structlog)
```

## Run

```
pip install -r requirements.txt
uvicorn app.main:app --reload
```
'''

REQ = {
    1: "fastapi==0.110.0\nuvicorn==0.29.0\n",
    5: "fastapi==0.110.0\nuvicorn==0.29.0\npytest==8.1.1\n",
    6: "fastapi==0.110.0\nuvicorn==0.29.0\npydantic[email]==2.6.4\npytest==8.1.1\n",
    10: "fastapi==0.110.0\nuvicorn==0.29.0\npydantic[email]==2.6.4\nsqlalchemy==2.0.29\npytest==8.1.1\n",
    11: "fastapi==0.110.0\nuvicorn==0.29.0\npydantic[email]==2.6.4\nsqlalchemy==2.0.29\npsycopg2-binary==2.9.9\n"
        "pytest==8.1.1\n",
    12: "fastapi==0.110.0\nuvicorn==0.29.0\npydantic[email]==2.6.4\nsqlalchemy==2.0.29\npsycopg2-binary==2.9.9\n"
        "redis==5.0.3\npytest==8.1.1\n",
    14: "fastapi==0.110.0\nuvicorn==0.29.0\npydantic[email]==2.6.4\nsqlalchemy==2.0.29\npsycopg2-binary==2.9.9\n"
        "redis==5.0.3\nhttpx==0.27.0\npytest==8.1.1\n",
    19: "fastapi==0.110.0\nuvicorn==0.29.0\npydantic[email]==2.6.4\nsqlalchemy==2.0.29\npsycopg2-binary==2.9.9\n"
        "redis==5.0.3\nhttpx==0.27.0\nstructlog==24.1.0\npytest==8.1.1\n",
    23: "fastapi==0.111.0\nuvicorn==0.30.1\npydantic[email]==2.7.4\nsqlalchemy==2.0.31\npsycopg2-binary==2.9.9\n"
        "redis==5.0.6\nhttpx==0.27.0\nstructlog==24.2.0\npytest==8.2.2\n",
}

STORY = [
    {"when": "2026-01-05T10:12:00+05:30", "author": PRIYA, "message": "Initial FastAPI skeleton",
     "files": {"requirements.txt": REQ[1], "app/__init__.py": INIT, "app/main.py": MAIN_V1,
               "app/core/__init__.py": INIT, "app/core/config.py": CONFIG_V1, "app/models/__init__.py": INIT,
               "app/models/product.py": PRODUCT_MODEL_V1, "app/models/user.py": USER_MODEL_V1,
               "app/models/order.py": ORDER_MODEL_V1, ".gitignore": "__pycache__/\n*.db\n.env\n"}},
    {"when": "2026-01-07T15:40:00+05:30", "author": PRIYA, "message": "Add product catalog backed by sqlite",
     "files": {"app/repositories/__init__.py": INIT, "app/repositories/db.py": DB_SQLITE,
               "app/repositories/product_repository.py": PRODUCT_REPO_SQLITE, "app/services/__init__.py": INIT,
               "app/services/product_service.py": PRODUCT_SERVICE_V1, "app/routers/__init__.py": INIT,
               "app/routers/products.py": PRODUCTS_ROUTER_V1, "app/main.py": MAIN_V2}},
    {"when": "2026-01-09T11:05:00+05:30", "author": MARCUS, "message": "Add user registration",
     "files": {"app/repositories/user_repository.py": USER_REPO_SQLITE,
               "app/services/user_service.py": USER_SERVICE_V1, "app/routers/users.py": USERS_ROUTER_V1,
               "app/main.py": MAIN_V3}},
    {"when": "2026-01-12T17:22:00+05:30", "author": PRIYA, "message": "Add orders with stock reservation",
     "files": {"app/repositories/order_repository.py": ORDER_REPO_SQLITE,
               "app/services/order_service.py": ORDER_SERVICE_V1, "app/routers/orders.py": ORDERS_ROUTER_V1,
               "app/main.py": MAIN_V4}},
    {"when": "2026-01-15T09:48:00+05:30", "author": MARCUS, "message": "Add pytest suite for the order service",
     "files": {"requirements.txt": REQ[5], "tests/__init__.py": INIT, "tests/test_order_service.py": TEST_ORDER_SERVICE}},
    {"when": "2026-01-20T14:30:00+05:30", "author": MARCUS,
     "message": "Validate models with pydantic\n\nDataclasses let negative prices and empty names through to the "
                "database. Pydantic models validate at the edge and FastAPI uses them for the OpenAPI schema.",
     "files": {"requirements.txt": REQ[6], "app/models/product.py": PRODUCT_MODEL_PYD,
               "app/models/user.py": USER_MODEL_PYD, "app/models/order.py": ORDER_MODEL_PYD}},
    {"when": "2026-01-26T12:00:00+05:30", "author": SAM, "message": "Add Dockerfile", "files": {"Dockerfile": DOCKERFILE}},
    {"when": "2026-02-02T10:30:00+05:30", "author": SAM, "message": "Run tests in GitHub Actions",
     "files": {".github/workflows/tests.yml": CI_WORKFLOW}},
    {"when": "2026-02-09T16:15:00+05:30", "author": SAM, "message": "Order status transitions",
     "files": {"app/services/order_service.py": ORDER_SERVICE_V2,
               "app/repositories/order_repository.py": ORDER_REPO_SQLITE_V2, "app/routers/orders.py": ORDERS_ROUTER_V2}},
    {"when": "2026-02-16T11:45:00+05:30", "author": PRIYA,
     "message": "Replace raw sqlite3 queries with SQLAlchemy\n\nRaw SQL strings were duplicated across the three "
                "repositories and manual row mapping caused two bugs this month (order lines lost on status updates, "
                "is_admin read as an int). SQLAlchemy gives us mapped tables, one session per call and a single "
                "DATABASE_URL, so production can move to Postgres without touching the repositories. sqlite stays "
                "the local default.",
     "files": {"requirements.txt": REQ[10], "app/core/config.py": CONFIG_V2, "app/repositories/db.py": DB_SQLALCHEMY,
               "app/repositories/tables.py": TABLES, "app/repositories/product_repository.py": PRODUCT_REPO_SA,
               "app/repositories/user_repository.py": USER_REPO_SA,
               "app/repositories/order_repository.py": ORDER_REPO_SA}},
    {"when": "2026-02-18T15:10:00+05:30", "author": SAM, "message": "Use Postgres in production (psycopg2)",
     "files": {"requirements.txt": REQ[11]}},
    {"when": "2026-03-02T10:05:00+05:30", "author": MARCUS,
     "message": "Cache the product catalog in Redis\n\nCatalog reads are about 80% of API traffic and the list "
                "changes only when stock moves. The service caches it for five minutes and invalidates on every "
                "stock change; a Redis outage falls back to the database instead of failing requests.",
     "files": {"requirements.txt": REQ[12], "app/core/cache.py": CACHE,
               "app/services/product_service.py": PRODUCT_SERVICE_CACHED}},
    {"when": "2026-03-12T13:20:00+05:30", "author": SAM,
     "message": "Put the payment provider behind a gateway adapter\n\nCheckout is about to call a real payment API. "
                "Keeping the HTTP details in app/adapters behind a PaymentGateway interface lets the order flow be "
                "tested with an in-memory gateway and lets us switch providers without touching services.",
     "files": {"requirements.txt": REQ[14], "app/adapters/__init__.py": INIT,
               "app/adapters/payment_gateway.py": PAYMENT_GATEWAY, "app/adapters/fake_gateway.py": FAKE_GATEWAY,
               "app/services/payment_service.py": PAYMENT_SERVICE, "app/routers/orders.py": ORDERS_ROUTER_V3}},
    {"when": "2026-03-20T18:40:00+05:30", "author": SAM, "message": "Email a receipt after payment",
     "files": {"app/adapters/email_sender.py": EMAIL_SENDER, "app/services/notification_service.py": NOTIFICATION_SERVICE,
               "app/services/payment_service.py": PAYMENT_SERVICE_V2}},
    {"when": "2026-03-27T19:55:00+05:30", "author": SAM,
     "message": "Hotfix: sales report for finance\n\nFinance needs revenue numbers before the quarterly review. "
                "Reads the order repository directly for now; should move into a service.",
     "files": {"app/routers/reports.py": REPORTS_ROUTER_DRIFT, "app/main.py": MAIN_V5}},
    {"when": "2026-04-17T12:35:00+05:30", "author": MARCUS, "message": "Live stock level on the product page",
     "files": {"app/routers/products.py": PRODUCTS_ROUTER_DRIFT}},
    {"when": "2026-04-03T10:50:00+05:30", "author": PRIYA,
     "message": "Move the sales report into ReportService\n\nThe reports router was the only router reading a "
                "repository. The numbers now come from report_service, which the admin dashboard will reuse.",
     "files": {"app/services/report_service.py": REPORT_SERVICE, "app/routers/reports.py": REPORTS_ROUTER_FIXED}},
    {"when": "2026-04-10T16:00:00+05:30", "author": MARCUS,
     "message": "Structured logging with structlog\n\nPlain log lines were impossible to search in production. "
                "structlog emits JSON with the order and user ids as fields.",
     "files": {"requirements.txt": REQ[19], "app/core/logging.py": LOGGING, "app/main.py": MAIN_V6}},
    {"when": "2026-04-24T11:25:00+05:30", "author": SAM, "message": "Discount codes at checkout",
     "files": {"app/models/discount.py": DISCOUNT_MODEL, "app/repositories/discount_repository.py": DISCOUNT_REPO,
               "app/services/discount_service.py": DISCOUNT_SERVICE, "app/services/order_service.py": ORDER_SERVICE_V3,
               "app/routers/orders.py": ORDERS_ROUTER_V4}},
    {"when": "2026-05-01T09:30:00+05:30", "author": MARCUS, "message": "Paginate order history",
     "files": {"app/repositories/order_repository.py": ORDER_REPO_SA_PAGED,
               "app/services/order_service.py": ORDER_SERVICE_V4, "app/routers/orders.py": ORDERS_ROUTER_V5}},
    {"when": "2026-05-08T17:45:00+05:30", "author": PRIYA, "message": "Admin endpoint listing all users",
     "files": {"app/repositories/user_repository.py": USER_REPO_SA_V2, "app/routers/users.py": USERS_ROUTER_DRIFT}},
    {"when": "2026-05-15T10:00:00+05:30", "author": SAM, "message": "Bump dependencies", "files": {"requirements.txt": REQ[23]}},
    {"when": "2026-05-22T14:15:00+05:30", "author": PRIYA, "message": "README with the architecture overview",
     "files": {"README.md": README}},
]

# Steps are listed by topic; commit them in date order (dates carry different time zones).
STORY.sort(key=lambda step: datetime.fromisoformat(step["when"]))

# ------------------------------------------------------------------ live code-review demo

BAD_ORDERS_ROUTER = ORDERS_ROUTER_V5.replace(
    "from fastapi import APIRouter, HTTPException\n",
    "from fastapi import APIRouter, HTTPException\nfrom sqlalchemy import text\n\n"
    "from app.repositories.db import get_session\n") + '''

@router.get("/search")
def search_orders(status: str):
    with get_session() as session:
        rows = session.execute(text(f"SELECT id, user_id, status FROM orders WHERE status = '{status}'")).fetchall()
    return [dict(row._mapping) for row in rows]
'''

BAD_REPORT_SERVICE = REPORT_SERVICE + '''

def average_order_value() -> int:
    orders = [o for o in order_repository.list_orders() if o.status in REVENUE_STATUSES]
    return sum(o.total_cents for o in orders) // len(orders)
'''

BAD_PAYMENT_SERVICE = PAYMENT_SERVICE_V2.replace('''        paid = order_repository.set_status(order_id, "paid")
        notifications.send_receipt(paid)
        return paid''', '''        paid = order_repository.set_status(order_id, "paid")
        try:
            notifications.send_receipt(paid)
        except Exception:
            pass
        return paid''')

BAD_GATEWAY = PAYMENT_GATEWAY.replace('''class HttpPaymentGateway:
    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = base_url or settings.payment_api_url
        self.api_key = api_key or settings.payment_api_key''', '''PAYMENT_API_SECRET = "shopwise-live-7d1f0c9a8b2e4f6a91c3"


class HttpPaymentGateway:
    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = base_url or settings.payment_api_url
        self.api_key = api_key or PAYMENT_API_SECRET''')

BAD_COMMIT = {
    "when": "2026-06-02T18:20:00+05:30", "author": SAM,
    "message": "Order search, average order value, quieter checkout",
    "files": {"app/routers/orders.py": BAD_ORDERS_ROUTER, "app/services/report_service.py": BAD_REPORT_SERVICE,
              "app/services/payment_service.py": BAD_PAYMENT_SERVICE, "app/adapters/payment_gateway.py": BAD_GATEWAY},
}

ORDER_REPO_SEARCH = ORDER_REPO_SA_PAGED + '''

MAX_SEARCH_RESULTS = 200


def orders_with_status(status: str) -> list:
    with get_session() as session:
        query = (select(OrderRow).where(OrderRow.status == status).order_by(OrderRow.id.desc())
                 .limit(MAX_SEARCH_RESULTS))
        return [_to_model(row) for row in session.scalars(query)]
'''

FIXED_ORDER_SERVICE = ORDER_SERVICE_V4 + '''

def search(status: str) -> list:
    if status not in {"new", "paid", "shipped", "delivered", "cancelled", "refunded"}:
        raise ValueError(f"unknown status {status}")
    return order_repository.orders_with_status(status)
'''

FIXED_ORDERS_ROUTER = ORDERS_ROUTER_V5.replace(
    "from app.services import order_service\n",
    "from app.models.order import Order\nfrom app.services import order_service\n") + '''

@router.get("/search", response_model=list[Order])
def search_orders(status: str):
    try:
        return order_service.search(status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
'''

FIXED_REPORT_SERVICE = REPORT_SERVICE + '''

def average_order_value() -> int:
    orders = [o for o in order_repository.list_orders() if o.status in REVENUE_STATUSES]
    if not orders:
        return 0
    return sum(o.total_cents for o in orders) // len(orders)
'''

FIXED_PAYMENT_SERVICE = PAYMENT_SERVICE_V2.replace(
    "from app.core.config import settings\n",
    "from app.core.config import settings\nfrom app.core.logging import get_logger\n").replace(
    "\n\nclass PaymentService:", "\nlog = get_logger(__name__)\n\n\nclass PaymentService:").replace(
    '''        paid = order_repository.set_status(order_id, "paid")
        notifications.send_receipt(paid)
        return paid''', '''        paid = order_repository.set_status(order_id, "paid")
        try:
            notifications.send_receipt(paid)
        except Exception:
            # The payment went through; a failed receipt must not fail it. Logged with the traceback for a resend.
            log.exception("receipt_not_sent", order_id=order_id)
        return paid''')

FIX_COMMIT = {
    "when": "2026-06-03T11:05:00+05:30", "author": PRIYA,
    "message": "Fix review findings: parameterised order search, empty report, receipt errors, payment key",
    "files": {"app/routers/orders.py": FIXED_ORDERS_ROUTER, "app/services/order_service.py": FIXED_ORDER_SERVICE,
              "app/repositories/order_repository.py": ORDER_REPO_SEARCH,
              "app/services/report_service.py": FIXED_REPORT_SERVICE,
              "app/services/payment_service.py": FIXED_PAYMENT_SERVICE,
              "app/adapters/payment_gateway.py": PAYMENT_GATEWAY},
}
