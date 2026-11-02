"""/garmin_to_strava — merge today's Garmin activities and upload them to Strava."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from bot.app import App, Context

from . import garmin, merge, strava_web
from .parse import SelectorError, parse_request

log = logging.getLogger(__name__)

USAGE = """\
Upload
  /garmin_to_strava today | Morning ride | Coffee at km 30
  Which activities: today, yesterday, 2026-10-24, last 2, last ride, rides today
  Then the title, then the description, separated by |
  The bot merges them, uploads to Strava and sends the link.
  Attach photos to the same message (command in the caption) and they're added too.

Accounts (only ever yours)
  /garmin_to_strava accounts                    show connected accounts
  /garmin_to_strava login garmin|strava         log in (again)
  /garmin_to_strava forget garmin|strava|all    delete saved logins

First time: the bot asks for your Garmin login, then your Strava email and the
code Strava emails you (Google sign-in accounts work). Passwords are never stored.
/cancel stops any question.
/garmin_to_strava help shows this message."""

HELP_HINT = "Send /garmin_to_strava help for examples."

SERVICES = {"garmin": garmin, "strava": strava_web}
SERVICE_NAMES = {"garmin": "Garmin", "strava": "Strava"}

# Garmin typeKey -> Strava sport type
SPORT_TYPES = {
    "road_biking": "Ride", "cycling": "Ride", "gravel_cycling": "GravelRide",
    "mountain_biking": "MountainBikeRide", "e_bike_fitness": "EBikeRide",
    "e_mountain_biking": "EMountainBikeRide",
    "running": "Run", "street_running": "Run", "trail_running": "TrailRun",
    "walking": "Walk", "hiking": "Hike",
    "open_water_swimming": "Swim", "lap_swimming": "Swim",
}


def fmt_duration(td: timedelta | None) -> str:
    if not td:
        return "?"
    minutes = int(td.total_seconds() // 60)
    return f"{minutes // 60}h{minutes % 60:02d}"


class GarminToStrava(App):
    command = "garmin_to_strava"
    description = "Upload merged Garmin activities to Strava (send /garmin_to_strava help)"
    usage = USAGE

    def handle(self, ctx: Context) -> None:
        word, _, rest = ctx.text.strip().partition(" ")
        word, rest = word.lower(), rest.strip().lower()
        if word in ("", "help"):
            # A bare command shows help instead of uploading by accident.
            ctx.reply(USAGE)
        elif word == "accounts":
            self.accounts(ctx)
        elif word in ("login", "connect"):
            self.connect(ctx, rest)
        elif word in ("forget", "logout"):
            self.forget(ctx, rest)
        else:
            try:
                self.run(ctx)
            except SelectorError as e:
                ctx.reply(f"❌ {e}. {HELP_HINT}")

    # --- accounts --------------------------------------------------------
    @staticmethod
    def accounts(ctx: Context) -> None:
        parts = []
        for key, module in SERVICES.items():
            info = module.account_info(ctx.user_dir)
            body = "\n".join(f"  {line}" for line in info) if info else \
                "  not connected (you'll be asked to log in when it's needed)"
            parts.append(f"{SERVICE_NAMES[key]}:\n{body}")
        ctx.reply("Your connected accounts (only you can see these):\n\n" + "\n\n".join(parts))

    @staticmethod
    def _which(arg: str, allow_all: bool) -> list[str] | None:
        if arg in SERVICES:
            return [arg]
        if allow_all and arg == "all":
            return list(SERVICES)
        return None

    def connect(self, ctx: Context, arg: str) -> None:
        which = self._which(arg, allow_all=False)
        if not which:
            ctx.reply(f"Usage: /garmin_to_strava login garmin|strava\n{HELP_HINT}")
            return
        key = which[0]
        module = SERVICES[key]
        if module.is_connected(ctx.user_dir):
            answer = ctx.ask(f"{SERVICE_NAMES[key]} is already connected. Log in again "
                             "and replace the saved login? (yes/no)")
            if answer.lower() not in ("yes", "y"):
                ctx.reply("Kept your current login.")
                return
            module.forget(ctx.user_dir)
        module.connect(ctx.user_dir, ctx.ask)
        ctx.reply(f"✅ {SERVICE_NAMES[key]} connected.")

    def forget(self, ctx: Context, arg: str) -> None:
        which = self._which(arg, allow_all=True)
        if not which:
            ctx.reply(f"Usage: /garmin_to_strava forget garmin|strava|all\n{HELP_HINT}")
            return
        saved = [k for k in which if SERVICES[k].account_info(ctx.user_dir)]
        if not saved:
            ctx.reply("Nothing to forget: no saved login.")
            return
        names = " and ".join(SERVICE_NAMES[k] for k in saved)
        answer = ctx.ask(f"Forget your saved {names} login? You'll be asked to log in "
                         "again next time. (yes/no)")
        if answer.lower() not in ("yes", "y"):
            ctx.reply("Nothing changed.")
            return
        for k in saved:
            SERVICES[k].forget(ctx.user_dir)
        ctx.reply(f"🗑 Forgot your {names} login.")

    # --- the main pipeline -------------------------------------------------
    def run(self, ctx: Context) -> None:
        req = parse_request(ctx.text, date.today())
        if not garmin.is_connected(ctx.user_dir):
            ctx.reply("First, let's connect your Garmin account.")
        client = garmin.login(ctx.user_dir, ctx.ask)

        status = ctx.reply(f"🔎 Looking for Garmin {req.selector.describe()}…")
        lines: list[str] = []

        def progress(line: str, replace_last: bool = False) -> None:
            if replace_last and lines:
                lines[-1] = line
            else:
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
        gpx_path = ctx.work_dir / f"{(summary.start or date.today()):%Y-%m-%d}_merged.gpx"
        gpx_path.write_text(merged.to_xml())
        progress(f"🔗 {'Merged' if len(activities) > 1 else 'Track'}: {summary.distance_km:.1f} km, "
                 f"{fmt_duration(summary.elapsed)} elapsed, {summary.points} points")

        if not strava_web.is_connected(ctx.user_dir):
            ctx.reply("Now let's connect your Strava account.")
            strava_web.connect(ctx.user_dir, ctx.ask)
        progress("⬆️ Uploading to Strava…"
                 + (f" (with {len(ctx.photos)} photo(s))" if ctx.photos else ""))
        args = (gpx_path, req.title, req.description,
                SPORT_TYPES.get(activities[0].type_key), ctx.photos)
        try:
            activity_id, duplicate, photo_error = strava_web.upload(ctx.user_dir, *args)
        except strava_web.SessionExpired:
            strava_web.forget(ctx.user_dir)
            strava_web.connect(ctx.user_dir, ctx.ask, reason="Your Strava login expired. ")
            activity_id, duplicate, photo_error = strava_web.upload(ctx.user_dir, *args)

        url = f"https://www.strava.com/activities/{activity_id}"
        progress(f"♻️ Already on Strava, updated it: {url}" if duplicate else f"✅ Uploaded: {url}",
                 True)
        if ctx.photos:
            progress(f"📷 Photos failed ({photo_error}); add them in the Strava app"
                     if photo_error else f"📷 {len(ctx.photos)} photo(s) added")


APP = GarminToStrava()
