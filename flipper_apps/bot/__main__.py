"""Entry point: `python -m bot`."""
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

import apps

from .api import BotAPI
from .registry import Registry
from .runner import Runner


def setup_logging() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs every request URL at INFO, and Telegram URLs contain the bot token.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    load_dotenv()
    setup_logging()
    token = os.getenv("TELEGRAM_TOKEN")
    allowed = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").replace(",", " ").split()}
    if not token or not allowed:
        sys.exit("Set TELEGRAM_TOKEN and ALLOWED_USER_IDS (see .env.example)")
    registry = Registry()
    registry.discover(apps)
    Runner(BotAPI(token), registry, allowed, Path(os.getenv("DATA_DIR", "data"))).run_forever()


if __name__ == "__main__":
    main()
