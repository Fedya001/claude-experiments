"""/garmin_to_strava — merge today's Garmin activities and upload them to Strava."""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta

from bot.app import App, Context

from . import garmin, merge, strava_api
from .parse import parse_request

log = logging.getLogger(__name__)

USAGE = """\
/garmin_to_strava <selector> | <title> | <description>

Selector: today, yesterday, 2026-10-24, last 2, rides today, runs yesterday…
Without '|': first line = selector (or 'today' if it isn't one), next line = title, rest = description.

Example: /garmin_to_strava today | Morning ride to the lake | Coffee stop at km 30

The first time, the bot asks you to log in to Garmin (in the chat) and to connect
Strava (with Strava's official link; Google sign-in works). Passwords are never stored,
only the resulting tokens, separately for each Telegram user.
Strava doesn't let apps add photos: add them in the Strava app afterwards.
  /garmin_to_strava accounts                       show your connected accounts
  /garmin_to_strava connect garmin|strava          log in (again) now
  /garmin_to_strava forget garmin|strava|all       delete your saved logins"""

SERVICES = {"garmin": garmin, "strava": strava_api}
SERVICE_NAMES = {"garmin": "Garmin", "strava": "Strava"}


def fmt_duration(td: timedelta | None) -> str:
    if not td:
        return "?"
    minutes = int(td.total_seconds() // 60)
    return f"{minutes // 60}h{minutes % 60:02d}"


class GarminToStrava(App):
    command = "garmin_to_strava"
    description = "Merge Garmin activities and upload them to Strava"
    usage = USAGE

    def handle(self, ctx: Context) -> None:
        word, _, rest = ctx.text.strip().partition(" ")
        word, rest = word.lower(), rest.strip().lower()
        if word == "accounts":
            self.accounts(ctx)
        elif word == "connect":
            self.connect(ctx, rest)
        elif word == "forget":
            self.forget(ctx, rest)
        else:
            self.run(ctx)

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
            ctx.reply("Usage: /garmin_to_strava connect garmin|strava")
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
            ctx.reply("Usage: /garmin_to_strava forget garmin|strava|all")
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

        if not strava_api.is_connected(ctx.user_dir):
            ctx.reply("Now let's connect your Strava account.")
            strava_api.connect(ctx.user_dir, ctx.ask)
        progress("⬆️ Uploading to Strava…")
        ids = ",".join(str(a.id) for a in activities)
        external_id = f"garmin-{hashlib.sha1(ids.encode()).hexdigest()[:16]}.gpx"
        strava = strava_api.Strava(ctx.user_dir)
        try:
            activity_id, duplicate = strava.upload_gpx(gpx_path, req.title, req.description,
                                                       external_id)
        except strava_api.NotConnected:
            strava_api.forget(ctx.user_dir)
            strava_api.connect(ctx.user_dir, ctx.ask,
                               reason="Strava no longer accepts the bot's access. ")
            activity_id, duplicate = strava.upload_gpx(gpx_path, req.title, req.description,
                                                       external_id)

        url = f"https://www.strava.com/activities/{activity_id}"
        fields = {"sport_type": strava_api.SPORT_TYPES.get(activities[0].type_key)}
        if duplicate:
            # The upload's name/description were dropped; apply them to the existing activity.
            fields.update(name=req.title, description=req.description)
            progress(f"♻️ Already on Strava, updated it: {url}", True)
        else:
            progress(f"✅ Uploaded: {url}", True)
        if fields := {k: v for k, v in fields.items() if v}:
            strava.update_activity(activity_id, **fields)

        if summary.start and summary.end:
            if others := self._overlapping(strava, activity_id, summary.start, summary.end):
                progress("⚠️ Overlapping Strava activities (Garmin auto-sync?), delete them "
                         "in Strava:\n" + "\n".join(f"  https://www.strava.com/activities/{i}"
                                                     for i in others))
        if ctx.photos:
            progress(f"📷 Strava doesn't let apps add photos. Add your {len(ctx.photos)} "
                     f"photo(s) in the Strava app: {url}")

    @staticmethod
    def _overlapping(strava: strava_api.Strava, activity_id: int, start, end) -> list[int]:
        # Best effort: a failure here must not fail a run whose upload succeeded.
        try:
            result = []
            for a in strava.activities_between(start - timedelta(hours=12), end):
                if a["id"] == activity_id:
                    continue
                a_start = datetime.fromisoformat(a["start_date"].replace("Z", "+00:00"))
                a_end = a_start + timedelta(seconds=a.get("elapsed_time", 0))
                if a_start < end and a_end > start:
                    result.append(a["id"])
            return result
        except Exception:
            log.exception("checking overlapping Strava activities failed")
            return []


APP = GarminToStrava()
