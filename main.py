import logging
from telegram.ext import Application

from app.bot.handlers import register_handlers
from app.config import load_settings
from app.db import Database
from app.security import SecretBox


async def post_init(application: Application):
    settings = application.bot_data["settings"]
    db = Database(settings.database_url)
    await db.open()
    application.bot_data["db"] = db
    application.bot_data["secret_box"] = SecretBox(settings.encryption_key)
    logging.getLogger(__name__).info("Manage bot initialized.")


async def post_shutdown(application: Application):
    db = application.bot_data.get("db")
    if db:
        await db.close()


def main():
    settings = load_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    application = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data["settings"] = settings
    register_handlers(application)
    application.run_polling(drop_pending_updates=True, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
