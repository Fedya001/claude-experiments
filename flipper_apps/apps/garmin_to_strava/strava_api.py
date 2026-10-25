"""Official Strava API, per Telegram user: authorization link, GPX upload, activity details.

The user connects by tapping Strava's authorization link and approving in Strava,
however they sign in there (Google, Apple, password). No password reaches the bot.
The public API can't add photos to an activity; the user adds those in the Strava app.
"""
from __future__ import annotations

import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .util import Ask, mask, read_json, write_json

API = "https://www.strava.com/api/v3"
OAUTH = "https://www.strava.com/oauth"
REDIRECT_URI = "http://localhost/exchange_token"
SCOPE = "activity:write,activity:read_all"
MAX_ATTEMPTS = 3

# Garmin typeKey -> Strava sport_type
SPORT_TYPES = {
    "road_biking": "Ride", "cycling": "Ride", "gravel_cycling": "GravelRide",
    "mountain_biking": "MountainBikeRide", "e_bike_fitness": "EBikeRide",
    "e_mountain_biking": "EMountainBikeRide",
    "running": "Run", "street_running": "Run", "trail_running": "TrailRun",
    "walking": "Walk", "hiking": "Hike",
    "open_water_swimming": "Swim", "lap_swimming": "Swim",
}


class StravaError(RuntimeError):
    pass


class NotConnected(StravaError):
    """No saved authorization, or Strava no longer accepts it (e.g. access revoked)."""


def new_http() -> httpx.Client:
    return httpx.Client(timeout=60)


def _credentials() -> tuple[str, str]:
    client_id, secret = os.getenv("STRAVA_CLIENT_ID"), os.getenv("STRAVA_CLIENT_SECRET")
    if not client_id or not secret:
        raise StravaError("the bot's Strava API application isn't configured: set "
                          "STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in .env "
                          "(see apps/garmin_to_strava/README.md)")
    return client_id, secret


def _token_file(user_dir: Path) -> Path:
    return user_dir / "strava_tokens.json"


def is_connected(user_dir: Path) -> bool:
    return _token_file(user_dir).exists()


def _token_request(http: httpx.Client, **params) -> httpx.Response:
    client_id, secret = _credentials()
    return http.post(f"{OAUTH}/token",
                     data={"client_id": client_id, "client_secret": secret, **params})


def authorize_url(state: str) -> str:
    client_id, _ = _credentials()
    return f"{OAUTH}/authorize?" + urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT_URI,
        "approval_prompt": "auto", "scope": SCOPE, "state": state})


