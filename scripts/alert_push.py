#!/usr/bin/env python3
"""Operator commands for external alert push (docs/GGONGBAB_ALERTS.md).

    python scripts/alert_push.py --status                       # never prints a token
    python scripts/alert_push.py --store-telegram-token         # activation: prompts, no echo
    python scripts/alert_push.py --find-telegram-chat           # after you messaged the bot once
    python scripts/alert_push.py --use-telegram --chat-id N     # writes .local/alert-push.json
    python scripts/alert_push.py --test                         # one test message
    python scripts/alert_push.py --remove                       # forget token and config

The bot token lives only in Windows Credential Manager (target babdoduk/alert-telegram); the
chat id, which is not a secret, lives in .local/alert-push.json. --store-telegram-token and
--test are activation steps and need the owner's approval first.
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ggongbab import dispatch, notify  # noqa: E402
from ggongbab.alerts import Alert  # noqa: E402
from ggongbab.ops_storage import atomic_json, read_json  # noqa: E402

LOCAL = ROOT / ".local"
CONFIG = LOCAL / "alert-push.json"
BOT_TOKEN_SHAPE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")


def telegram_chats(token: str, opener=urllib.request.urlopen) -> list[tuple[str, str]]:
    """Private chats that have messaged the bot: (chat id, first name). getUpdates only."""
    with opener(f"{notify.TELEGRAM_API}/bot{token}/getUpdates", timeout=notify.TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    chats = {}
    for update in payload.get("result") or []:
        chat = ((update.get("message") or {}).get("chat") or {})
        if chat.get("type") == "private" and chat.get("id") is not None:
            chats[str(chat["id"])] = str(chat.get("first_name") or "")
    return sorted(chats.items())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    for flag in ("--status", "--store-telegram-token", "--find-telegram-chat", "--use-telegram", "--test", "--remove"):
        mode.add_argument(flag, action="store_true")
    parser.add_argument("--chat-id", help="Telegram chat id for --use-telegram")
    args = parser.parse_args(argv)
    config = read_json(CONFIG, {})
    if args.status:
        state = read_json(LOCAL / "alert-push-state.json", {})
        token = dispatch.read_windows_credential(notify.TOKEN_TARGET)
        print(f"provider         : {config.get('provider') or '-'}")
        print(f"telegram token   : {'stored' if token else 'not stored'} ({notify.TOKEN_TARGET})")
        print(f"chat configured  : {'yes' if config.get('chat_id') else 'no'}")
        print(f"last push result : {state.get('last_result') or '-'}")
        return 0
    if args.store_telegram_token:
        token = getpass.getpass("Telegram bot token from @BotFather: ").strip()
        if not BOT_TOKEN_SHAPE.match(token):
            print("That does not look like a Telegram bot token; nothing was stored.")
            return 1
        ok = dispatch.write_windows_credential(token, notify.TOKEN_TARGET, comment="Babdoduk ops alert bot",
                                               user="telegram-bot")
        del token
        print("stored in Windows Credential Manager" if ok else "could not store the token")
        return 0 if ok else 1
    if args.find_telegram_chat:
        token = dispatch.read_windows_credential(notify.TOKEN_TARGET)
        if not token:
            print("no token stored; run --store-telegram-token first")
            return 1
        try:
            chats = telegram_chats(token)
        except Exception as exc:  # noqa: BLE001 - never echo the URL, which contains the token
            print(f"could not read updates ({exc.__class__.__name__})")
            return 1
        if not chats:
            print("no private chat yet: open the bot in Telegram, press Start, send any message, then retry")
            return 1
        for chat_id, name in chats:
            print(f"chat id {chat_id}  ({name})")
        return 0
    if args.use_telegram:
        if not args.chat_id or not re.fullmatch(r"-?\d{3,20}", args.chat_id):
            print("--chat-id must be the numeric id printed by --find-telegram-chat")
            return 1
        atomic_json(CONFIG, {"provider": "telegram", "chat_id": args.chat_id})
        print("local push configured: Telegram")
        return 0
    if args.test:
        notifier = notify.local_notifier(LOCAL)
        if notifier is None:
            print(notify.NOT_CONFIGURED)
            return 1
        result = notifier.send(notify.CONNECTION_TEST_MESSAGE)
        print(result)
        return 0 if result == notify.SENT else 1
    removed = dispatch.delete_windows_credential(notify.TOKEN_TARGET)
    if CONFIG.exists():
        CONFIG.unlink()
    print("removed" if removed else "no stored token; config cleared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
