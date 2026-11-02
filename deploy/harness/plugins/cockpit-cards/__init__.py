"""cockpit-cards: the cockpit's cards on Hermes's Telegram bot, only those that need Tristan now
(PLAN-HERMES H2, H14; SOUL.md P8).

With `notify.telegram.via = "hermes"` in the cockpit's config.lua, the cockpit's host daemon no
longer talks to Telegram: it keeps its cards (an urgent question, a failure, a session stuck at
its usage limit, a message) and serves them through the Session API (`notify.pending`). This
plugin polls that list and decides, by the rule in its settings, which card reaches the phone:

    plugins.entries.cockpit-cards.settings.relay:
      send: [blocking, failure]       card kinds that need his decision now
      held_failures: [rate_limit]     failure types somebody else fixes (the cockpit's limit rule)
      held_when_kept_alive: true      a failure of a chat keep-alive watches is keep-alive's
      tell_me_every_s: 60             how often his "tell me when ..." watches are looked at

A held card is not lost: it goes to the held log in the delivery state, which the ops tool
`cards_held` reads for "what's up?" and the morning briefing. A chat Tristan asked to be told
about (ops `tellme_add`, state/tell-me.json) gets its cards through whatever their kind, and a
watched PR one message once it is ready to merge, merged or closed.

One message per chat per episode: a card is filed under its inbox item ("dev-1/3d76bde7/
blocking#e4": one per question, failure or turn), and a newer card of the same item (a "later"
that came back) edits that message instead of sending another. A message is sent silent when the
card says so (the cockpit's night), edited once its rev changes (answered, closed, later), and a
tap or a text reply to it goes to `notify.answer` / `notify.open` / `notify.later`, every act
with a `why`. No model call decides any of that.

Settings: chat_id (Tristan's chat, required), poll_s (default 8), relay (above). The delivery
state is $HERMES_HOME/state/cockpit-cards.json.
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
HELD_MAX = 300
FIRST_RUN_MAX_AGE_S = 24 * 3600
API_TIMEOUT_S = 90
BACKOFF_MAX_S = 300
# Without a rule in the settings only questions and permissions go out: the one kind whose
# missed message leaves an agent stuck.
MINIMAL_RULE = {"send": ["blocking"], "held_failures": [], "held_when_kept_alive": False, "tell_me_every_s": 60}
HELD_WHY = {"limit": "a usage limit the cockpit handles", "message": "a message, nothing to decide",
            "review": "a result to review, nothing blocks"}
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


def thread_of(card: dict) -> str:
    """The message a card belongs to: its inbox item, which is one per chat and episode."""
    if card.get("item"):
        return str(card["item"])
    if card.get("vm") and card.get("id") and card.get("episode") is not None:
        return f"{card['vm']}/{card['id']}/{card.get('kind')}#e{card['episode']}"
    return "card:" + str(card["card"])


def load_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def pr_verdict(pr: dict) -> str | None:
    """What a watched PR has come to, as the cockpit's finish line reads it (nvc.wait): `ready`
    (open, no draft, every check passed, approved, or clean with no review), `merged`, `closed`,
    None (not yet), or `clean?` when only its merge state (session.get) can tell."""
    state = str(pr.get("state") or "").upper()
    if state == "MERGED":
        return "merged"
    if state == "CLOSED":
        return "closed"
    ci = pr.get("ci") or {}
    if pr.get("draft") or not ci.get("total") or ci.get("fail") or ci.get("pending"):
        return None
    if pr.get("review") == "APPROVED":
        return "ready"
    if pr.get("review") in (None, ""):
        if "merge_state" not in pr:
            return "clean?"
        return "ready" if pr["merge_state"] == "CLEAN" else None
    return None


class Relay:
    """Card delivery state and the poll; the Telegram side comes in as `send`/`edit` callables."""

    def __init__(self, chat_id: int, state_path: str, call=call_api, rule: dict | None = None):
        self.chat_id = int(chat_id)
        self.state_path = state_path
        state_dir = os.path.dirname(state_path)
        self.watches_path = os.path.join(state_dir, "keep-alive.json")
        self.tell_me_path = os.path.join(state_dir, "tell-me.json")
        self.call = call
        if not rule:
            logger.error("cockpit-cards: plugins.entries.cockpit-cards.settings.relay is not set: only "
                         "questions and permissions are relayed (install.sh writes the rule)")
        self.rule = dict(MINIMAL_RULE, **(rule or {}))
        self.send = None  # async (html, rows, silent) -> message_id
        self.edit = None  # async (message_id, html, rows) -> None
        self.wake = asyncio.Event()
        self.down = None
        self.failures = 0
        self.notice = None
        self.night = False
        self.told_at = None
        self.first_run = not os.path.exists(state_path)
        self.state = self._load()

    def _load(self) -> dict:
        data = load_json(self.state_path, {})
        if not isinstance(data, dict) or not isinstance(data.get("cards"), dict):
            return {"cards": {}, "threads": {}, "held": []}
        data.setdefault("threads", {})
        data.setdefault("held", [])
        # a state from before threads: each delivered card was its own message
        for cid, rec in list(data["cards"].items()):
            if "msg" not in rec:
                continue
            if rec["msg"] is None:
                data["cards"][cid] = {"held": "older than a day when the relay first ran", "at": rec.get("at", 0)}
                continue
            key = "card:" + cid
            data["threads"][key] = {"msg": rec["msg"], "card": cid, "rev": rec.get("rev"),
                                    "state": rec.get("state"), "at": rec.get("at", 0)}
            data["cards"][cid] = {"thread": key, "at": rec.get("at", 0)}
        return data

    def save(self) -> None:
        save_json(self.state_path, self.state)

    def card_of_message(self, message_id: int) -> str | None:
        for t in self.state["threads"].values():
            if t.get("msg") == message_id:
                return t.get("card")
        return None

    def _say_once(self, key: str, level, msg: str, *args) -> None:
        if self.notice != key:
            self.notice = key
            logger.log(level, "cockpit-cards: " + msg, *args)

    # ---------------------------------------------------------------- the rule
    def tell_me(self, now: float) -> list:
        data = load_json(self.tell_me_path, {})
        watches = data.get("watches", []) if isinstance(data, dict) else []
        return [w for w in watches if isinstance(w, dict)]

    def kept_alive(self, vm, sid) -> bool:
        data = load_json(self.watches_path, {})
        watches = data.get("watches", []) if isinstance(data, dict) else []
        return any(w.get("vm") == vm and w.get("id") == sid for w in watches)

    async def held_why(self, card: dict, now: float) -> str | None:
        """None when the card goes to Telegram, else why it is kept for Tristan's asking."""
        kind, vm, sid = card.get("kind"), card.get("vm"), card.get("id")
        if kind != "limit" and vm and sid and any(
                w.get("vm") == vm and w.get("id") == sid and float(w.get("until") or 0) > now
                for w in self.tell_me(now)):
            return None
        if kind not in self.rule["send"]:
            return HELD_WHY.get(kind, f"{kind} cards are not relayed")
        if kind != "failure":
            return None
        if self.rule.get("held_when_kept_alive") and self.kept_alive(vm, sid):
            return "keep-alive revives it"
        if self.rule.get("held_failures") and vm and sid:
            got = await self.call("session.get", {"vm": vm, "id": sid})
            ftype = ((got.get("result") or {}).get("failure") or {}).get("type") if got.get("ok") else None
            if ftype in self.rule["held_failures"]:
                return f"a {ftype} failure the cockpit's account rules handle"
        return None

    def hold(self, card: dict, why: str, now: float) -> None:
        self.state["cards"][card["card"]] = {"held": why, "at": now}
        self.state["held"].append({
            "card": card["card"], "kind": card.get("kind"), "vm": card.get("vm"), "id": card.get("id"),
            "name": card.get("name"), "text": (card.get("text") or "")[:600],
            "at": float(card.get("at") or now), "why": why})
        cut = now - KEEP_S
        self.state["held"] = [h for h in self.state["held"] if h.get("at", 0) > cut][-HELD_MAX:]

    # ---------------------------------------------------------------- the poll
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
        self.night = bool(result.get("night"))
        cards = result.get("cards") or []
        done = 0
        for card in cards:
            try:
                done += await self.sync(card, now)
            except Exception as e:  # one card must not stop the others; it is retried next poll
                logger.error("cockpit-cards: card %s: %s", card.get("card"), e)
        try:
            done += await self.check_told(now)
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.error("cockpit-cards: tell-me watches: %s", e)
        seen = {c.get("card") for c in cards}
        for cid in [c for c, r in self.state["cards"].items() if c not in seen and now - r.get("at", 0) > KEEP_S]:
            del self.state["cards"][cid]
        live = {r.get("thread") for r in self.state["cards"].values()}
        for key in [k for k, t in self.state["threads"].items() if k not in live and now - t.get("at", 0) > KEEP_S]:
            del self.state["threads"][key]
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
                self.state["cards"][cid] = {"held": "older than a day when the relay first ran", "at": now}
                return 0
            why = await self.held_why(card, now)
            if why:
                self.hold(card, why, now)
                self.save()
                return 0
            key = thread_of(card)
            text, rows = render(card)
            t = self.state["threads"].get(key)
            if t and t.get("msg") is not None:
                await self.edit(t["msg"], text, rows)
            else:
                t = {"msg": await self.send(text, rows, bool(card.get("silent")))}
                self.state["threads"][key] = t
            t.update(card=cid, rev=card.get("rev"), state=card.get("state"), at=now)
            self.state["cards"][cid] = {"thread": key, "at": now}
            self.save()
            return 1
        t = self.state["threads"].get(rec.get("thread"))
        # a card whose message a newer card of its item took over changes nothing on the phone
        if not t or t.get("card") != cid or t.get("msg") is None:
            return 0
        if t.get("rev") == card.get("rev") and t.get("state") == card.get("state"):
            return 0
        text, rows = render(card)
        await self.edit(t["msg"], text, rows)
        t.update(rev=card.get("rev"), state=card.get("state"), at=now)
        rec["at"] = now
        self.save()
        return 1

    # ---------------------------------------------------------------- "tell me when ..."
    async def check_told(self, now: float) -> int:
        """Each watched PR once it is ready to merge, merged or closed: one message, and the watch
        ends. A watch past its `until` ends without one."""
        watches = [w for w in self.tell_me(now) if w.get("pr")]
        if not watches or (self.told_at is not None and now - self.told_at < float(self.rule["tell_me_every_s"])):
            return 0
        self.told_at = now
        res = await self.call("sessions.list", {})
        if not res.get("ok"):
            return 0
        done, ended = 0, []
        for w in watches:
            if float(w.get("until") or 0) <= now:
                logger.info("cockpit-cards: the watch on #%s ended unanswered (%s)", w["pr"], w.get("why"))
                ended.append(w)
                continue
            found = None
            for s in res["result"].get("sessions") or []:
                if w.get("vm") and (s.get("vm"), s.get("id")) != (w.get("vm"), w.get("id")):
                    continue
                for pr in s.get("prs") or []:
                    if pr.get("number") == w["pr"] and (not w.get("repo") or pr.get("repo") in (None, w["repo"])):
                        found = (s, pr)
            if not found:
                continue
            s, pr = found
            verdict = pr_verdict(pr)
            if verdict == "clean?":
                full = await self.call("session.get", {"vm": s["vm"], "id": s["id"]})
                more = [p for p in ((full.get("result") or {}).get("prs") or []) if p.get("number") == w["pr"]]
                verdict = pr_verdict(dict(pr, merge_state=(more[0] if more else {}).get("merge_state")))
            if verdict is None:
                continue
            head = {"ready": "is ready to merge", "merged": "is merged",
                    "closed": "was closed without merging"}[verdict]
            text = (f"<b>#{w['pr']} {head}</b>\n{html.escape(pr.get('title') or s.get('name') or '')}"
                    f" · {html.escape(str(s.get('vm')))}")
            if verdict == "ready":
                text += f"\n\nSay \"merge {w['pr']}\" and I arm auto-merge."
            msg = await self.send(text, [], self.night)
            self.state["threads"][f"pr:{w.get('repo') or ''}#{w['pr']}"] = {
                "msg": msg, "card": None, "state": verdict, "at": now}
            ended.append(w)
            done += 1
        if ended:
            # read again before writing: the ops tool may have added a watch meanwhile
            gone = [(x.get("pr"), x.get("vm"), x.get("id"), x.get("added")) for x in ended]
            left = [x for x in self.tell_me(now) if (x.get("pr"), x.get("vm"), x.get("id"), x.get("added")) not in gone]
            save_json(self.tell_me_path, {"watches": left})
        return done

    # ---------------------------------------------------------------- taps and replies
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
    rule = ctx.get_config("relay")

    def wire(app, adapter):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.error import BadRequest
        from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, MessageHandler, filters

        relay = Relay(chat_id, state_path, rule=rule if isinstance(rule, dict) else None)

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
        logger.info("cockpit-cards: relaying to chat %s every %ss what needs Tristan (send: %s)",
                    relay.chat_id, poll_s, ", ".join(relay.rule["send"]))

    ctx.register_telegram_handler(wire)
