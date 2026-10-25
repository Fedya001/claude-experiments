import json

import pytest

from apps.garmin_to_strava import garmin


class FakeGarmin:
    def __init__(self, email=None, password=None, prompt_mfa=None):
        self.email, self.password, self.prompt_mfa = email, password, prompt_mfa

    def login(self, tokenstore):
        path = garmin.Path(tokenstore) / "garmin_tokens.json"
        if self.email is None:
            if not path.exists():
                raise garmin.GarminConnectAuthenticationError("no tokens")
            return
        if self.password != "right":
            raise garmin.GarminConnectAuthenticationError("bad password")
        assert self.prompt_mfa() == "123456"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"di_token": "a" * 40, "di_refresh_token": "b" * 40}))

    def get_full_name(self):
        return "Fedya"


@pytest.fixture(autouse=True)
def fake_garmin(monkeypatch):
    monkeypatch.setattr(garmin, "Garmin", FakeGarmin)


class Asker:
    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def __call__(self, prompt, *, secret=False):
        self.asked.append((prompt, secret))
        return self.answers.pop(0)


def test_first_login_asks_and_saves_token_not_password(tmp_path):
    ask = Asker("me@x.org", "wrong", "me@x.org", "right", "123456")
    garmin.login(tmp_path, ask)
    assert [secret for _, secret in ask.asked] == [False, True, False, True, True]
    assert "rejected" in ask.asked[2][0]
    saved = "".join(p.read_text() for p in tmp_path.rglob("*.json"))
    assert "right" not in saved and "123456" not in saved
    info = garmin.account_info(tmp_path)
    assert info[0] == "Account: Fedya (me@x.org)" and "aaaa…aaaa" in info[2]


def test_saved_token_is_reused_without_asking(tmp_path):
    garmin.login(tmp_path, Asker("me@x.org", "right", "123456"))
    ask = Asker()
    garmin.login(tmp_path, ask)
    assert ask.asked == []


def test_gives_up_after_repeated_failures(tmp_path):
    with pytest.raises(RuntimeError, match="failed 3 times"):
        garmin.login(tmp_path, Asker(*["me@x.org", "wrong"] * 3))


def test_forget(tmp_path):
    garmin.login(tmp_path, Asker("me@x.org", "right", "123456"))
    assert garmin.forget(tmp_path) and not garmin.is_connected(tmp_path)
    assert garmin.account_info(tmp_path) is None and not garmin.forget(tmp_path)
