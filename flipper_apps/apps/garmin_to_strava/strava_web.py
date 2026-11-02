"""Strava through the strava.com website: login, GPX upload, title/description/photos.

Strava's API needs a paid subscription and can't upload photos, so everything goes
through the website with a headless browser instead. Logging in uses Strava's
one-time code: the user gives their email and pastes the code Strava emails them
(this also works for accounts that sign in with Google). Only the browser cookies
are kept, per Telegram user.

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
SEL_SUBMIT = "button[type=submit], input[type=submit], #login-button"
SEL_EMAIL_CODE = (":is(button, a):text-matches('email me a (one-time )?code|send (me )?a code"
                  "|(use|with) a one-time code|log ?in with (a )?code', 'i')")
SEL_FORGOT = ":is(button, a):text-matches('forgot', 'i')"
RATE_LIMITED_RE = re.compile(r"too many|try again later|rate limit", re.IGNORECASE)
SEL_CODE = ("input[autocomplete=one-time-code], input[name=code], input[name=otp], "
            "input[inputmode=numeric]")
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


NO_CODE_OPTION = ("Strava didn't offer to email a login code. Turn on one-time codes in the "
                  "Strava app (Settings → My Account → Switch to One-Time Codes), then send "
                  "/garmin_to_strava login strava.")
RATE_LIMITED = "Strava limits how often it emails codes. Try again in about an hour."


def _click_if_visible(page, selector: str) -> bool:
    target = page.locator(selector)
    if target.count() and target.first.is_visible():
        target.first.click()
        page.wait_for_load_state("networkidle")
        return True
    return False


def _code_box_visible(page) -> bool:
    box = page.locator(SEL_CODE)
    return bool(box.count()) and box.first.is_visible()


def _request_code(page, email: str) -> str | None:
    """Gets Strava to email a one-time login code. Returns None, or why it failed."""
    page.goto(f"{BASE}/login")
    page.locator(SEL_EMAIL).first.fill(email)
    if not _click_if_visible(page, SEL_EMAIL_CODE):
        # Two-step login: the code option appears after the email is submitted.
        page.locator(SEL_SUBMIT).first.click()
        page.wait_for_load_state("networkidle")
        if not _click_if_visible(page, SEL_EMAIL_CODE):
            # Strava's "Forgot your password?" also emails a one-time code.
            if not _click_if_visible(page, SEL_FORGOT):
                return NO_CODE_OPTION
            box = page.locator(SEL_EMAIL)
            if box.count() and box.first.is_visible():
                box.first.fill(email)
                page.locator(SEL_SUBMIT).first.click()
                page.wait_for_load_state("networkidle")
    if RATE_LIMITED_RE.search(page.locator("body").inner_text()):
        return RATE_LIMITED
    return None if _code_box_visible(page) else NO_CODE_OPTION


def connect(user_dir: Path, ask: Ask, reason: str = "") -> None:
    """Logs in with an emailed one-time code and saves the session cookies.

    Works for every kind of Strava account, including ones that sign in with Google.
    """
    email = ask(f"{reason}🔑 Connect Strava: what's your Strava email? (With Google sign-in, "
                "that's your Gmail address.)")
    with _browser() as context:
        page = context.new_page()
        if problem := _request_code(page, email):
            raise RuntimeError(problem)
        prompt = f"Strava emailed a login code to {email}. What is it?"
        for _ in range(MAX_ATTEMPTS):
            code = ask(prompt, secret=True)
            page.locator(SEL_CODE).first.fill(code)
            page.locator(SEL_SUBMIT).first.click()
            page.wait_for_load_state("networkidle")
            if not _logged_out(page) and not _code_box_visible(page):
                break
            prompt = "❌ Strava didn't accept that code. Check the email and try again:"
        else:
            raise RuntimeError(f"Strava didn't accept the code {MAX_ATTEMPTS} times")

        page.goto(f"{BASE}/dashboard")
        if _logged_out(page):
            raise RuntimeError("Strava login didn't stick, please try again")
        name_el = page.locator(SEL_ATHLETE_NAME)
        name = name_el.first.inner_text().strip() if name_el.count() else None
        _save_state(context, user_dir)
    write_json(_account_file(user_dir), {
        "email": email,
        "name": name,
        "connected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


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
