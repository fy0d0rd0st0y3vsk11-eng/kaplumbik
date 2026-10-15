
import logging

import discord
from discord.ext import commands

from app.core.config import settings


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
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
        logger.info("Kaplumbik komut altyapısı hazırlanıyor.")

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

    bot = KaplumbikBot()
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
