"""cockpit-cards: the cockpit's cards on Hermes's Telegram bot (PLAN-HERMES H2, H14).

With `notify.telegram.via = "hermes"` in the cockpit's config.lua, the cockpit's host daemon no
longer talks to Telegram: it keeps its cards (an urgent question, a failure, a session stuck at
its usage limit, a message) and serves them through the Session API (`notify.pending`). This
plugin is the delivery: it polls that list, sends each new card to Tristan's chat with its
buttons (silent when the card says so: the cockpit's night), edits a card once its rev changes
(answered, closed, later, a limit card's new text), and routes a tap or a text reply to a card
to `notify.answer` / `notify.open` / `notify.later`, every act with a `why`. The answer itself
goes through the cockpit's own checks (the same question still open, never twice).

Deterministic on purpose: no model call decides whether a card goes out or what a tap means.
Settings (plugins.entries.cockpit-cards.settings): chat_id (Tristan's chat, required),
poll_s (default 8). Its delivery state is $HERMES_HOME/state/cockpit-cards.json.
"""

import asyncio
import html
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

NVC_API = os.path.expanduser(os.environ.get("NVC_API", "~/.local/bin/nvc-api"))
PREFIX = "nvc"
KEEP_S = 7 * 86400
FIRST_RUN_MAX_AGE_S = 24 * 3600
API_TIMEOUT_S = 90
BACKOFF_MAX_S = 300
DONE = {"notify.open": "Opening it in the cockpit.",
        "notify.later": "Later: it comes back in an hour if it still waits."}


async def call_api(method: str, args: dict, why: str | None = None) -> dict:
    """One Session API call as hermes; a CLI that fails or says nothing is an `unavailable` answer."""
    cmd = [NVC_API, method, json.dumps(args), "--as", "hermes"]
    if why:
        cmd += ["--why", why]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), API_TIMEOUT_S)
        return json.loads(out.decode() or "{}") or {
            "ok": False, "error": {"code": "unavailable", "message": err.decode()[-300:] or "no answer"}}
    except (OSError, ValueError, asyncio.TimeoutError) as e:
        return {"ok": False, "error": {"code": "unavailable", "message": f"nvc-api: {type(e).__name__}: {e}"}}


def render(card: dict) -> tuple[str, list]:
    """(html, button rows of (label, callback_data)) for the card as it is now."""
    text = card.get("html") or html.escape(card.get("text") or "")
    if card.get("state") == "closed":
        return text + "\n\n<b>" + html.escape(card.get("closed") or "closed") + "</b>", []
    if card.get("state") == "later":
        until = card.get("until")
        when = time.strftime("%H:%M", time.localtime(until)) if until else "later"
        return text + f"\n\n<i>later: it comes back at {when} if it still waits</i>", []
    rows = []
    for row in card.get("buttons") or []:
        rows.append([(b["label"], f"{PREFIX}:{card['card']}:{b['action']}") for b in row])
    return text, rows


def parse_callback(data: str) -> tuple[str, str] | None:
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != PREFIX or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def act_for(card: str, action: str) -> tuple[str, dict, str] | None:
    """(method, args, why) for a tap."""
    if action.isdigit():
        return ("notify.answer", {"card": card, "option": int(action)},
                f"Tristan tapped option {action} on the card in Telegram")
    if action == "o":
        return "notify.open", {"card": card}, "Tristan tapped 'open in the cockpit' on Telegram"
    if action == "l":
        return "notify.later", {"card": card}, "Tristan tapped 'later' on Telegram"
    return None


