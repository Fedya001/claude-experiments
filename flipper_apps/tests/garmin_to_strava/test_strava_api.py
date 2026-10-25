import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from apps.garmin_to_strava import strava_api


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_ID", "123")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "shh-secret")


class FakeStravaServer:
    def __init__(self):
        self.requests = []
        self.refresh_status = 200
        self.upload_error = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        body = parse_qs(request.content.decode()) if request.method == "POST" and \
            request.headers.get("content-type", "").startswith("application/x-www") else {}
        if path == "/oauth/token":
            if body["grant_type"] == ["authorization_code"]:
                if body["code"] != ["good"]:
                    return httpx.Response(400, json={"message": "Bad Request"})
                return httpx.Response(200, json={
                    "access_token": "access-" + "a" * 30, "refresh_token": "refresh-" + "r" * 30,
                    "expires_at": int(time.time()) + 3600,
                    "athlete": {"firstname": "Fedya", "lastname": "R"}})
            if self.refresh_status != 200:
                return httpx.Response(self.refresh_status, json={"message": "invalid"})
            return httpx.Response(200, json={
                "access_token": "fresh-" + "f" * 30, "refresh_token": "refresh2-" + "r" * 30,
                "expires_at": int(time.time()) + 3600})
        if path == "/api/v3/uploads":
            if self.upload_error:
                return httpx.Response(201, json={"id": 1, "error": self.upload_error})
            return httpx.Response(201, json={"id": 1, "activity_id": 555})
        if path == "/oauth/deauthorize":
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.fixture
def server(monkeypatch):
    srv = FakeStravaServer()
    monkeypatch.setattr(strava_api, "new_http",
                        lambda: httpx.Client(transport=httpx.MockTransport(srv)))
    return srv


def redirect(url, **overrides):
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    params = {"state": q["state"], "code": "good", "scope": "read,activity:write,activity:read_all"}
    params.update(overrides)
    return "http://localhost/exchange_token?" + "&".join(f"{k}={v}" for k, v in params.items())


class Asker:
    """Answers each link prompt by building the redirect from the link in it."""

    def __init__(self, *responses):
        self.responses, self.prompts = list(responses), []

    def __call__(self, prompt, *, secret=False):
        self.prompts.append(prompt)
        link = next(w for w in prompt.split() if w.startswith("https://www.strava.com/oauth"))
        r = self.responses.pop(0)
        return r(link) if callable(r) else r


def test_connect_via_link_saves_tokens_but_not_client_secret(tmp_path, server):
    ask = Asker(lambda link: redirect(link, state="forged"),
                "not a url",
                lambda link: redirect(link, scope="read"),
                lambda link: redirect(link))
    with pytest.raises(strava_api.StravaError):   # 3 bad answers exhaust the attempts
        strava_api.connect(tmp_path, Asker(*ask.responses[:3]))
    strava_api.connect(tmp_path, Asker(lambda link: redirect(link)))
    saved = (tmp_path / "strava_tokens.json").read_text()
    assert "shh-secret" not in saved and json.loads(saved)["athlete"] == "Fedya R"
    info = strava_api.account_info(tmp_path)
    assert info[0] == "Athlete: Fedya R" and "acce…aaaa" in info[3]


def test_connect_retry_messages(tmp_path, server):
    ask = Asker(lambda link: redirect(link, state="forged"),
                lambda link: redirect(link, scope="read"),
                lambda link: redirect(link))
    strava_api.connect(tmp_path, ask)
    assert "doesn't look like the right address" in ask.prompts[1]
    assert "keep the permission to upload" in ask.prompts[2]
    link = next(w for w in ask.prompts[0].split() if w.startswith("https://"))
    q = parse_qs(urlparse(link).query)
    assert q["client_id"] == ["123"] and q["scope"] == ["activity:write,activity:read_all"]


def test_missing_app_credentials_explain_setup(tmp_path, monkeypatch):
    monkeypatch.delenv("STRAVA_CLIENT_ID")
    with pytest.raises(strava_api.StravaError, match="STRAVA_CLIENT_ID"):
        strava_api.connect(tmp_path, Asker())


def connected(tmp_path, expires_at):
    (tmp_path / "strava_tokens.json").write_text(json.dumps({
        "access_token": "old-" + "o" * 30, "refresh_token": "refresh-" + "r" * 30,
        "expires_at": expires_at, "athlete": "Fedya R", "scope": "activity:write"}))


def test_expired_token_is_refreshed_and_kept(tmp_path, server):
    connected(tmp_path, expires_at=0)
    gpx = tmp_path / "m.gpx"
    gpx.write_text("<gpx/>")
    assert strava_api.Strava(tmp_path, strava_api.new_http()).upload_gpx(
        gpx, "T", None, "ext") == (555, False)
    data = json.loads((tmp_path / "strava_tokens.json").read_text())
    assert data["access_token"].startswith("fresh-") and data["athlete"] == "Fedya R"
    assert server.requests[-1].headers["Authorization"] == "Bearer " + data["access_token"]


def test_revoked_refresh_token_raises_not_connected(tmp_path, server):
    connected(tmp_path, expires_at=0)
    server.refresh_status = 400
    with pytest.raises(strava_api.NotConnected):
        strava_api.Strava(tmp_path, strava_api.new_http()).update_activity(1, name="x")


def test_duplicate_upload_returns_existing_id(tmp_path, server):
    connected(tmp_path, expires_at=int(time.time()) + 3600)
    server.upload_error = "m.gpx duplicate of activity 4321"
    gpx = tmp_path / "m.gpx"
    gpx.write_text("<gpx/>")
    assert strava_api.Strava(tmp_path, strava_api.new_http()).upload_gpx(
        gpx, None, None, "ext") == (4321, True)


def test_forget_revokes_and_deletes(tmp_path, server):
    connected(tmp_path, expires_at=int(time.time()) + 3600)
    assert strava_api.forget(tmp_path)
    assert server.requests[-1].url.path == "/oauth/deauthorize"
    assert not strava_api.is_connected(tmp_path) and not strava_api.forget(tmp_path)
