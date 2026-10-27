"""Shared by every chat app: when to check, limits, and the welcome text."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Awaitable, Callable

from .config import Settings
from .evidence import extract
from .reasoner import language
from .sources import patterns
from .store import Store

WELCOME = (
    "Forward me any message you're not sure about: a loan offer, a 'you've won' text, an investment, "
    "a link, an account number. I'll check it and tell you if it's a scam, and why.\n\n"
    "I never ask for your PIN, OTP, BVN or passwords. Don't send them to anyone."
)
LIMITED = "You've sent a lot of checks in a short time. Please wait a few minutes and try again."
FAILED = "Sorry, something went wrong while checking. Please send it again."
BUSY = "I've reached today's limit of checks. Please try again tomorrow."
CHECKING = {"English": "🔎 Checking…", "Nigerian Pidgin": "🔎 I dey check am…"}
GREETING = re.compile(r"(?i)^\s*(hi|hello|hey|good (morning|afternoon|evening)|start|help|menu|how far|thanks?|thank you|ok(ay)?)\W*$")

log = logging.getLogger("checkam.chat")


def checking(text: str) -> str:
    """Sent at once, so people know the bot is working during the 10-30 seconds a check takes."""
    return CHECKING[language(text)]


@asynccontextmanager
async def keep_typing(send: Callable[[], Awaitable[object]], every: float):
    """Repeats a "typing…" signal until the block ends. Apps drop it on their own (Telegram after 5 s, WhatsApp 25 s)."""
    async def loop() -> None:
        while True:
            try:
                await send()
            except Exception as exc:  # a missed typing signal never matters enough to stop a check
                log.debug("typing signal failed: %s", exc)
            await asyncio.sleep(every)

    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()


class RateLimiter:
    """Per-person sliding window, so one person (or a spammer) can't burn the shared budget."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit, self.window = limit, window_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self.hits[key]
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


def worth_checking_in_group(text: str) -> bool:
    """In groups, stay quiet unless a message has something checkable or a scam pattern."""
    ents = extract(text)
    if ents.urls or ents.accounts:
        return True
    found, _ = patterns.scan(text)
    return any(e.weight >= 2 for e in found)


def is_greeting(text: str) -> bool:
    return bool(GREETING.match(text))


def limit_reason(settings: Settings, store: Store, limiter: RateLimiter, user: str) -> str | None:
    if not limiter.allow(user):
        return LIMITED
    if store.checks_since(time.time() - 86400) >= settings.daily_cap:
        return BUSY
    return None
