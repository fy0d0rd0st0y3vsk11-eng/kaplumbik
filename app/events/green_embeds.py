"""Shared green swirl embed theme for Kaplumbik's Discord responses."""
from __future__ import annotations

import logging
import re
from typing import Any

import discord

log = logging.getLogger("kaplumbik.embeds")
GREEN = 0x2E8B57
FOOTER = "〰️ ･ﾟ🌿 Mahzen · Kaplumbik 🌿･ﾟ 〰️"
DEFAULT_DESCRIPTION = "🌿 Kaplumbik burada."
_PING_TOKEN_RE = re.compile(r"@everyone|@here|<@!?[0-9]+>|<@&[0-9]+>")


def make_green_embed(description: str | None = None, *, title: str | None = None,
                     embed: discord.Embed | None = None) -> discord.Embed:
    """Create a consistently styled green embed or theme an existing embed."""
    result = embed.copy() if embed is not None else discord.Embed(
        title=title, description=description or DEFAULT_DESCRIPTION, color=GREEN
    )
    result.color = discord.Color(GREEN)
    if (result.footer.text or "") != FOOTER:
        result.set_footer(text=FOOTER)
    return result


def _prepare(content: str | None, embed: Any, embeds: Any):
    # Mentions inside embeds do not ping. Keep ping tokens in message content
    # and place the remaining announcement text in the embed.
    if embed is None and not embeds and isinstance(content, str):
        tokens = list(dict.fromkeys(_PING_TOKEN_RE.findall(content)))
        if tokens:
            body = _PING_TOKEN_RE.sub("", content).strip()
            if len(body) <= 4096:
                content = " ".join(tokens)
                embed = make_green_embed(body or None)
            else:
                log.warning("Long message with pings left as plain text to avoid truncation.")
        elif len(content) <= 4096:
            embed = make_green_embed(content)
            content = None
        else:
            log.warning("Long message left as plain text to avoid truncation.")
    if embed is None and embeds:
        embeds = [make_green_embed(embed=item) for item in embeds]
    elif embed is not None:
        embed = make_green_embed(embed=embed)
    if embed is None and not embeds and content is None:
        embed = make_green_embed()
    return content, embed, embeds


def _extract_args(args: tuple, kwargs: dict):
    content = kwargs.pop("content", None)
    embed = kwargs.pop("embed", None)
    embeds = kwargs.pop("embeds", None)
    if args:
        first, *remaining = args
        if isinstance(first, str):
            content = first if content is None else content
        elif isinstance(first, discord.Embed):
            embed = first if embed is None else embed
        else:
            remaining.insert(0, first)
        args = tuple(remaining)
    content, embed, embeds = _prepare(content, embed, embeds)
    if embeds is not None:
        kwargs["embeds"] = embeds
    elif embed is not None:
        kwargs["embed"] = embed
    if content is not None:
        kwargs["content"] = content
    return args, kwargs


async def send_green_response(interaction: discord.Interaction, *args: Any, **kwargs: Any) -> Any:
    """Send an interaction response using the green theme without losing options."""
    args, kwargs = _extract_args(args, kwargs)
    return await interaction.response.send_message(*args, **kwargs)


async def send_green_followup(interaction: discord.Interaction, *args: Any, **kwargs: Any) -> Any:
    """Send a follow-up response using the green theme."""
    args, kwargs = _extract_args(args, kwargs)
    return await interaction.followup.send(*args, **kwargs)


async def send_green_message(destination: Any, *args: Any, **kwargs: Any) -> Any:
    """Send a channel or DM message with the shared green theme."""
    args, kwargs = _extract_args(args, kwargs)
    return await destination.send(*args, **kwargs)


async def send_green_reply(message: Any, *args: Any, **kwargs: Any) -> Any:
    """Reply to a Discord message with the shared green theme."""
    args, kwargs = _extract_args(args, kwargs)
    return await message.reply(*args, **kwargs)
