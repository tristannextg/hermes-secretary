#!/usr/bin/env python3
"""Hermes's Telegram side: long-polls @Hermes_secretarybot and answers each
message from Tristan's chat with a Claude Code session.

One conversation continues (claude --resume) until it has been idle for
CHAT_IDLE_S, so a "yes" answers the question Hermes just asked; after that a
fresh session starts, and lessons carry over through memory/lessons.md.
Messages from any other chat are dropped unread. Runs as the long-lived
hermes-claude-telegram.service; only one process may poll a bot, so the old
hermes-gateway.service must stay stopped.
"""

import json
import os
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hermes_mcp  # noqa: E402
import hermes_run  # noqa: E402

STATE = hermes_run.STATE
OFFSET = os.path.join(STATE, "tg_offset")
SESSION = os.path.join(STATE, "chat_session.json")
CHAT_IDLE_S = 8 * 3600
POLL_S = 50


def load(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def save(path: str, value) -> None:
    os.makedirs(STATE, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(value, f)
    os.replace(tmp, path)


def updates(token: str, offset: int) -> list[dict]:
    url = f"https://api.telegram.org/bot{token}/getUpdates?timeout={POLL_S}&offset={offset}"
    res = json.loads(hermes_mcp.http("GET", url, timeout=POLL_S + 15))
    if not res.get("ok"):
        raise RuntimeError(f"getUpdates refused: {res.get('description')}")
    return res["result"]


def answer(text: str, sent_at: int) -> None:
    hermes_mcp.log_chat("tristan", text)
    prev = load(SESSION, {})
    resume = prev.get("id") if time.time() - prev.get("used", 0) < CHAT_IDLE_S else None
    when = time.strftime("%a %Y-%m-%d %H:%M", time.localtime(sent_at))
    prompt = (
        f"Telegram message from Tristan ({when}):\n\n{text}\n\n"
        "Your final answer is sent to him on Telegram as it is - do not also "
        "call telegram_send for it."
    )
    code, res = hermes_run.run_job("chat", prompt, resume=resume)
    if code and resume and "No conversation found" in str(res.get("result")):
        code, res = hermes_run.run_job("chat", prompt)
    if code == hermes_run.EXIT_EXHAUSTED:
        reply = f"I can't answer right now: {res['result']}."
    elif code:
        reply = f"⚠️ That failed: {str(res.get('result'))[:500]}"
    else:
        reply = str(res.get("result") or "").strip() or "(I had nothing to say - that is a bug, tell me.)"
        save(SESSION, {"id": res.get("session_id"), "used": time.time()})
    hermes_mcp.send_telegram(reply)


def main() -> int:
    token = hermes_mcp.secret("TELEGRAM_BOT_TOKEN")
    chat = str(hermes_mcp.CHAT_ID)
    offset = int(load(OFFSET, 0))
    while True:
        try:
            batch = updates(token, offset)
        except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as e:
            print(f"poll failed: {e}", file=sys.stderr, flush=True)
            time.sleep(15)
            continue
        for u in batch:
            offset = u["update_id"] + 1
            save(OFFSET, offset)
            msg = u.get("message") or u.get("edited_message")
            if not msg or str(msg.get("chat", {}).get("id")) != chat:
                continue
            text = msg.get("text") or msg.get("caption")
            if not text:
                hermes_mcp.send_telegram("I can only read text for now - please type it.")
                continue
            if text.strip() in ("/start", "/help"):
                hermes_mcp.send_telegram("Hermes here. Write to me; I see your vault and the repos.")
                continue
            try:
                answer(text, msg.get("date", int(time.time())))
            except Exception as e:  # keep polling; say what broke
                print(f"answer failed: {e}", file=sys.stderr, flush=True)
                hermes_run.alert("chat-crash", f"I crashed answering you: {type(e).__name__}: {e}", every_s=0)


if __name__ == "__main__":
    sys.exit(main())
