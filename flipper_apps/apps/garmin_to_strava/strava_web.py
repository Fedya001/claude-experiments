"""Adds photos to an activity through the strava.com website (the API can't upload photos).

Uses a browser session saved once by `cli auth-web`. Strava's page markup is not
a stable interface, so selectors may need updating if Strava changes its site.
"""
from __future__ import annotations

from pathlib import Path

BASE = "https://www.strava.com"


class WebSessionError(RuntimeError):
    pass


def state_file(data_dir: Path) -> Path:
    return data_dir / "strava_web_state.json"


def save_session(data_dir: Path, timeout_s: int = 300) -> None:
    """Opens a visible browser; log in to Strava there and the session is saved."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(f"{BASE}/login")
        print("Log in to Strava in the opened browser window…")
        page.wait_for_url(f"{BASE}/dashboard**", timeout=timeout_s * 1000)
        state_file(data_dir).parent.mkdir(parents=True, exist_ok=True)
        page.context.storage_state(path=str(state_file(data_dir)))
        state_file(data_dir).chmod(0o600)
        browser.close()


def add_photos(data_dir: Path, activity_id: int, photos: list[Path], timeout_s: int = 180) -> None:
    from playwright.sync_api import sync_playwright

    state = state_file(data_dir)
    if not state.exists():
        raise WebSessionError("no Strava web session: run "
                              "`python -m apps.garmin_to_strava.cli auth-web` "
                              "(see README → 4. Connect Strava)")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(storage_state=str(state))
        page = context.new_page()
        page.set_default_timeout(timeout_s * 1000)
        page.goto(f"{BASE}/activities/{activity_id}/edit")
        if "/login" in page.url or "/session" in page.url:
            raise WebSessionError("Strava web session expired: run "
                                  "`python -m apps.garmin_to_strava.cli auth-web` again")

        file_input = page.locator("input[type=file]").first
        file_input.wait_for(state="attached")
        file_input.set_input_files([str(p) for p in photos])

        # Wait until all uploads finished: thumbnails appear and no spinner remains.
        page.wait_for_load_state("networkidle")
        page.wait_for_function(
            "() => !document.querySelector('[class*=uploading], [class*=Uploading], .spinner')")

        save = page.locator("button[type=submit]:has-text('Save'), "
                            "input[type=submit][value='Save']").first
        save.click()
        page.wait_for_url(f"{BASE}/activities/{activity_id}**")
        page.wait_for_load_state("networkidle")
        context.storage_state(path=str(state))  # keep cookies fresh
        browser.close()
