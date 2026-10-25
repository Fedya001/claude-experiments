"""Strava through the strava.com website: login, GPX upload, title/description/photos.

Strava's public API needs an OAuth app and can't upload photos, so everything goes
through the website with a headless browser instead. The user's password is only
used to log in; afterwards just the browser cookies are kept, per Telegram user.

Strava's page markup is not a stable interface. All selectors live at the top of
this file so they are easy to adjust if Strava changes its site.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .util import Ask, read_json, write_json

BASE = "https://www.strava.com"
MAX_ATTEMPTS = 3
TIMEOUT_MS = 60_000

SEL_EMAIL = "input[type=email], input[name=email], #email"
SEL_PASSWORD = "input[type=password], input[name=password], #password"
SEL_SUBMIT = "button[type=submit], input[type=submit], #login-button"
SEL_USE_PASSWORD = "text=/use (a |your )?password/i"
SEL_CODE = ("input[autocomplete=one-time-code], input[name=code], input[name=otp], "
            "input[inputmode=numeric]")
SEL_LOGIN_ERROR = ".alert-message, [role=alert], .error, [data-testid*=error]"
SEL_ATHLETE_NAME = ".athlete-name, [data-testid=athlete-name], #athlete-profile h1"
SEL_FILE_INPUT = "input[type=file]"
SEL_DUPLICATE = "text=/duplicate/i"
SEL_ACTIVITY_LINK = "a[href*='/activities/']"
SEL_UPLOAD_ERROR = ".error, .alert-message, [role=alert]"
SEL_NAME = "input[name='activity[name]'], #activity_name"
SEL_DESCRIPTION = "textarea[name='activity[description]'], #activity_description"
SEL_SPORT = "select[name='activity[sport_type]'], #activity_sport_type, select[name='activity[type]']"
SEL_SAVE = "button[type=submit]:has-text('Save'), input[type=submit][value='Save']"
SEL_BUSY = "[class*=uploading], [class*=Uploading], .spinner"


class SessionExpired(RuntimeError):
    pass


def state_file(user_dir: Path) -> Path:
    return user_dir / "strava_web_state.json"


def _account_file(user_dir: Path) -> Path:
    return user_dir / "strava_account.json"


def is_connected(user_dir: Path) -> bool:
    return state_file(user_dir).exists()


@contextmanager
def _browser(state: Path | None = None) -> Iterator:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(storage_state=str(state) if state else None)
        context.set_default_timeout(TIMEOUT_MS)
        try:
            yield context
        finally:
            browser.close()


def _logged_out(page) -> bool:
    return any(part in page.url for part in ("/login", "/session", "/register", "/onboarding"))


def _save_state(context, user_dir: Path) -> None:
    write_json(state_file(user_dir), context.storage_state())


def connect(user_dir: Path, ask: Ask, reason: str = "") -> None:
    """Asks for email and password (and an emailed code if Strava wants one), logs in
    with a headless browser and saves the session cookies. The password is never stored."""
    note = reason
    for _ in range(MAX_ATTEMPTS):
        email = ask(f"{note}🔑 Connect Strava: what's your Strava email?")
        password = ask("Strava password? (If you sign in with Google or Apple, first set a "
                       "password in the Strava app: Settings → Account → Change password.)",
                       secret=True)
        with _browser() as context:
            page = context.new_page()
            page.goto(f"{BASE}/login")
            page.locator(SEL_EMAIL).first.fill(email)
            password_box = page.locator(SEL_PASSWORD).first
            if not password_box.is_visible():
                # Newer two-step login: email first, then a choice of code or password.
                page.locator(SEL_SUBMIT).first.click()
                page.wait_for_load_state("networkidle")
                if page.locator(SEL_USE_PASSWORD).count():
                    page.locator(SEL_USE_PASSWORD).first.click()
            password_box.wait_for(state="visible")
            password_box.fill(password)
            page.locator(SEL_SUBMIT).first.click()
            page.wait_for_load_state("networkidle")

            if page.locator(SEL_CODE).count() and page.locator(SEL_CODE).first.is_visible():
                code = ask("Strava emailed you a verification code. What is it?", secret=True)
                page.locator(SEL_CODE).first.fill(code)
                page.locator(SEL_SUBMIT).first.click()
                page.wait_for_load_state("networkidle")

            if _logged_out(page):
                error = page.locator(SEL_LOGIN_ERROR)
                detail = error.first.inner_text().strip() if error.count() else ""
                note = f"❌ Strava login failed{': ' + detail if detail else ''}. "
                continue

            page.goto(f"{BASE}/dashboard")
            name_el = page.locator(SEL_ATHLETE_NAME)
            name = name_el.first.inner_text().strip() if name_el.count() else None
            _save_state(context, user_dir)
        write_json(_account_file(user_dir), {
            "email": email,
            "name": name,
            "connected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        return
    raise RuntimeError(f"Strava login failed {MAX_ATTEMPTS} times")


def forget(user_dir: Path) -> bool:
    existed = is_connected(user_dir) or _account_file(user_dir).exists()
    state_file(user_dir).unlink(missing_ok=True)
    _account_file(user_dir).unlink(missing_ok=True)
    return existed


def account_info(user_dir: Path) -> list[str] | None:
    """Human-readable description of the saved Strava login, or None. Shows no cookies."""
    if not is_connected(user_dir):
        return None
    account = read_json(_account_file(user_dir)) or {}
    state = read_json(state_file(user_dir)) or {}
    expiries = [c["expires"] for c in state.get("cookies", [])
                if "strava.com" in c.get("domain", "") and (c.get("expires") or 0) > 0]
    lines = [f"Account: {account.get('name') or '?'} ({account.get('email') or '?'})",
             f"Connected: {account.get('connected_at', '?')}",
             f"Saved browser session: {len(state.get('cookies', []))} cookies"]
    if expiries:
        until = datetime.fromtimestamp(max(expiries), timezone.utc)
        lines[-1] += f", valid until about {until:%Y-%m-%d}"
    return lines


def upload(user_dir: Path, gpx: Path, name: str | None, description: str | None,
           sport_type: str | None, photos: list[Path]) -> tuple[int, bool, str | None]:
    """Uploads the GPX and applies the details. Returns (activity_id, was_duplicate, photo_error).

    Raises SessionExpired if the saved login no longer works.
    """
    with _browser(state_file(user_dir)) as context:
        page = context.new_page()
        page.goto(f"{BASE}/upload/select")
        if _logged_out(page):
            raise SessionExpired()

        page.locator(SEL_FILE_INPUT).first.set_input_files(str(gpx))
        # Processing ends with a link to the new activity, or a duplicate/error notice.
        page.wait_for_function(
            """() => /duplicate|error/i.test(document.body.innerText)
                  || [...document.querySelectorAll("a[href*='/activities/']")]
                       .some(a => /\\/activities\\/\\d+/.test(a.href))""",
            timeout=180_000)
        duplicate = page.locator(SEL_DUPLICATE).count() > 0
        ids = [int(m.group(1)) for href in page.locator(SEL_ACTIVITY_LINK).evaluate_all(
                   "els => els.map(e => e.href)")
               if (m := re.search(r"/activities/(\d+)", href))]
        if not ids:
            error = page.locator(SEL_UPLOAD_ERROR)
            raise RuntimeError("Strava rejected the upload: "
                               + (error.first.inner_text().strip() if error.count() else page.url))
        activity_id = ids[-1]

        page.goto(f"{BASE}/activities/{activity_id}/edit")
        if _logged_out(page):
            raise SessionExpired()
        if name:
            page.locator(SEL_NAME).first.fill(name)
        if description:
            page.locator(SEL_DESCRIPTION).first.fill(description)
        if sport_type:
            try:
                page.locator(SEL_SPORT).first.select_option(sport_type, timeout=5_000)
            except Exception:
                pass  # keep Strava's own guess
        photo_error = None
        if photos:
            try:
                page.locator(SEL_FILE_INPUT).first.set_input_files([str(p) for p in photos])
                page.wait_for_load_state("networkidle")
                page.wait_for_function(f"() => !document.querySelector('{SEL_BUSY}')",
                                       timeout=180_000)
            except Exception as e:
                photo_error = str(e).splitlines()[0]
        page.locator(SEL_SAVE).first.click()
        page.wait_for_url(re.compile(rf".*/activities/{activity_id}(?!/edit).*"))
        _save_state(context, user_dir)  # keep cookies fresh
    return activity_id, duplicate, photo_error
