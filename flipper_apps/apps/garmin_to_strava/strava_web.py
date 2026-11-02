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

import logging
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .util import Ask, read_json, write_json

log = logging.getLogger(__name__)

BASE = "https://www.strava.com"
MAX_ATTEMPTS = 3
TIMEOUT_MS = 60_000
SETTLE_MS = 10_000      # max wait for the page to go quiet after an action
APPEAR_MS = 15_000      # max wait for one of several expected elements to show up
# A regular desktop Chrome: one stable page layout, and no "HeadlessChrome" in the user agent.
BROWSER_PROFILE = {
    "locale": "en-US",
    "viewport": {"width": 1280, "height": 900},
    "user_agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/140.0.0.0 Safari/537.36"),
}

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


class StravaStepFailed(RuntimeError):
    """A step on strava.com didn't work; `files` are a screenshot and the page's HTML."""

    def __init__(self, step: str, reason: str, files: list[Path]):
        super().__init__(f"Strava step '{step}' failed: {reason}")
        self.step, self.files = step, files


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
        context = browser.new_context(storage_state=str(state) if state else None,
                                      **BROWSER_PROFILE)
        context.set_default_timeout(TIMEOUT_MS)
        try:
            yield context
        finally:
            browser.close()


def _logged_out(page) -> bool:
    return any(part in page.url for part in ("/login", "/session", "/register", "/onboarding"))


def _save_state(context, user_dir: Path) -> None:
    write_json(state_file(user_dir), context.storage_state())


# --- page helpers ------------------------------------------------------------
# Strava renders some elements twice (e.g. a hidden mobile and a visible desktop
# email field), so every interaction targets the first *visible* match.

def _visible(page, selector: str):
    return page.locator(selector).filter(visible=True).first


def _is_visible(page, selector: str) -> bool:
    return page.locator(selector).filter(visible=True).count() > 0


def _settle(page) -> None:
    """Waits for the page to go quiet, but never long: analytics can keep it busy."""
    try:
        page.wait_for_load_state("networkidle", timeout=SETTLE_MS)
    except Exception:
        pass


