"""Runs every configured chat app on one event loop, sharing one checker, database and daily cap."""

from __future__ import annotations

import asyncio
import logging

from . import zetaris
from .agent import Checker
from .config import Settings
from .store import Store

log = logging.getLogger("checkam.serve")


async def serve(settings: Settings, store: Store) -> None:
    checker = Checker(settings, store)
    stops = []
    try:
        zetaris.loaded_from = await zetaris.load(settings, checker.client)
        log.info("Data layer: %s", zetaris.loaded_from)
        if settings.whatsapp_token:
            from aiohttp import web

            from .whatsapp import WhatsApp
            runner = web.AppRunner(WhatsApp(settings, store, checker).app())
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", settings.port).start()
            log.info("WhatsApp webhook listening on http://localhost:%s/webhook", settings.port)
            stops.append(runner.cleanup)
        if settings.telegram_token:
            from .telegram_bot import build as build_telegram
            tg = build_telegram(settings, store, checker)
            for attempt in range(1, 4):  # a slow network shouldn't stop the whole service
                try:
                    await tg.initialize()
                    break
                except Exception as exc:
                    if attempt == 3:
                        raise
                    log.warning("Telegram didn't answer (%s), retrying", exc)
                    await asyncio.sleep(5 * attempt)
            await tg.updater.start_polling()
            await tg.start()
            log.info("Telegram polling as @%s", tg.bot.username)

            async def stop_tg() -> None:
                await tg.updater.stop()
                await tg.stop()
                await tg.shutdown()
            stops.append(stop_tg)
        if settings.discord_token:
            from .discord_bot import build as build_discord
            client = build_discord(settings, store, checker)
            async with client:
                await client.start(settings.discord_token)  # runs until the process stops
        else:
            await asyncio.Event().wait()
    finally:
        for stop in reversed(stops):
            try:
                await stop()
            except Exception as exc:  # pragma: no cover
                log.warning("shutdown: %s", exc)
        await checker.aclose()
