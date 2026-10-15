import logging
import os
import threading

import discord
from discord.ext import commands
from waitress import serve

from app import create_app
from app.core.config import settings


logging.basicConfig(
    level=getattr(
        logging,
        settings.log_level.upper(),
        logging.INFO,
    ),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("kaplumbik")


class KaplumbikBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="!",
            intents=intents,
        )

    async def setup_hook(self):
        logger.info("Kaplumbik hazırlanıyor...")

        await self.load_extension("app.events.announcements")
        logger.info("Etkinlik duyuru sistemi yüklendi.")

        await self.load_extension("app.events.rsvp")
        logger.info("Etkinlik katılım butonları yüklendi.")

    async def on_ready(self):
        logger.info(
            "Kaplumbik Discord'a bağlandı: %s (ID: %s)",
            self.user,
            self.user.id if self.user else "unknown",
        )


def main():
    if not settings.discord_token:
        raise RuntimeError(
            "DISCORD_TOKEN ayarlanmamış. "
            "Tokenı kodun içine yazma; ortam değişkeni kullan."
        )

    # Flask uygulamasını ve veritabanını hazırla.
    flask_app = create_app()

    # Render Web Service için HTTP portunu dinle; bot aynı süreçte çalışır.
    port = int(os.getenv("PORT", "10000"))
    web_thread = threading.Thread(
        target=serve,
        kwargs={"app": flask_app, "host": "0.0.0.0", "port": port},
        name="kaplumbik-dashboard",
        daemon=True,
    )
    web_thread.start()
    logger.info("Yönetim paneli HTTP sunucusu başlatıldı (port %s).", port)

    # Bot çalıştığı sürece Flask uygulama bağlamını açık tut.
    with flask_app.app_context():
        bot = KaplumbikBot()
        bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
