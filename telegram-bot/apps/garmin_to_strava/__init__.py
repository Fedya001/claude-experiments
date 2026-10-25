"""/garmin_to_strava — merge today's Garmin activities and upload them to Strava with photos."""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from bot.app import App, Context

from . import garmin, merge, strava_web
from .parse import parse_request
from .strava_api import SPORT_TYPES, Strava

log = logging.getLogger(__name__)

USAGE = """\
/garmin_to_strava [dry] <selector> | <title> | <description>
Attach photos to the same message (put the command in the caption).

Selector: today, yesterday, 2026-10-24, last 2, rides today, runs yesterday…
Without '|': first line = selector (or 'today' if it isn't one), next line = title, rest = description.
'dry' sends the merged GPX back instead of uploading.

Example: /garmin_to_strava today | Morning ride to the lake | Coffee stop at km 30"""


def fmt_duration(td: timedelta | None) -> str:
    if not td:
        return "?"
    minutes = int(td.total_seconds() // 60)
    return f"{minutes // 60}h{minutes % 60:02d}"


class GarminToStrava(App):
    command = "garmin_to_strava"
    description = "Merge Garmin activities and upload to Strava with photos"
    usage = USAGE

    def handle(self, ctx: Context) -> None:
        req = parse_request(ctx.text, date.today())
        status = ctx.reply(f"🔎 Looking for Garmin {req.selector.describe()}…")
        lines: list[str] = []

        def progress(line: str, replace_last: bool = False) -> None:
            if replace_last and lines:
                lines[-1] = line
            else:
                lines.append(line)
            ctx.edit(status, "\n".join(lines))

        client = garmin.login(ctx.data_dir)
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

        if req.dry_run:
            ctx.send_file(gpx_path, caption="Dry run — not uploaded")
            return

        strava = Strava(ctx.data_dir)
        ids = ",".join(str(a.id) for a in activities)
        external_id = f"garmin-{hashlib.sha1(ids.encode()).hexdigest()[:16]}.gpx"
        progress("⬆️ Uploading to Strava…")
        activity_id, duplicate = strava.upload_gpx(gpx_path, req.title, req.description, external_id)
        url = f"https://www.strava.com/activities/{activity_id}"
        if duplicate:
            progress(f"⚠️ Strava says this is a duplicate of {url} — using that activity", True)
        else:
            progress(f"✅ Uploaded: {url}", True)
            if sport := SPORT_TYPES.get(activities[0].type_key):
                strava.update_activity(activity_id, sport_type=sport)

        if summary.start and summary.end:
            others = self._overlapping(strava, activity_id, summary.start, summary.end)
            if others:
                progress("⚠️ Overlapping Strava activities (Garmin auto-sync?) — delete them manually:\n"
                         + "\n".join(f"  https://www.strava.com/activities/{i}" for i in others))

        if ctx.photos:
            progress(f"📷 Adding {len(ctx.photos)} photo(s)…")
            try:
                strava_web.add_photos(ctx.data_dir, activity_id, ctx.photos)
                progress(f"📷 {len(ctx.photos)} photo(s) added", True)
            except Exception as e:
                log.exception("adding photos failed")
                progress(f"📷 Photos failed ({e}); add them in the Strava app", True)

    @staticmethod
    def _overlapping(strava: Strava, activity_id: int, start, end) -> list[int]:
        try:
            candidates = strava.activities_between(start - timedelta(hours=12), end)
        except Exception:
            log.exception("listing Strava activities failed")
            return []
        result = []
        for a in candidates:
            if a["id"] == activity_id:
                continue
            a_start = datetime.fromisoformat(a["start_date"].replace("Z", "+00:00"))
            a_end = a_start + timedelta(seconds=a.get("elapsed_time", 0))
            if a_start < end and a_end > start:
                result.append(a["id"])
        return result


APP = GarminToStrava()