def connect(user_dir: Path, ask: Ask, reason: str = "") -> None:
    """Sends the authorization link, takes the redirected address back and saves the tokens."""
    state = secrets.token_urlsafe(12)
    note = reason
    with new_http() as http:
        for _ in range(MAX_ATTEMPTS):
            pasted = ask(
                f"{note}🔑 Connect Strava: open this link, sign in to Strava as usual "
                f"(Google works) and tap Authorize:\n{authorize_url(state)}\n\n"
                "You'll land on a page that doesn't load (localhost). That's expected: "
                "copy that page's address and paste it here.")
            query = parse_qs(urlparse(pasted.strip()).query)
            if query.get("error"):
                note = "You didn't authorize the bot. "
                continue
            if query.get("state") != [state] or not query.get("code"):
                note = "❌ That doesn't look like the right address. "
                continue
            if "activity:write" not in query.get("scope", [""])[0]:
                note = "❌ Please keep the permission to upload activities ticked. "
                continue
            resp = _token_request(http, grant_type="authorization_code", code=query["code"][0])
            if resp.status_code != 200:
                note = "❌ Strava didn't accept that authorization, please try again. "
                continue
            tokens = resp.json()
            athlete = tokens.get("athlete") or {}
            _save(user_dir, tokens, {
                "athlete": " ".join(filter(None, (athlete.get("firstname"),
                                                  athlete.get("lastname")))) or None,
                "scope": query["scope"][0],
                "connected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            return
    raise StravaError(f"Strava authorization failed {MAX_ATTEMPTS} times")


def _save(user_dir: Path, tokens: dict, extra: dict) -> None:
    write_json(_token_file(user_dir), {
        **extra, **{k: tokens[k] for k in ("access_token", "refresh_token", "expires_at")}})


def forget(user_dir: Path) -> bool:
    """Revokes the bot's access on Strava's side (best effort) and deletes the tokens."""
    if not is_connected(user_dir):
        return False
    try:
        with new_http() as http:
            Strava(user_dir, http).deauthorize()
    except Exception:
        pass  # already revoked, or offline: deleting locally is what matters
    _token_file(user_dir).unlink(missing_ok=True)
    return True


def account_info(user_dir: Path) -> list[str] | None:
    data = read_json(_token_file(user_dir))
    if not data:
        return None
    expiry = datetime.fromtimestamp(data["expires_at"], timezone.utc)
    return [f"Athlete: {data.get('athlete') or '?'}",
            f"Connected: {data.get('connected_at', '?')}",
            f"Permissions: {data.get('scope', '?')}",
            f"Access token: {mask(data['access_token'])}, expires {expiry:%Y-%m-%d %H:%M} UTC "
            "(renewed automatically)",
            f"Refresh token: {mask(data['refresh_token'])}"]


class Strava:
    """API calls on behalf of one user; refreshes the access token as needed."""

    def __init__(self, user_dir: Path, http: httpx.Client | None = None):
        self.user_dir = user_dir
        self.http = http or new_http()

    def _access_token(self) -> str:
        data = read_json(_token_file(self.user_dir))
        if not data:
            raise NotConnected()
        if data["expires_at"] < time.time() + 120:
            resp = _token_request(self.http, grant_type="refresh_token",
                                  refresh_token=data["refresh_token"])
            if resp.status_code in (400, 401):
                raise NotConnected()
            if resp.status_code != 200:
                raise StravaError(f"token refresh failed: {resp.status_code} {resp.text}")
            extra = {k: v for k, v in data.items()
                     if k not in ("access_token", "refresh_token", "expires_at")}
            _save(self.user_dir, resp.json(), extra)
            data = read_json(_token_file(self.user_dir))
        return data["access_token"]

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        resp = self.http.request(method, f"{API}{path}",
                                 headers={"Authorization": f"Bearer {self._access_token()}"}, **kw)
        if resp.status_code == 401:
            raise NotConnected()
        if resp.status_code >= 400:
            raise StravaError(f"{method} {path}: {resp.status_code} {resp.text}")
        return resp

    def deauthorize(self) -> None:
        self.http.post(f"{OAUTH}/deauthorize", data={"access_token": self._access_token()})

    def upload_gpx(self, path: Path, name: str | None, description: str | None,
                   external_id: str, timeout: float = 120) -> tuple[int, bool]:
        """Uploads and waits for processing. Returns (activity_id, was_duplicate)."""
        data = {"data_type": "gpx", "external_id": external_id}
        if name:
            data["name"] = name
        if description:
            data["description"] = description
        with open(path, "rb") as f:
            upload = self._request("POST", "/uploads", data=data,
                                   files={"file": (path.name, f, "application/gpx+xml")}).json()
        deadline = time.monotonic() + timeout
        while True:
            if upload.get("activity_id"):
                return upload["activity_id"], False
            if err := upload.get("error"):
                if m := re.search(r"duplicate of .*?(\d+)", err):
                    return int(m.group(1)), True
                raise StravaError(f"upload failed: {err}")
            if time.monotonic() > deadline:
                raise StravaError(f"upload still processing after {timeout}s")
            time.sleep(2)
            upload = self._request("GET", f"/uploads/{upload['id']}").json()

    def update_activity(self, activity_id: int, **fields) -> dict:
        return self._request("PUT", f"/activities/{activity_id}", json=fields).json()

    def activities_between(self, start: datetime, end: datetime) -> list[dict]:
        return self._request("GET", "/athlete/activities", params={
            "after": int(start.timestamp()), "before": int(end.timestamp()), "per_page": 50}).json()
