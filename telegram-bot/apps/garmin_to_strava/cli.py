"""One-time setup and local testing without Telegram.

Run from the telegram-bot folder:
  python -m apps.garmin_to_strava.cli auth-garmin
  python -m apps.garmin_to_strava.cli auth-strava
  python -m apps.garmin_to_strava.cli auth-web
  python -m apps.garmin_to_strava.cli run "dry today | Test ride" photo1.jpg
"""
from __future__ import annotations

import argparse
import getpass
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from bot.app import Context

from . import APP, garmin, strava_web
from .strava_api import Strava


class ConsoleContext(Context):
    def reply(self, text: str) -> int:
        print(text)
        return 0

    def edit(self, message_id: int, text: str) -> None:
        print("—" * 40 + "\n" + text)

    def send_file(self, path: Path, caption: str | None = None) -> None:
        dest = Path.cwd() / path.name
        dest.write_bytes(path.read_bytes())
        print(f"{caption or 'File'}: saved {dest}")


def main() -> None:
    load_dotenv()
    data_dir = Path(os.getenv("DATA_DIR", "data")) / APP.command
    data_dir.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser(prog="garmin_to_strava")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth-garmin", help="log in to Garmin Connect and cache tokens")
    sub.add_parser("auth-strava", help="authorize the Strava API app")
    sub.add_parser("auth-web", help="log in to strava.com in a browser (for photos)")
    run = sub.add_parser("run", help="run the pipeline in the terminal")
    run.add_argument("text")
    run.add_argument("photos", nargs="*", type=Path)
    args = parser.parse_args()

    if args.cmd == "auth-garmin":
        email = os.getenv("GARMIN_EMAIL") or input("Garmin email: ")
        password = os.getenv("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")
        client = garmin.login(data_dir, email, password, prompt_mfa=lambda: input("MFA code: "))
        print(f"Logged in as {client.get_full_name()}; tokens in {garmin.token_dir(data_dir)}")
    elif args.cmd == "auth-strava":
        strava = Strava(data_dir)
        print("Open this URL, approve, then paste the URL you were redirected to\n"
              "(the page itself will fail to load — that's expected):\n")
        print(strava.authorize_url() + "\n")
        strava.exchange_code(input("Redirected URL: "))
        print(f"Saved {strava.token_file}")
    elif args.cmd == "auth-web":
        strava_web.save_session(data_dir)
        print(f"Saved {strava_web.state_file(data_dir)}")
    elif args.cmd == "run":
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ConsoleContext(api=None, chat_id=0, user_id=0, text=args.text,
                                 photos=[p.resolve() for p in args.photos],
                                 data_dir=data_dir, work_dir=Path(tmp))
            APP.handle(ctx)


if __name__ == "__main__":
    main()
