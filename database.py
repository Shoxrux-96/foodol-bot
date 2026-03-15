from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update, delete
from models import Base, User, Cafe, CafeAdmin, Food, Order, OrderItem, Channel, Role, OrderStatus, DeliveryType
from config import DATABASE_URL
import math

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

MAX_ADMINS_PER_CAFE = 3


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── User ──────────────────────────────────────────────────────────────────────

async def get_or_create_user(session, telegram_id: int, name: str) -> User:
    r = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = r.scalar_one_or_none()
    if not user:
        user = User(telegram_id=telegram_id, name=name)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def get_user_by_telegram_id(session, telegram_id: int) -> User | None:
    r = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return r.scalar_one_or_none()


async def set_user_phone(session, telegram_id: int, phone: str):
    await session.execute(update(User).where(User.telegram_id == telegram_id).values(phone=phone))
    await session.commit()


async def set_user_role(session, telegram_id: int, role: Role):
    await session.execute(update(User).where(User.telegram_id == telegram_id).values(role=role))
    await session.commit()


async def get_all_admins(session) -> list[User]:
    r = await session.execute(select(User).where(User.role == Role.admin))
    return r.scalars().all()


# ── Cafe ──────────────────────────────────────────────────────────────────────

async def create_cafe(session, name: str) -> Cafe:
    cafe = Cafe(name=name)
    session.add(cafe)
    await session.commit()
    await session.refresh(cafe)
    return cafe


async def update_cafe_location(session, cafe_id: int, lat: float, lon: float):
    await session.execute(update(Cafe).where(Cafe.id == cafe_id).values(latitude=lat, longitude=lon))
    await session.commit()


async def get_all_cafes(session) -> list[Cafe]:
    r = await session.execute(select(Cafe))
    return r.scalars().all()


async def get_cafe_by_id(session, cafe_id: int) -> Cafe | None:
    r = await session.execute(select(Cafe).where(Cafe.id == cafe_id))
    return r.scalar_one_or_none()


