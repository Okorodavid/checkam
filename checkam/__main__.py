"""CLI: check, refresh, stats, run, zetaris.

  python -m checkam check "Congrats! Pay N5,000 to unlock your loan: opay-loans.xyz"
  python -m checkam refresh        # download phishing blocklists + SEC notices
  python -m checkam run            # start every chat platform that has a token in .env
  python -m checkam zetaris        # register CheckAm's data in Zetaris and check it loads
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time

import httpx

from .agent import Checker
from .config import load_settings
from .render import chat_text, detail_text
from . import zetaris
from .sources import regulators, threats
from .store import Store


def _utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except AttributeError:
            pass


async def _check(settings, store, text: str, as_json: bool, short: bool) -> None:
    checker = Checker(settings, store)
    try:
        zetaris.loaded_from = await zetaris.load(settings, checker.client)
        report = await checker.check(text)
    finally:
        await checker.aclose()
    if as_json:
        v = report.verdict
        print(json.dumps({
            "verdict": v.verdict, "headline": v.headline, "advice": v.advice, "reasoner": v.reasoner,
            "reasons": [{"text": r.text, "evidence": r.evidence} for r in v.reasons],
            "evidence": [e.__dict__ for e in report.evidence], "notes": v.notes, "trace": v.trace, "seconds": round(report.seconds, 2),
        }, indent=2, ensure_ascii=False))
    else:
        print(chat_text(report) if short else detail_text(report))


async def _refresh(store) -> None:
    async with httpx.AsyncClient(headers={"User-Agent": "CheckAm/0.1"}) as client:
        counts = await threats.refresh(store, client)
        for name, n in counts.items():
            print(f"{name}: {n:,} entries")
        n = await regulators.refresh(store, client)
        print(f"SEC Nigeria notices: {n} saved ({store.notice_count()} in index)")
        rows = store.warned_aliases()
        if rows:
            zetaris.export_notices(rows)
            print(f"Exported {len(rows)} operator names to {zetaris.NOTICES.name} for Zetaris")


async def _zetaris(settings) -> int:
    if not settings.zetaris_api_key:
        print("Set ZETARIS_API_KEY (and ZETARIS_REST_URL if not http://localhost:8888/api/v1.0) in .env first.")
        return 1
    async with httpx.AsyncClient() as client:
        for line in await zetaris.setup(settings, client):
            print(line)
        print("Data layer:", await zetaris.load(settings, client))
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8()
    p = argparse.ArgumentParser(prog="checkam", description="Forward a suspicious message, get a verdict with evidence.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check one message (or - to read stdin)")
    c.add_argument("text")
    c.add_argument("--json", action="store_true")
    c.add_argument("--short", action="store_true", help="only the chat reply")
    sub.add_parser("refresh", help="download blocklists and regulator notices")
    s = sub.add_parser("stats", help="checks per verdict")
    s.add_argument("--days", type=float, default=7)
    sub.add_parser("run", help="start Telegram, Discord and WhatsApp (whichever have tokens)")
    sub.add_parser("zetaris", help="register CheckAm's data in Zetaris and check it loads")
    p.add_argument("--env", default=".env")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose or args.cmd == "run" else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = load_settings(args.env)
    store = Store(settings.db_path)

    if args.cmd == "check":
        text = sys.stdin.read() if args.text == "-" else args.text
        asyncio.run(_check(settings, store, text, args.json, args.short))
    elif args.cmd == "refresh":
        asyncio.run(_refresh(store))
    elif args.cmd == "stats":
        stats = store.stats(time.time() - args.days * 86400)
        print(json.dumps(stats, indent=2) if stats else "No checks yet.")
    elif args.cmd == "zetaris":
        return asyncio.run(_zetaris(settings))
    elif args.cmd == "run":
        from .serve import serve
        if not (settings.telegram_token or settings.discord_token or settings.whatsapp_token):
            print("No chat tokens set. Add TELEGRAM_BOT_TOKEN, DISCORD_BOT_TOKEN or WHATSAPP_TOKEN to .env.")
            return 1
        print(f"Reasoning with: {settings.reasoner}. Blocklist entries: {store.threat_count():,}.")
        try:
            asyncio.run(serve(settings, store))
        except KeyboardInterrupt:
            print("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
