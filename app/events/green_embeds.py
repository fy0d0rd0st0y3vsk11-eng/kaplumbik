"""Shared green swirl embed theme for Kaplumbik's Discord responses."""
from __future__ import annotations

import logging
from typing import Any

import discord

log = logging.getLogger("kaplumbik.embeds")

GREEN = 0x2E8B57
FOOTER = "〰️ ･ﾟ🌿 Mahzen · Kaplumbik 🌿･ﾟ 〰️"
DEFAULT_DESCRIPTION = "🌿 Kaplumbik burada."


def make_green_embed(
    description: str | None = None,
    *,
    title: str | None = None,
    embed: discord.Embed | None = None,
) -> discord.Embed:
    """Create a consistently styled green embed or theme an existing embed."""
    result = embed.copy() if embed is not None else discord.Embed(
        title=title,
        description=description or DEFAULT_DESCRIPTION,
        color=GREEN,
    )
    result.color = discord.Color(GREEN)
    # Avoid adding the footer repeatedly when an embed is passed through helpers.
    current_footer = result.footer.text or ""
    if current_footer != FOOTER:
        result.set_footer(text=FOOTER)
    return result


async def send_green_message(destination: Any, *args: Any, **kwargs: Any) -> Any:
    """Send a channel or DM message with the shared green theme."""
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

    if embed is None and embeds:
        embeds = [make_green_embed(embed=item) for item in embeds]
    elif embed is not None:
        embed = make_green_embed(embed=embed)
    elif isinstance(content, str) and len(content) <= 4096:
        embed = make_green_embed(content)
        content = None
    elif isinstance(content, str):
        log.warning("Long message left as plain text to avoid truncation.")

    if embed is None and not embeds and content is None:
        embed = make_green_embed()
    if embeds is not None:
        kwargs["embeds"] = embeds
    elif embed is not None:
        kwargs["embed"] = embed
    if content is not None:
        kwargs["content"] = content
    return await destination.send(*args, **kwargs)


async def send_green_response(interaction: discord.Interaction, *args: Any, **kwargs: Any) -> Any:
    """Send an interaction response using the green theme without losing options."""
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

    if embed is None and embeds:
        embeds = [make_green_embed(embed=item) for item in embeds]
    elif embed is not None:
        embed = make_green_embed(embed=embed)
    elif isinstance(content, str):
        if len(content) <= 4096:
            embed = make_green_embed(content)
            content = None
        else:
            # Preserve long content instead of silently truncating it.
            log.warning("Long interaction response left as plain text to avoid truncation.")

    if embed is None and not embeds and content is None:
        embed = make_green_embed()

    if embeds is not None:
        kwargs["embeds"] = embeds
    elif embed is not None:
        kwargs["embed"] = embed
    if content is not None:
        kwargs["content"] = content

    return await interaction.response.send_message(*args, **kwargs)


async def send_green_followup(interaction: discord.Interaction, *args: Any, **kwargs: Any) -> Any:
    """Send a follow-up response using the green theme."""
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

    if embed is None and embeds:
        embeds = [make_green_embed(embed=item) for item in embeds]
    elif embed is not None:
        embed = make_green_embed(embed=embed)
    elif isinstance(content, str):
        if len(content) <= 4096:
            embed = make_green_embed(content)
            content = None
        else:
            log.warning("Long follow-up left as plain text to avoid truncation.")

    if embed is None and not embeds and content is None:
        embed = make_green_embed()

    if embeds is not None:
        kwargs["embeds"] = embeds
    elif embed is not None:
        kwargs["embed"] = embed
    if content is not None:
        kwargs["content"] = content

    return await interaction.followup.send(*args, **kwargs)
