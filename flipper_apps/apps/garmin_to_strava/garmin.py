"""Fetches activities as GPX from Garmin Connect via the unofficial `garminconnect` library."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from garminconnect import Garmin

from .parse import Selector

LOOKBACK_DAYS = 30  # how far back 'last N' without a date searches


@dataclass
class Activity:
    id: int
    name: str
    type_key: str
    start_local: str
    distance_km: float
    gpx: str


def token_dir(data_dir: Path) -> Path:
    return data_dir / "garmin_tokens"


def login(data_dir: Path, email: str | None = None, password: str | None = None,
          prompt_mfa: Callable[[], str] | None = None) -> Garmin:
    """Logs in with cached tokens; falls back to credentials (env GARMIN_EMAIL/PASSWORD)."""
    tokens = token_dir(data_dir)
    tokens.mkdir(parents=True, exist_ok=True)
    client = Garmin(email or os.getenv("GARMIN_EMAIL"), password or os.getenv("GARMIN_PASSWORD"),
                    prompt_mfa=prompt_mfa)
    client.login(str(tokens))  # saves refreshed tokens back to the directory
    return client


def has_gps(meta: dict) -> bool:
    return bool(meta.get("hasPolyline") or meta.get("startLatitude") is not None)


def find_activities(client: Garmin, selector: Selector) -> list[dict]:
    """Activity metadata matching the selector, oldest first."""
    if selector.date_from:
        start, end = selector.date_from, selector.date_to or selector.date_from
    else:
        end = date.today()
        start = end - timedelta(days=LOOKBACK_DAYS)
    found = client.get_activities_by_date(start.isoformat(), end.isoformat())
    found = [a for a in found
             if selector.matches_type(a.get("activityType", {}).get("typeKey", "")) and has_gps(a)]
    found.sort(key=lambda a: a.get("startTimeGMT") or a.get("startTimeLocal") or "")
    if selector.limit:
        found = found[-selector.limit:]
    return found


def download(client: Garmin, metas: list[dict]) -> list[Activity]:
    result = []
    for a in metas:
        data = client.download_activity(a["activityId"], dl_fmt=Garmin.ActivityDownloadFormat.GPX)
        result.append(Activity(
            id=a["activityId"],
            name=a.get("activityName") or "",
            type_key=a.get("activityType", {}).get("typeKey", ""),
            start_local=a.get("startTimeLocal", ""),
            distance_km=(a.get("distance") or 0) / 1000,
            gpx=data.decode("utf-8") if isinstance(data, bytes) else data,
        ))
    return result
