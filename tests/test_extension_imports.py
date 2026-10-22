import asyncio
import discord
from discord.ext import commands

EXTENSIONS = [
    "app.events.announcements",
    "app.events.rsvp",
    "app.events.assistant_features",
    "app.events.mahzen_commands",
    "app.events.scheduler",
    "app.seri.commands",
    "app.events.community",
    "app.events.security",
    "app.events.backups",
]

def test_discord_extensions_import_and_register_command_definitions():
    import importlib
    for name in EXTENSIONS:
        module = importlib.import_module(name)
        assert callable(module.setup)

def test_all_extensions_load_without_duplicate_slash_commands():
    async def load_all():
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        try:
            for extension in EXTENSIONS:
                await bot.load_extension(extension)
            names = [command.name for command in bot.tree.get_commands()]
            assert len(names) == len(set(names)), "Duplicate slash-command names would prevent clean startup"
        finally:
            await bot.close()
    asyncio.run(load_all())
