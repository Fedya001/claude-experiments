"""/garmin_merge — merge Garmin activities into one GPX file and send it back."""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from bot.app import App, Context

from . import garmin, merge
from .parse import SelectorError, parse_request

log = logging.getLogger(__name__)

USAGE = """\
Merge
  /garmin_merge today
  /garmin_merge today | Morning ride
  Which activities: today, yesterday, 2026-10-24, last 2, last ride, rides today
  The optional title after | names the merged track and the file.
  The bot merges them in time order and sends you the GPX file.

Garmin login (only ever yours)
  /garmin_merge accounts    show your connected Garmin account
  /garmin_merge login       log in (again)
  /garmin_merge forget      delete your saved login

First time: the bot asks for your Garmin login in the chat. Your password is
never stored. /cancel stops any question.
/garmin_merge help shows this message."""

HELP_HINT = "Send /garmin_merge help for examples."


def fmt_duration(td: timedelta | None) -> str:
    if not td:
        return "?"
    minutes = int(td.total_seconds() // 60)
    return f"{minutes // 60}h{minutes % 60:02d}"


def file_name(day: date, title: str | None) -> str:
    slug = re.sub(r"[^\w-]+", "_", title or "").strip("_")[:60]
    return f"{day:%Y-%m-%d}_{slug or 'merged'}.gpx"


class GarminMerge(App):
    command = "garmin_merge"
    description = "Merge Garmin activities into one GPX file (send /garmin_merge help)"
    usage = USAGE

    def handle(self, ctx: Context) -> None:
        word, _, rest = ctx.text.strip().partition(" ")
        word, rest = word.lower(), rest.strip().lower()
        if word in ("", "help"):
            # A bare command shows help instead of merging by accident.
            ctx.reply(USAGE)
        elif word == "accounts":
            self.accounts(ctx)
        elif word in ("login", "connect"):
            self.login(ctx, rest)
        elif word in ("forget", "logout"):
            self.forget(ctx, rest)
        else:
            try:
                self.run(ctx)
            except SelectorError as e:
                ctx.reply(f"❌ {e}. {HELP_HINT}")

    # --- Garmin login ------------------------------------------------------
    @staticmethod
    def _check_arg(ctx: Context, arg: str, usage: str) -> bool:
        if arg in ("", "garmin", "all"):
            return True
        ctx.reply(f"Usage: {usage}\n{HELP_HINT}")
        return False

    @staticmethod
    def accounts(ctx: Context) -> None:
        info = garmin.account_info(ctx.user_dir)
        body = "\n".join(f"  {line}" for line in info) if info else \
            "  not connected (you'll be asked to log in when it's needed)"
        ctx.reply(f"Your Garmin account (only you can see this):\n{body}")

    def login(self, ctx: Context, arg: str) -> None:
        if not self._check_arg(ctx, arg, "/garmin_merge login"):
            return
        if garmin.is_connected(ctx.user_dir):
            answer = ctx.ask("Garmin is already connected. Log in again and replace the "
                             "saved login? (yes/no)")
            if answer.lower() not in ("yes", "y"):
                ctx.reply("Kept your current login.")
                return
            garmin.forget(ctx.user_dir)
        garmin.connect(ctx.user_dir, ctx.ask)
        ctx.reply("✅ Garmin connected.")

    def forget(self, ctx: Context, arg: str) -> None:
        if not self._check_arg(ctx, arg, "/garmin_merge forget"):
            return
        if not garmin.account_info(ctx.user_dir):
            ctx.reply("Nothing to forget: no saved login.")
            return
        answer = ctx.ask("Forget your saved Garmin login? You'll be asked to log in again "
                         "next time. (yes/no)")
        if answer.lower() not in ("yes", "y"):
            ctx.reply("Nothing changed.")
            return
        garmin.forget(ctx.user_dir)
        ctx.reply("🗑 Forgot your Garmin login.")

    # --- the main pipeline -------------------------------------------------
    def run(self, ctx: Context) -> None:
        req = parse_request(ctx.text, date.today())
        if not garmin.is_connected(ctx.user_dir):
            ctx.reply("First, let's connect your Garmin account.")
        client = garmin.login(ctx.user_dir, ctx.ask)

        status = ctx.reply(f"🔎 Looking for Garmin {req.selector.describe()}…")
        lines: list[str] = []

        def progress(line: str) -> None:
            lines.append(line)
            ctx.edit(status, "\n".join(lines))

        metas = garmin.find_activities(client, req.selector)
        if not metas:
            progress(f"No Garmin {req.selector.describe()} with GPS found.")
            return
        activities = garmin.download(client, metas)
        progress(f"📥 {len(activities)} Garmin activit{'y' if len(activities) == 1 else 'ies'}: "
                 + ", ".join(f"{a.name or a.type_key} ({a.distance_km:.1f} km)" for a in activities))

        merged = merge.merge([a.gpx for a in activities], name=req.title)
        summary = merge.summarize(merged)
        gpx_path = ctx.work_dir / file_name(summary.start or date.today(), req.title)
        gpx_path.write_text(merged.to_xml())
        progress(f"🔗 {'Merged' if len(activities) > 1 else 'Track'}: {summary.distance_km:.1f} km, "
                 f"{fmt_duration(summary.elapsed)} elapsed, {summary.points} points")
        ctx.send_file(gpx_path, caption=req.title)


APP = GarminMerge()
