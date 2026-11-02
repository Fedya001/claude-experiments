"""Run /garmin_merge in a terminal, without Telegram (for testing).

Run from the flipper_apps folder:
  python -m apps.garmin_merge.cli "today | Lake loop"
  python -m apps.garmin_merge.cli accounts
  python -m apps.garmin_merge.cli --user 123456789 forget

Logins are asked in the terminal and saved for the given Telegram user id
(default: the first of ALLOWED_USER_IDS), so the bot reuses them.
"""
from __future__ import annotations

import argparse
import getpass
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from bot.app import Context

from . import APP


class ConsoleContext(Context):
    def reply(self, text: str) -> int:
        print(text)
        return 0

    def edit(self, message_id: int, text: str) -> None:
        print("—" * 40 + "\n" + text)

    def ask(self, prompt: str, *, secret: bool = False, timeout: float = 300) -> str:
        return (getpass.getpass if secret else input)(prompt + " ").strip()

    def send_file(self, path: Path, caption: str | None = None) -> None:
        # The user's data folder is mounted from the host in Docker, unlike the working dir.
        dest = self.user_dir / path.name
        dest.write_bytes(path.read_bytes())
        print(f"Saved {dest}")


def main() -> None:
    load_dotenv()
    allowed = os.getenv("ALLOWED_USER_IDS", "").replace(",", " ").split()
    parser = argparse.ArgumentParser(prog="garmin_merge", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", type=int, default=int(allowed[0]) if allowed else None,
                        help="Telegram user id whose logins to use (default: first of ALLOWED_USER_IDS)")
    parser.add_argument("text", help="what you'd send after /garmin_merge")
    args = parser.parse_args()
    if args.user is None:
        parser.error("set ALLOWED_USER_IDS in .env or pass --user")

    data_dir = Path(os.getenv("DATA_DIR", "data")) / APP.command
    with tempfile.TemporaryDirectory() as tmp:
        ctx = ConsoleContext(api=None, chat_id=0, user_id=args.user, text=args.text,
                             data_dir=data_dir, work_dir=Path(tmp))
        APP.handle(ctx)


if __name__ == "__main__":
    main()
