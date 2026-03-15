from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.orm import declarative_base
from datetime import datetime
import enum

Base = declarative_base()


class Role(str, enum.Enum):
    user = "user"
    admin = "admin"
    owner = "owner"


class OrderStatus(str, enum.Enum):
    new = "new"
    accepted = "accepted"
    rejected = "rejected"
    ready = "ready"
    delivering = "delivering"
    delivered = "delivered"


class DeliveryType(str, enum.Enum):
    pickup = "pickup"
    delivery = "delivery"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    role = Column(Enum(Role), default=Role.user)
    created_at = Column(DateTime, default=datetime.utcnow)


class Cafe(Base):
    __tablename__ = "cafes"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    address = Column(String, nullable=True)


class CafeAdmin(Base):
    __tablename__ = "cafe_admins"
    __table_args__ = (UniqueConstraint("cafe_id", "admin_id"),)

    id = Column(Integer, primary_key=True)
    cafe_id = Column(Integer, ForeignKey("cafes.id"), nullable=False)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)


class Food(Base):
    __tablename__ = "foods"

    id = Column(Integer, primary_key=True)
    cafe_id = Column(Integer, ForeignKey("cafes.id"), nullable=False)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    photo = Column(String, nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    cafe_id = Column(Integer, ForeignKey("cafes.id"), nullable=False)
    delivery_type = Column(Enum(DeliveryType), default=DeliveryType.pickup)
    delivery_lat = Column(Float, nullable=True)
    delivery_lon = Column(Float, nullable=True)
    status = Column(Enum(OrderStatus), default=OrderStatus.new)
    created_at = Column(DateTime, default=datetime.utcnow)


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    food_id = Column(Integer, ForeignKey("foods.id"), nullable=False)
    quantity = Column(Float, default=1.0)


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, nullable=False)
    title = Column(String, nullable=False)
    chat_type = Column(String, default="group")
    added_at = Column(DateTime, default=datetime.utcnow)