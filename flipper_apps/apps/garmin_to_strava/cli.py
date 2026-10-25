"""Run /garmin_to_strava in a terminal, without Telegram (for testing).

Run from the flipper_apps folder:
  python -m apps.garmin_to_strava.cli "dry today | Test ride"
  python -m apps.garmin_to_strava.cli "today | Lake loop" photo1.jpg
  python -m apps.garmin_to_strava.cli accounts
  python -m apps.garmin_to_strava.cli --user 123456789 "forget all"

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
        # data_dir is mounted from the host in Docker, unlike the working directory
        dest = self.user_dir / path.name
        dest.write_bytes(path.read_bytes())
        print(f"{caption or 'File'}: saved {dest}")


def main() -> None:
    load_dotenv()
    allowed = os.getenv("ALLOWED_USER_IDS", "").replace(",", " ").split()
    parser = argparse.ArgumentParser(prog="garmin_to_strava", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", type=int, default=int(allowed[0]) if allowed else None,
                        help="Telegram user id whose logins to use (default: first of ALLOWED_USER_IDS)")
    parser.add_argument("text", help="what you'd send after /garmin_to_strava")
    parser.add_argument("photos", nargs="*", type=Path)
    args = parser.parse_args()
    if args.user is None:
        parser.error("set ALLOWED_USER_IDS in .env or pass --user")

    data_dir = Path(os.getenv("DATA_DIR", "data")) / APP.command
    with tempfile.TemporaryDirectory() as tmp:
        ctx = ConsoleContext(api=None, chat_id=0, user_id=args.user, text=args.text,
                             photos=[p.resolve() for p in args.photos],
                             data_dir=data_dir, work_dir=Path(tmp))
        APP.handle(ctx)


if __name__ == "__main__":
    main()
