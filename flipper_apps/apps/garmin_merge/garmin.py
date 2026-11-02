"""Fetches activities as GPX from Garmin Connect via the unofficial `garminconnect` library."""
from __future__ import annotations

import base64
import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from garminconnect import Garmin, GarminConnectAuthenticationError

from .parse import Selector
from .util import Ask, mask, read_json, write_json

LOOKBACK_DAYS = 30  # how far back 'last N' without a date searches


MAX_ATTEMPTS = 3


@dataclass
class Activity:
    id: int
    name: str
    type_key: str
    start_local: str
    distance_km: float
    gpx: str


def token_dir(user_dir: Path) -> Path:
    return user_dir / "garmin_tokens"


def _token_file(user_dir: Path) -> Path:
    return token_dir(user_dir) / "garmin_tokens.json"


def _account_file(user_dir: Path) -> Path:
    return user_dir / "garmin_account.json"


def is_connected(user_dir: Path) -> bool:
    return _token_file(user_dir).exists()


def connect(user_dir: Path, ask: Ask, reason: str = "") -> Garmin:
    """Asks for email and password (and an MFA code if needed), logs in, saves the token.

    The password is only used for this login and never stored.
    """
    note = reason
    for _ in range(MAX_ATTEMPTS):
        email = ask(f"{note}🔑 Connect Garmin: what's your Garmin Connect email?")
        password = ask("Garmin password?", secret=True)
        client = Garmin(email, password,
                        prompt_mfa=lambda: ask("Garmin sent you a verification code. "
                                               "What is it?", secret=True))
        try:
            client.login(str(token_dir(user_dir)))
        except GarminConnectAuthenticationError:
            note = "❌ Garmin rejected that email or password. "
            continue
        write_json(_account_file(user_dir), {
            "email": email,
            "name": client.get_full_name(),
            "connected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        return client
    raise RuntimeError(f"Garmin login failed {MAX_ATTEMPTS} times")


def login(user_dir: Path, ask: Ask) -> Garmin:
    """Uses the saved token, or asks the user to log in if there is none or it stopped working."""
    if is_connected(user_dir):
        client = Garmin()
        try:
            client.login(str(token_dir(user_dir)))  # refreshes and re-saves the token
            return client
        except GarminConnectAuthenticationError:
            forget(user_dir)
            return connect(user_dir, ask, reason="Your Garmin login expired. ")
    return connect(user_dir, ask)


def forget(user_dir: Path) -> bool:
    existed = is_connected(user_dir) or _account_file(user_dir).exists()
    shutil.rmtree(token_dir(user_dir), ignore_errors=True)
    _account_file(user_dir).unlink(missing_ok=True)
    return existed


def _jwt_expiry(token: str) -> datetime | None:
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return datetime.fromtimestamp(float(claims["exp"]), timezone.utc)
    except Exception:
        return None


def account_info(user_dir: Path) -> list[str] | None:
    """Human-readable, masked description of the saved Garmin login, or None."""
    if not is_connected(user_dir):
        return None
    account = read_json(_account_file(user_dir)) or {}
    tokens = read_json(_token_file(user_dir)) or {}
    lines = [f"Account: {account.get('name') or '?'} ({account.get('email') or '?'})",
             f"Connected: {account.get('connected_at', '?')}"]
    if token := tokens.get("di_token"):
        expiry = _jwt_expiry(token)
        lines.append(f"Access token: {mask(token)}"
                     + (f", expires {expiry:%Y-%m-%d %H:%M} UTC (renewed automatically)"
                        if expiry else ""))
    if refresh := tokens.get("di_refresh_token"):
        lines.append(f"Refresh token: {mask(refresh)}")
    return lines


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
