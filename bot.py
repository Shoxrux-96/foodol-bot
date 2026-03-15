import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import ChatMemberUpdated
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, OWNER_ID
from database import init_db, AsyncSessionLocal, add_channel, remove_channel
from models import Role
import handlers_owner
import handlers_admin
import handlers_user

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def setup_owner(bot: Bot):
    async with AsyncSessionLocal() as session:
        from database import get_or_create_user, set_user_role
        try:
            # Owner ni yaratish — telegram_id OWNER_ID
            user = await get_or_create_user(session, OWNER_ID, "Owner")
            await set_user_role(session, OWNER_ID, Role.owner)
            logger.info(f"Owner ({OWNER_ID}) tayyor. DB id: {user.id}")
        except Exception as e:
            logger.warning(f"Owner setup xato: {e}")


async def db_middleware(handler, event, data):
    async with AsyncSessionLocal() as session:
        data["session"] = session
        return await handler(event, data)


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.middleware(db_middleware)

    # ── Bot guruhga qo'shildi / chiqarildi ───────────────────────────────────
    @dp.my_chat_member()
    async def on_chat_member_update(event: ChatMemberUpdated, session, bot: Bot):
        chat = event.chat
        new_status = event.new_chat_member.status

        # Faqat guruh va kanallar
        if chat.type not in ("group", "supergroup", "channel"):
            return

        if new_status in ("administrator", "member"):
            # Botni guruhga admin/a'zo qilib qo'shishdi
            ch = await add_channel(session, chat.id, chat.title or "Nomsiz", chat.type)
            logger.info(f"Guruh qo'shildi: {chat.title} ({chat.id})")

            # Ownerga xabar
            type_label = "📢 Kanal" if chat.type == "channel" else "👥 Guruh"
            try:
                await bot.send_message(
                    OWNER_ID,
                    f"✅ Bot yangi {type_label.lower()}ga qo'shildi!\n\n"
                    f"{type_label}: <b>{chat.title}</b>\n"
                    f"ID: <code>{chat.id}</code>\n\n"
                    f"Endi bu guruhga '📢 Guruh/Kanal xabari' orqali xabar yuborishingiz mumkin.",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        elif new_status in ("left", "kicked", "restricted"):
            # Bot guruhdan chiqarildi
            await remove_channel(session, chat.id)
            logger.info(f"Guruh o'chirildi: {chat.title} ({chat.id})")

            try:
                await bot.send_message(
                    OWNER_ID,
                    f"⚠️ Bot guruhdan chiqarildi: <b>{chat.title}</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    # Router tartib: owner > admin > user
    dp.include_router(handlers_owner.router)
    dp.include_router(handlers_admin.router)
    dp.include_router(handlers_user.router)

    await init_db()
    await setup_owner(bot)

    logger.info("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())