class Relay:
    """Card delivery state and the poll; the Telegram side comes in as `send`/`edit` callables."""

    def __init__(self, chat_id: int, state_path: str, call=call_api):
        self.chat_id = int(chat_id)
        self.state_path = state_path
        self.call = call
        self.send = None  # async (html, rows, silent) -> message_id
        self.edit = None  # async (message_id, html, rows) -> None
        self.wake = asyncio.Event()
        self.down = None
        self.failures = 0
        self.notice = None
        self.first_run = not os.path.exists(state_path)
        self.state = self._load()

    def _load(self) -> dict:
        try:
            with open(self.state_path) as f:
                data = json.load(f)
            return data if isinstance(data.get("cards"), dict) else {"cards": {}}
        except (OSError, ValueError):
            return {"cards": {}}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.state_path), mode=0o700, exist_ok=True)
        tmp = self.state_path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, self.state_path)

    def card_of_message(self, message_id: int) -> str | None:
        for cid, rec in self.state["cards"].items():
            if rec.get("msg") == message_id:
                return cid
        return None

    def _say_once(self, key: str, level, msg: str, *args) -> None:
        if self.notice != key:
            self.notice = key
            logger.log(level, "cockpit-cards: " + msg, *args)

    async def poll_once(self, now: float | None = None) -> int:
        """Sync every card once; returns how many messages were sent or edited."""
        now = time.time() if now is None else now
        res = await self.call("notify.pending", {"closed": True})
        if not res.get("ok"):
            err = res.get("error") or {}
            self.failures += 1
            if self.down is None:
                self.down = now
            self._say_once("down", logging.WARNING, "the cockpit's API does not answer (%s: %s); "
                           "cards wait until it does", err.get("code"), err.get("message"))
            return 0
        self.failures = 0
        if self.down is not None:
            logger.info("cockpit-cards: the cockpit's API answers again after %ds", now - self.down)
            self.down = None
        result = res["result"]
        if result.get("via") != "hermes":
            self._say_once("via", logging.WARNING, "the cockpit sends its cards itself "
                           "(notify.telegram.via is %r): nothing to relay", result.get("via"))
            return 0
        self.notice = None
        done = 0
        for card in result.get("cards") or []:
            try:
                done += await self.sync(card, now)
            except Exception as e:  # one card must not stop the others; it is retried next poll
                logger.error("cockpit-cards: card %s: %s", card.get("card"), e)
        seen = {c.get("card") for c in result.get("cards") or []}
        for cid in [c for c, r in self.state["cards"].items() if c not in seen and now - r.get("at", 0) > KEEP_S]:
            del self.state["cards"][cid]
        self.first_run = False
        self.save()
        return done

    async def sync(self, card: dict, now: float) -> int:
        cid, rec = card["card"], self.state["cards"].get(card["card"])
        if rec is None:
            # A card closed or put off before it was ever delivered needs no message; on the very
            # first run, only what is recent goes out, not a week of history.
            if card.get("state") != "open":
                return 0
            if self.first_run and now - float(card.get("at") or now) > FIRST_RUN_MAX_AGE_S:
                self.state["cards"][cid] = {"msg": None, "rev": card.get("rev"), "state": "skipped", "at": now}
                return 0
            text, rows = render(card)
            msg = await self.send(text, rows, bool(card.get("silent")))
            self.state["cards"][cid] = {"msg": msg, "rev": card.get("rev"), "state": card["state"], "at": now}
            self.save()
            return 1
        if rec.get("msg") is None or (rec.get("rev") == card.get("rev") and rec.get("state") == card.get("state")):
            return 0
        text, rows = render(card)
        await self.edit(rec["msg"], text, rows)
        rec.update(rev=card.get("rev"), state=card.get("state"), at=now)
        self.save()
        return 1

    async def tap(self, data: str) -> tuple[bool, str]:
        parsed = parse_callback(data)
        act = parsed and act_for(*parsed)
        if not act:
            return False, "Nothing was sent: unknown button."
        res = await self.call(*act)
        self.wake.set()
        if res.get("ok"):
            return True, (res.get("result") or {}).get("message") or DONE.get(act[0], "Done.")
        return False, (res.get("error") or {}).get("message") or "Nothing was sent."

    async def reply(self, card: str, text: str) -> str:
        res = await self.call("notify.answer", {"card": card, "text": text},
                              "Tristan replied to the card on Telegram in his own words")
        self.wake.set()
        if res.get("ok"):
            return (res.get("result") or {}).get("message") or "Sent."
        return (res.get("error") or {}).get("message") or "Nothing was sent."

    def interval(self, poll_s: float) -> float:
        """The wait before the next poll: every refused or unanswered poll doubles it, up to
        BACKOFF_MAX_S, because the cockpit audits every API call, refused ones too."""
        return min(BACKOFF_MAX_S, poll_s * 2 ** min(self.failures, 10))

    async def run(self, poll_s: float) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception as e:
                self.failures += 1
                logger.error("cockpit-cards: poll failed: %s", e)
            try:
                await asyncio.wait_for(self.wake.wait(), self.interval(poll_s))
            except asyncio.TimeoutError:
                pass
            self.wake.clear()


