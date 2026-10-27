"""Discord: DMs check everything; in servers it checks when tagged and flags likely scams on its own."""

from __future__ import annotations

import logging
import re

import discord

from .agent import Checker
from .chat import WELCOME, RateLimiter, is_greeting, limit_reason, worth_checking_in_group
from .config import Settings
from .render import chat_text
from .store import Store

log = logging.getLogger("checkam.discord")
NO_PINGS = discord.AllowedMentions.none()
ALARM = {"scam", "likely_scam"}


def build(settings: Settings, store: Store, checker: Checker) -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    limiter = RateLimiter(settings.user_limit, settings.user_window_seconds)

    async def run_check(message: discord.Message, text: str, quiet: bool) -> None:
        user = store.user_key("discord", message.author.id)
        reason = limit_reason(settings, store, limiter, user)
        if reason:
            if not quiet:
                await message.reply(reason, allowed_mentions=NO_PINGS)
            return
        if quiet:
            report = await checker.check(text, "discord", user)
        else:
            async with message.channel.typing():
                report = await checker.check(text, "discord", user)
        if quiet and report.verdict.verdict not in ALARM:
            return
        await message.reply(chat_text(report, max_len=1950), allowed_mentions=NO_PINGS, suppress_embeds=True)

    @client.event
    async def on_ready() -> None:
        log.info("Discord connected as %s", client.user)

    @client.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot or not client.user:
            return
        text = (message.content or "").strip()
        if not text:
            return
        if message.guild is None:
            await (message.reply(WELCOME) if is_greeting(text) else run_check(message, text, quiet=False))
            return
        if client.user in message.mentions:
            own = re.sub(rf"<@!?{client.user.id}>", "", text).strip()
            replied = getattr(message.reference, "resolved", None) if message.reference else None
            other = (getattr(replied, "content", "") or "").strip()
            await run_check(message, own or other, quiet=False) if (own or other) else await message.reply(WELCOME)
        elif worth_checking_in_group(text):
            await run_check(message, text, quiet=True)

    return client
