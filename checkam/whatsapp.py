"""WhatsApp through Meta's official Cloud API (a webhook). People message the bot's number directly.

Setup: developers.facebook.com -> create app -> add WhatsApp -> use the free test number,
add your phone as a recipient, set the webhook to https://<tunnel>/webhook with WHATSAPP_VERIFY_TOKEN,
and subscribe to `messages`.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging

import httpx
from aiohttp import web

from .agent import Checker
from .chat import WELCOME, RateLimiter, is_greeting, limit_reason
from .config import Settings
from .render import chat_text
from .store import Store

log = logging.getLogger("checkam.whatsapp")


def valid_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not app_secret:
        return True  # signature checks are on once WHATSAPP_APP_SECRET is set
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


def incoming(payload: dict) -> list[tuple[str, str, str]]:
    """(sender phone, message id, text) for every text-like message in a webhook payload."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for m in change.get("value", {}).get("messages", []) or []:
                kind = m.get("type")
                text = ""
                if kind == "text":
                    text = m.get("text", {}).get("body", "")
                elif kind in ("image", "video", "document"):
                    text = m.get(kind, {}).get("caption", "")
                if text.strip():
                    out.append((m.get("from", ""), m.get("id", ""), text.strip()))
    return out


class WhatsApp:
    def __init__(self, settings: Settings, store: Store, checker: Checker):
        self.settings, self.store, self.checker = settings, store, checker
        self.limiter = RateLimiter(settings.user_limit, settings.user_window_seconds)
        self.http = httpx.AsyncClient(timeout=20)
        self.tasks: set[asyncio.Task] = set()

    async def send(self, to: str, text: str, reply_to: str = "") -> None:
        s = self.settings
        body = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4000], "preview_url": False}}
        if reply_to:
            body["context"] = {"message_id": reply_to}
        r = await self.http.post(f"https://graph.facebook.com/{s.whatsapp_graph_version}/{s.whatsapp_phone_number_id}/messages",
                                 json=body, headers={"Authorization": f"Bearer {s.whatsapp_token}"})
        if r.status_code >= 300:
            log.warning("WhatsApp send failed %s: %s", r.status_code, r.text[:300])

    async def handle(self, sender: str, msg_id: str, text: str) -> None:
        if is_greeting(text):
            await self.send(sender, WELCOME, msg_id)
            return
        user = self.store.user_key("whatsapp", sender)
        reason = limit_reason(self.settings, self.store, self.limiter, user)
        if reason:
            await self.send(sender, reason, msg_id)
            return
        report = await self.checker.check(text, "whatsapp", user)
        await self.send(sender, chat_text(report), msg_id)

    async def verify(self, request: web.Request) -> web.Response:
        q = request.query
        if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == self.settings.whatsapp_verify_token and self.settings.whatsapp_verify_token:
            return web.Response(text=q.get("hub.challenge", ""))
        return web.Response(status=403)

    async def receive(self, request: web.Request) -> web.Response:
        body = await request.read()
        if not valid_signature(self.settings.whatsapp_app_secret, body, request.headers.get("X-Hub-Signature-256")):
            return web.Response(status=401)
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return web.Response(status=400)
        for sender, msg_id, text in incoming(payload):
            task = asyncio.create_task(self.handle(sender, msg_id, text))  # reply after acknowledging Meta fast
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        return web.Response(text="ok")

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/webhook", self.verify)
        app.router.add_post("/webhook", self.receive)
        app.router.add_get("/", lambda r: web.Response(text="CheckAm is running."))
        return app