async def delete_cafe(session, cafe_id: int):
    admins = await get_cafe_admins(session, cafe_id)
    for admin in admins:
        await remove_cafe_admin(session, cafe_id, admin.id)
    orders_r = await session.execute(select(Order).where(Order.cafe_id == cafe_id))
    order_ids = [o.id for o in orders_r.scalars().all()]
    if order_ids:
        await session.execute(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
    await session.execute(delete(Order).where(Order.cafe_id == cafe_id))
    await session.execute(delete(Food).where(Food.cafe_id == cafe_id))
    await session.execute(delete(Cafe).where(Cafe.id == cafe_id))
    await session.commit()


def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


async def get_nearest_cafe(session, lat: float, lon: float) -> Cafe | None:
    cafes = await get_all_cafes(session)
    cafes = [c for c in cafes if c.latitude and c.longitude]
    if not cafes:
        return None
    return min(cafes, key=lambda c: haversine(lat, lon, c.latitude, c.longitude))


# ── CafeAdmin ─────────────────────────────────────────────────────────────────

async def get_cafe_admins(session, cafe_id: int) -> list[User]:
    r = await session.execute(
        select(User).join(CafeAdmin, CafeAdmin.admin_id == User.id)
        .where(CafeAdmin.cafe_id == cafe_id)
    )
    return r.scalars().all()


async def get_cafes_by_admin(session, admin_user_id: int) -> list[Cafe]:
    r = await session.execute(
        select(Cafe).join(CafeAdmin, CafeAdmin.cafe_id == Cafe.id)
        .where(CafeAdmin.admin_id == admin_user_id)
    )
    return r.scalars().all()


async def add_cafe_admin(session, cafe_id: int, admin_user_id: int) -> tuple[bool, str]:
    # Allaqachon bor?
    r = await session.execute(
        select(CafeAdmin).where(CafeAdmin.cafe_id == cafe_id, CafeAdmin.admin_id == admin_user_id)
    )
    if r.scalar_one_or_none():
        return False, "Bu admin allaqachon ushbu cafega biriktirilgan."
    # Limit tekshirish
    r2 = await session.execute(select(CafeAdmin).where(CafeAdmin.cafe_id == cafe_id))
    if len(r2.scalars().all()) >= MAX_ADMINS_PER_CAFE:
        return False, f"Bir cafega maksimum {MAX_ADMINS_PER_CAFE} ta admin biriktirilishi mumkin."

    session.add(CafeAdmin(cafe_id=cafe_id, admin_id=admin_user_id))
    await session.commit()
    return True, "Muvaffaqiyatli biriktirildi."


async def remove_cafe_admin(session, cafe_id: int, admin_user_id: int):
    await session.execute(
        delete(CafeAdmin).where(CafeAdmin.cafe_id == cafe_id, CafeAdmin.admin_id == admin_user_id)
    )
    # Boshqa cafesi yo'q bo'lsa rolini user ga qaytarish
    other = await get_cafes_by_admin(session, admin_user_id)
    if not other:
        await session.execute(update(User).where(User.id == admin_user_id).values(role=Role.user))
    await session.commit()


# ── Channel ───────────────────────────────────────────────────────────────────

async def add_channel(session, chat_id: int, title: str, chat_type: str) -> Channel:
    r = await session.execute(select(Channel).where(Channel.chat_id == chat_id))
    ch = r.scalar_one_or_none()
    if ch:
        ch.title = title
        ch.chat_type = chat_type
    else:
        ch = Channel(chat_id=chat_id, title=title, chat_type=chat_type)
        session.add(ch)
    await session.commit()
    await session.refresh(ch)
    return ch


async def remove_channel(session, chat_id: int):
    await session.execute(delete(Channel).where(Channel.chat_id == chat_id))
    await session.commit()


async def get_all_channels(session) -> list[Channel]:
    r = await session.execute(select(Channel).order_by(Channel.added_at))
    return r.scalars().all()


async def get_channel_by_id(session, channel_id: int) -> Channel | None:
    r = await session.execute(select(Channel).where(Channel.id == channel_id))
    return r.scalar_one_or_none()

async def create_food(session, cafe_id: int, name: str, price: float, photo: str) -> Food:
    food = Food(cafe_id=cafe_id, name=name, price=price, photo=photo)
    session.add(food)
    await session.commit()
    await session.refresh(food)
    return food


async def update_food(session, food_id: int, **kwargs):
    await session.execute(update(Food).where(Food.id == food_id).values(**kwargs))
    await session.commit()


async def delete_food(session, food_id: int):
    await session.execute(delete(OrderItem).where(OrderItem.food_id == food_id))
    await session.execute(delete(Food).where(Food.id == food_id))
    await session.commit()


async def get_foods_by_cafe(session, cafe_id: int) -> list[Food]:
    r = await session.execute(select(Food).where(Food.cafe_id == cafe_id))
    return r.scalars().all()


async def get_food_by_id(session, food_id: int) -> Food | None:
    r = await session.execute(select(Food).where(Food.id == food_id))
    return r.scalar_one_or_none()


# ── Order ─────────────────────────────────────────────────────────────────────

async def create_order_with_items(session, user_id, cafe_id, items,
                                   delivery_type=DeliveryType.pickup,
                                   delivery_lat=None, delivery_lon=None) -> Order:
    order = Order(user_id=user_id, cafe_id=cafe_id,
                  delivery_type=delivery_type,
                  delivery_lat=delivery_lat, delivery_lon=delivery_lon)
    session.add(order)
    await session.flush()
    for item in items:
        session.add(OrderItem(order_id=order.id, food_id=item["food_id"], quantity=item["quantity"]))
    await session.commit()
    await session.refresh(order)
    return order


async def get_order_items(session, order_id: int) -> list[OrderItem]:
    r = await session.execute(select(OrderItem).where(OrderItem.order_id == order_id))
    return r.scalars().all()


async def get_order_item_by_id(session, item_id: int) -> OrderItem | None:
    r = await session.execute(select(OrderItem).where(OrderItem.id == item_id))
    return r.scalar_one_or_none()


async def update_order_item_quantity(session, item_id: int, new_qty: float):
    await session.execute(update(OrderItem).where(OrderItem.id == item_id).values(quantity=new_qty))
    await session.commit()


async def update_order_status(session, order_id: int, status: OrderStatus):
    await session.execute(update(Order).where(Order.id == order_id).values(status=status))
    await session.commit()


async def get_order_by_id(session, order_id: int) -> Order | None:
    r = await session.execute(select(Order).where(Order.id == order_id))
    return r.scalar_one_or_none()


async def get_orders_by_cafe(session, cafe_id: int, status: OrderStatus = None) -> list[Order]:
    q = select(Order).where(Order.cafe_id == cafe_id)
    if status:
        q = q.where(Order.status == status)
    r = await session.execute(q.order_by(Order.created_at.desc()))
    return r.scalars().all()


async def get_orders_by_user(session, user_id: int, limit: int = 10) -> list[Order]:
    r = await session.execute(
        select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(limit)
    )
    return r.scalars().all()