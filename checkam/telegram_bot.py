"""Telegram: private chats check everything; in groups it only speaks up about likely scams (or when asked)."""

from __future__ import annotations

import logging

from telegram import LinkPreviewOptions, Message, ReplyParameters, Update
from telegram.constants import ChatAction, ChatType
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from .agent import Checker
from .chat import WELCOME, RateLimiter, is_greeting, limit_reason, worth_checking_in_group
from .config import Settings
from .render import chat_text
from .store import Store

log = logging.getLogger("checkam.telegram")
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
ALARM = {"scam", "likely_scam"}


def text_of(msg: Message | None) -> str:
    return ((msg.text or msg.caption or "") if msg else "").strip()


class TelegramBot:
    def __init__(self, settings: Settings, store: Store, checker: Checker):
        self.settings, self.store, self.checker = settings, store, checker
        self.limiter = RateLimiter(settings.user_limit, settings.user_window_seconds)

    async def on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(WELCOME)

    async def on_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/check <text>, or /check as a reply to someone else's message."""
        msg = update.effective_message
        own = " ".join(context.args or []).strip()
        target = msg.reply_to_message if not own and msg.reply_to_message else msg
        text = own or text_of(msg.reply_to_message)
        if not text:
            await msg.reply_text("Reply /check to the message you want checked, or send /check followed by the text.")
            return
        await self.run_check(update, text, target, quiet=False)

    async def on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        text = text_of(msg)
        if not text or (msg.from_user and msg.from_user.is_bot):
            return
        if update.effective_chat.type == ChatType.PRIVATE:
            if is_greeting(text):
                await msg.reply_text(WELCOME)
                return
            await self.run_check(update, text, msg, quiet=False)
            return
        me = context.bot
        mentioned = me.username and f"@{me.username}".lower() in text.lower()
        replied_to_me = msg.reply_to_message and msg.reply_to_message.from_user and msg.reply_to_message.from_user.id == me.id
        if mentioned or replied_to_me:
            other = text_of(msg.reply_to_message) if mentioned and msg.reply_to_message and not replied_to_me else ""
            await self.run_check(update, other or text.replace(f"@{me.username}", "").strip(), msg.reply_to_message if other else msg, quiet=False)
        elif worth_checking_in_group(text):
            await self.run_check(update, text, msg, quiet=True)

    async def run_check(self, update: Update, text: str, target: Message, quiet: bool) -> None:
        user = self.store.user_key("telegram", update.effective_user.id if update.effective_user else 0)
        reason = limit_reason(self.settings, self.store, self.limiter, user)
        if reason:
            if not quiet:
                await target.reply_text(reason)
            return
        if not quiet:
            await update.effective_chat.send_action(ChatAction.TYPING)
        report = await self.checker.check(text, "telegram", user)
        if quiet and report.verdict.verdict not in ALARM:
            return  # in groups, only interrupt for likely scams
        await update.effective_chat.send_message(
            chat_text(report), link_preview_options=NO_PREVIEW,
            reply_parameters=ReplyParameters(message_id=target.message_id, allow_sending_without_reply=True))


def build(settings: Settings, store: Store, checker: Checker) -> Application:
    bot = TelegramBot(settings, store, checker)
    # Generous timeouts: Telegram's 5-second default is too short on slow mobile and Nigerian networks.
    app = (Application.builder().token(settings.telegram_token)
           .connect_timeout(30).read_timeout(30).write_timeout(30).get_updates_read_timeout(60).build())
    app.add_handler(CommandHandler(["start", "help"], bot.on_start))
    app.add_handler(CommandHandler("check", bot.on_check))
    app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, bot.on_message))
    return app