def _wait_for_any(page, selectors: list[str], timeout_ms: int = APPEAR_MS) -> int | None:
    """Index of the first selector that becomes visible, or None after the timeout."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        for i, selector in enumerate(selectors):
            if _is_visible(page, selector):
                return i
        if time.monotonic() > deadline:
            return None
        page.wait_for_timeout(250)


def _fill_and_submit(page, selector: str, value: str, *, click_fallback: bool = True) -> None:
    """Fills the visible field and submits its form with Enter, like a person would."""
    field = _visible(page, selector)
    field.fill(value)
    url = page.url
    field.press("Enter")
    _settle(page)
    if click_fallback and page.url == url and field.is_visible():
        button = field.locator("xpath=ancestor::form[1]").locator(SEL_SUBMIT).filter(visible=True)
        if button.count():
            button.first.click()
            _settle(page)


def _short(error: Exception) -> str:
    """First line of an error; Playwright appends a long call log."""
    return (str(error).strip().splitlines() or [type(error).__name__])[0]


def _failure(page, user_dir: Path, step: str, reason: str) -> StravaStepFailed:
    """Saves a screenshot and the HTML of the current page for debugging."""
    files = []
    shot, html = user_dir / "strava_error.png", user_dir / "strava_error.html"
    try:
        page.screenshot(path=str(shot), full_page=True)
        shot.chmod(0o600)
        files.append(shot)
    except Exception:
        log.warning("could not take a screenshot", exc_info=True)
    try:
        html.write_text(page.content())
        html.chmod(0o600)
        files.append(html)
    except Exception:
        log.warning("could not save the page HTML", exc_info=True)
    log.warning("Strava step %r failed at %s: %s", step, page.url, reason)
    return StravaStepFailed(step, reason, files)


@contextmanager
def _step(page, user_dir: Path, name: str) -> Iterator:
    """Turns any unexpected error in a step into StravaStepFailed with debug files."""
    try:
        yield
    except (SessionExpired, StravaStepFailed, RateLimited):
        raise
    except Exception as e:
        raise _failure(page, user_dir, name, _short(e)) from e


# --- login with an emailed one-time code -------------------------------------
NO_CODE_OPTION = ("Strava didn't offer to email a login code. Turn on one-time codes in the "
                  "Strava app (Settings → My Account → Switch to One-Time Codes), then send "
                  "/garmin_to_strava login strava.")


class RateLimited(RuntimeError):
    def __init__(self):
        super().__init__("Strava limits how often it emails codes. Try again in about an hour.")


def _request_code(page, user_dir: Path, email: str) -> None:
    """Gets Strava to email a one-time login code and leaves the page at the code box."""
    with _step(page, user_dir, "open the login page"):
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        _visible(page, SEL_EMAIL).wait_for()
    with _step(page, user_dir, "enter the email"):
        _visible(page, SEL_EMAIL).fill(email)
        if not _is_visible(page, SEL_EMAIL_CODE):
            # Two-step login: the code option appears after the email is submitted.
            _fill_and_submit(page, SEL_EMAIL, email)
    with _step(page, user_dir, "ask for an emailed code"):
        found = _wait_for_any(page, [SEL_EMAIL_CODE, SEL_CODE, SEL_FORGOT])
        if found == 0:
            _visible(page, SEL_EMAIL_CODE).click()
            _settle(page)
        elif found == 2:
            # Strava's "Forgot your password?" also emails a one-time code.
            _visible(page, SEL_FORGOT).click()
            _settle(page)
            if _wait_for_any(page, [SEL_EMAIL, SEL_CODE]) == 0:
                _fill_and_submit(page, SEL_EMAIL, email)
        elif found is None:
            raise _failure(page, user_dir, "ask for an emailed code", NO_CODE_OPTION)
    if _wait_for_any(page, [SEL_CODE]) is None:
        if RATE_LIMITED_RE.search(page.locator("body").inner_text()):
            raise RateLimited()
        raise _failure(page, user_dir, "open the code box", NO_CODE_OPTION)


def connect(user_dir: Path, ask: Ask, reason: str = "") -> None:
    """Logs in with an emailed one-time code and saves the session cookies.

    Works for every kind of Strava account, including ones that sign in with Google.
    """
    email = ask(f"{reason}🔑 Connect Strava: what's your Strava email? (With Google sign-in, "
                "that's your Gmail address.)")
    with _browser() as context:
        page = context.new_page()
        _request_code(page, user_dir, email)
        prompt = f"Strava emailed a login code to {email}. What is it?"
        for _ in range(MAX_ATTEMPTS):
            code = ask(prompt, secret=True)
            with _step(page, user_dir, "enter the code"):
                _fill_and_submit(page, SEL_CODE, code, click_fallback=False)
                if _wait_for_any(page, [SEL_CODE], timeout_ms=2_000) is None \
                        and not _logged_out(page):
                    break
            prompt = "❌ Strava didn't accept that code. Check the email and try again:"
        else:
            raise RuntimeError(f"Strava didn't accept the code {MAX_ATTEMPTS} times")

        with _step(page, user_dir, "open the dashboard"):
            page.goto(f"{BASE}/dashboard", wait_until="domcontentloaded")
            _settle(page)
            if _logged_out(page):
                raise _failure(page, user_dir, "open the dashboard",
                               "the login didn't stick, please try again")
            name_el = page.locator(SEL_ATHLETE_NAME).filter(visible=True)
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


# --- upload --------------------------------------------------------------------
def upload(user_dir: Path, gpx: Path, name: str | None, description: str | None,
           sport_type: str | None, photos: list[Path]) -> tuple[int, bool, str | None]:
    """Uploads the GPX and applies the details. Returns (activity_id, was_duplicate, photo_error).

    Raises SessionExpired if the saved login no longer works.
    """
    with _browser(state_file(user_dir)) as context:
        page = context.new_page()
        with _step(page, user_dir, "open the upload page"):
            page.goto(f"{BASE}/upload/select", wait_until="domcontentloaded")
            _settle(page)
            if _logged_out(page):
                raise SessionExpired()

        with _step(page, user_dir, "upload the GPX file"):
            # File inputs are usually hidden behind a styled button; that's fine here.
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
                error = page.locator(SEL_UPLOAD_ERROR).filter(visible=True)
                raise _failure(page, user_dir, "upload the GPX file", "Strava rejected it: "
                               + (error.first.inner_text().strip() if error.count() else page.url))
            activity_id = ids[-1]

        with _step(page, user_dir, "open the activity's edit page"):
            page.goto(f"{BASE}/activities/{activity_id}/edit", wait_until="domcontentloaded")
            _settle(page)
            if _logged_out(page):
                raise SessionExpired()
        with _step(page, user_dir, "set the title and description"):
            if name:
                _visible(page, SEL_NAME).fill(name)
            if description:
                _visible(page, SEL_DESCRIPTION).fill(description)
        if sport_type:
            try:
                _visible(page, SEL_SPORT).select_option(sport_type, timeout=5_000)
            except Exception:
                pass  # keep Strava's own guess
        photo_error = None
        if photos:
            try:
                page.locator(SEL_FILE_INPUT).first.set_input_files([str(p) for p in photos])
                _settle(page)
                page.wait_for_function(f"() => !document.querySelector('{SEL_BUSY}')",
                                       timeout=180_000)
            except Exception as e:
                photo_error = _short(e)
        with _step(page, user_dir, "save the activity"):
            _visible(page, SEL_SAVE).click()
            page.wait_for_url(re.compile(rf".*/activities/{activity_id}(?!/edit).*"))
            _save_state(context, user_dir)  # keep cookies fresh
    return activity_id, duplicate, photo_error