_current = {"task": None, "relay": None}


def register(ctx):
    chat_id = ctx.get_config("chat_id")
    if not chat_id:
        logger.error("cockpit-cards: plugins.entries.cockpit-cards.settings.chat_id is not set; "
                     "no cards will be delivered")
        return
    from hermes_constants import get_hermes_home

    state_path = os.path.join(str(get_hermes_home()), "state", "cockpit-cards.json")
    poll_s = float(ctx.get_config("poll_s", 8) or 8)

    def wire(app, adapter):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.error import BadRequest
        from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, MessageHandler, filters

        relay = Relay(chat_id, state_path)

        def markup(rows):
            return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in row]
                                         for row in rows]) if rows else None

        async def send(text, rows, silent):
            msg = await app.bot.send_message(relay.chat_id, text, parse_mode="HTML", reply_markup=markup(rows),
                                             disable_notification=silent, disable_web_page_preview=True)
            return msg.message_id

        async def edit(message_id, text, rows):
            try:
                await app.bot.edit_message_text(text, chat_id=relay.chat_id, message_id=message_id,
                                                parse_mode="HTML", reply_markup=markup(rows),
                                                disable_web_page_preview=True)
            except BadRequest as e:
                # an unchanged text, or a message too old to edit, needs nothing more
                if "not modified" not in str(e).lower() and "can't be edited" not in str(e).lower():
                    raise

        relay.send, relay.edit = send, edit

        async def on_tap(update, context):
            q = update.callback_query
            if q.message is None or q.message.chat.id != relay.chat_id:
                await q.answer("Not for this chat.")
                raise ApplicationHandlerStop
            ok, text = await relay.tap(q.data)
            await q.answer(text[:190], show_alert=not ok)
            raise ApplicationHandlerStop

        class CardReply(filters.MessageFilter):
            def filter(self, message):
                r = message.reply_to_message
                return (message.chat.id == relay.chat_id and r is not None
                        and relay.card_of_message(r.message_id) is not None)

        async def on_reply(update, context):
            m = update.effective_message
            card = relay.card_of_message(m.reply_to_message.message_id)
            await m.reply_text(await relay.reply(card, m.text))
            raise ApplicationHandlerStop

        # group -1 runs before the core handlers, and ApplicationHandlerStop keeps a handled tap or
        # reply from also reaching the agent; everything else falls through untouched
        app.add_handler(CallbackQueryHandler(on_tap, pattern=rf"^{PREFIX}:"), group=-1)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.REPLY & CardReply(), on_reply),
                        group=-1)
        old = _current["task"]
        if old is not None and not old.done():
            old.cancel()
        _current["relay"] = relay
        _current["task"] = asyncio.get_running_loop().create_task(relay.run(poll_s))
        logger.info("cockpit-cards: relaying the cockpit's cards to chat %s every %ss", relay.chat_id, poll_s)

    ctx.register_telegram_handler(wire)
