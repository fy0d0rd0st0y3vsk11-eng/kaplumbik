import importlib

def test_discord_extensions_import_and_register_command_definitions():
    modules = [
        "app.events.community",
        "app.events.security",
        "app.events.backups",
        "app.seri.commands",
        "app.events.assistant_features",
    ]
    for name in modules:
        module=importlib.import_module(name)
        assert callable(module.setup)
