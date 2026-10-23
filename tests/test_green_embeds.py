import asyncio

import discord

from app.events.green_embeds import FOOTER, GREEN, make_green_embed, send_green_response


class FakeResponse:
    def __init__(self):
        self.args = ()
        self.kwargs = None

    async def send_message(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        return "sent"


class FakeInteraction:
    def __init__(self):
        self.response = FakeResponse()


def test_green_embed_uses_theme_and_footer():
    embed = make_green_embed("Test message", title="Test")
    assert embed.color.value == GREEN
    assert embed.description == "Test message"
    assert embed.title == "Test"
    assert embed.footer.text == FOOTER


def test_green_response_converts_plain_text_to_embed():
    interaction = FakeInteraction()
    result = asyncio.run(send_green_response(interaction, "Hello Mahzen", ephemeral=True))

    assert result == "sent"
    assert interaction.response.kwargs["ephemeral"] is True
    embed = interaction.response.kwargs["embed"]
    assert embed.description == "Hello Mahzen"
    assert embed.color.value == GREEN
    assert embed.footer.text == FOOTER
    assert "content" not in interaction.response.kwargs


def test_green_response_preserves_everyone_ping_in_content():
    interaction = FakeInteraction()
    asyncio.run(send_green_response(interaction, "@everyone Oyun 20.00'de başlıyor", ephemeral=False))

    assert interaction.response.kwargs["content"] == "@everyone"
    embed = interaction.response.kwargs["embed"]
    assert embed.description == "Oyun 20.00'de başlıyor"
    assert embed.color.value == GREEN
