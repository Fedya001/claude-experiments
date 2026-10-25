"""Official Strava API: OAuth tokens, GPX upload, activity update."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import httpx

API = "https://www.strava.com/api/v3"
OAUTH = "https://www.strava.com/oauth"
REDIRECT_URI = "http://localhost/exchange_token"
SCOPE = "activity:read_all,activity:write"

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


class Strava:
    def __init__(self, data_dir: Path, client_id: str | None = None, client_secret: str | None = None):
        self.token_file = data_dir / "strava_tokens.json"
        self.client_id = client_id or os.getenv("STRAVA_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("STRAVA_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise StravaError("set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in .env "
                              "(see README → 4. Connect Strava)")
        self.http = httpx.Client(timeout=60)

    # --- OAuth -------------------------------------------------------------
    def authorize_url(self) -> str:
        return (f"{OAUTH}/authorize?client_id={self.client_id}&response_type=code"
                f"&redirect_uri={REDIRECT_URI}&approval_prompt=force&scope={SCOPE}")

    def exchange_code(self, code_or_url: str) -> None:
        m = re.search(r"[?&]code=([^&]+)", code_or_url)
        code = m.group(1) if m else code_or_url.strip()
        self._save(self._token_request(grant_type="authorization_code", code=code))

    def _token_request(self, **params) -> dict:
        resp = self.http.post(f"{OAUTH}/token", data={
            "client_id": self.client_id, "client_secret": self.client_secret, **params})
        if resp.status_code != 200:
            raise StravaError(f"token request failed: {resp.text}")
        return resp.json()

    def _save(self, tokens: dict) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        keep = {k: tokens[k] for k in ("access_token", "refresh_token", "expires_at")}
        self.token_file.write_text(json.dumps(keep))
        self.token_file.chmod(0o600)

    def _access_token(self) -> str:
        if not self.token_file.exists():
            raise StravaError("Strava isn't connected yet: run "
                              "`python -m apps.garmin_to_strava.cli auth-strava` "
                              "(see README → 4. Connect Strava)")
        tokens = json.loads(self.token_file.read_text())
        if tokens["expires_at"] < time.time() + 120:
            tokens = self._token_request(grant_type="refresh_token",
                                         refresh_token=tokens["refresh_token"])
            self._save(tokens)
        return tokens["access_token"]

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        resp = self.http.request(method, f"{API}{path}",
                                 headers={"Authorization": f"Bearer {self._access_token()}"}, **kw)
        if resp.status_code >= 400:
            raise StravaError(f"{method} {path}: {resp.status_code} {resp.text}")
        return resp

    # --- Activities --------------------------------------------------------
    def upload_gpx(self, path: Path, name: str | None, description: str | None,
                   external_id: str, timeout: float = 120) -> tuple[int, bool]:
        """Uploads and waits for processing. Returns (activity_id, was_duplicate)."""
        with open(path, "rb") as f:
            data = {"data_type": "gpx", "external_id": external_id}
            if name:
                data["name"] = name
            if description:
                data["description"] = description
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
                raise StravaError(f"upload still processing after {timeout}s: {upload.get('status')}")
            time.sleep(2)
            upload = self._request("GET", f"/uploads/{upload['id']}").json()

    def update_activity(self, activity_id: int, **fields) -> dict:
        return self._request("PUT", f"/activities/{activity_id}", json=fields).json()

    def activities_between(self, start: datetime, end: datetime) -> list[dict]:
        return self._request("GET", "/athlete/activities", params={
            "after": int(start.timestamp()), "before": int(end.timestamp()), "per_page": 50}).json()
