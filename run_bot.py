import logging
import os
import threading

import discord
from discord import app_commands
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
        self.tree.on_error = self._handle_app_command_error

    async def _handle_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, "original", None) or error
        if isinstance(original, app_commands.MissingPermissions):
            message = "Bu komut için gerekli yönetici iznine sahip değilsin."
        else:
            logger.error(
                "Slash komutu başarısız: %s",
                type(original).__name__,
                exc_info=(type(original), original, original.__traceback__),
            )
            message = "Komut çalışırken bir hata oluştu. Hata kaydı oluşturuldu; birazdan tekrar dene."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.exception("Slash komut hata mesajı gönderilemedi.")

    async def setup_hook(self):
        logger.info("Kaplumbik hazırlanıyor...")

        await self.load_extension("app.events.announcements")
        logger.info("Etkinlik duyuru sistemi yüklendi.")

        await self.load_extension("app.events.rsvp")
        logger.info("Etkinlik katılım butonları yüklendi.")

        await self.load_extension("app.events.assistant_features")
        logger.info("AI, profil ve oyun bağlantısı özellikleri yüklendi.")

        await self.load_extension("app.events.mahzen_commands")
        logger.info("Mahzen kişi tanıtımı ve çekiliş komutları yüklendi.")

        await self.load_extension("app.events.scheduler")
        logger.info("Zamanlanmış duyuru sistemi yüklendi.")

        await self.load_extension("app.seri.commands")
        logger.info("Mahzen ortak seri sistemi yüklendi.")

        await self.load_extension("app.events.community")
        logger.info("Mahzen topluluk, oyun profili, anket, öneri ve görev sistemleri yüklendi.")

        await self.load_extension("app.events.security")
        logger.info("Mahzen doğrulama, anti-raid ve moderasyon güvenliği yüklendi.")

        await self.load_extension("app.events.backups")
        logger.info("Günlük veri tabanı yedekleme sistemi yüklendi.")

        # Slash komutlarını Discord'a kaydet.
        # Test sunucusu ID'si verilirse komutlar o sunucuda hemen görünür;
        # verilmezse global kayıt yapılır (yayılması daha uzun sürebilir).
        guild_id = os.getenv("DISCORD_GUILD_ID", "").strip()
        if guild_id.isdigit():
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info("%s slash komutu test sunucusuna kaydedildi.", len(synced))
        else:
            synced = await self.tree.sync()
            logger.info("%s global slash komutu Discord'a kaydedildi.", len(synced))

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
