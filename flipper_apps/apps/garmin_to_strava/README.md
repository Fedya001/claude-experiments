# `/garmin_to_strava`

Merges the day's Garmin activities into one and uploads it to Strava, with your title, description and photos. It's one of the [flipper_apps](../../README.md); set up the bot there first.

## Usage
Send `/garmin_to_strava help` (or just `/garmin_to_strava`) to see the short help in the chat. A bare command never uploads anything.

To upload, send one message, with your photos attached and the command in the caption:
```
/garmin_to_strava today | Morning ride to the lake | Coffee stop at km 30
```
The bot then:
1. finds the matching Garmin Connect activities that have GPS and downloads each as GPX,
2. merges them into one track in time order, the same as [joewein gpxmerge](https://joewein.net/bike/gpxmerge/), with one segment per activity so the gaps count as paused time,
3. uploads the merged track on strava.com and sets the title, description and sport type (taken from Garmin),
4. attaches your photos,
5. reports progress in a single message that it keeps editing, ending with the activity link.

**Selector** (the part before the first `|`): `today`, `yesterday`, `2026-10-24`, `last 2`, `last ride` (meaning the single most recent ride), `rides today`, `last 3 runs`, or `latest activities today`. Types are ride, run, walk, hike and swim. If you leave out the `|` separators, the first line is the selector only if it names a day or `last`; otherwise it's the title and the selector is `today`. So a one-word title like `Ride` stays a title. After the title comes the description.

## Accounts and logins
The bot asks the first time it needs each account:
- **Garmin**, on your first call: your Garmin Connect email and password, and the verification code Garmin sends you if your account uses two-step verification. Garmin offers no other way for personal accounts. Your password replies are deleted from the chat right after reading.
- **Strava**, on your first upload: your Strava email, then the **one-time code Strava emails you**. No password is involved, so this **works with Google or Apple sign-in**: for a Google account, the email is your Gmail address and the code arrives there.
  - If the bot says Strava didn't offer to email a code, turn on one-time codes once in the Strava app (Settings → My Account → **Switch to One-Time Codes**), then send `/garmin_to_strava login strava`.
  - Strava limits how often it emails codes. If you request too many, wait about an hour.

Strava has no free API for this (it needs a paid subscription, and even then can't add photos). So the bot uses strava.com itself in a headless browser, logged in with that code.

The bot never stores passwords. It keeps only the login results: the Garmin token, which is renewed automatically, and the strava.com browser cookies, which last a long time. They're saved **separately for each Telegram user** in `data/garmin_to_strava/users/<telegram_user_id>/`. If a login stops working, the bot simply asks again (for Strava, a new emailed code). Send `/cancel` at any question to stop.

Manage your logins with these commands. They only ever show or change **your own** data:

| Command | What it does |
|---|---|
| `/garmin_to_strava accounts` | Shows your connected Garmin and Strava accounts: names, emails, when connected, and the Garmin tokens masked like `abcd…wxyz` (never in full) |
| `/garmin_to_strava login garmin` | Logs in to Garmin now (again), without uploading anything. Same with `strava`. `connect` works too. |
| `/garmin_to_strava forget garmin` | Deletes your saved Garmin login, after asking you to confirm. Also works with `strava` or `all`. `logout` works too. |
| `/garmin_to_strava help` | Shows the short help |

**Turn off Garmin → Strava auto-sync** in Garmin Connect. Otherwise each activity is also on Strava separately, and you'd have to delete those copies by hand.

## Try it
Send `/garmin_to_strava today | Test`. The first time, the bot asks for your Garmin login and then your Strava email and code. Then it uploads the activity and replies with its link. You can rename or delete the test activity in Strava afterwards.

You can also run the app in a terminal, without Telegram. It asks the same questions there and saves the logins for your Telegram user id (the first of `ALLOWED_USER_IDS`, or `--user <id>`), so the bot reuses them. Run it from the `flipper_apps/` folder:
```bash
python -m apps.garmin_to_strava.cli "today | Test"                         # Python venv
dc run --rm bot python -m apps.garmin_to_strava.cli "today | Test"         # Docker
python -m apps.garmin_to_strava.cli accounts
```

## Caveats
- Garmin has no public API for personal accounts. This app uses the unofficial [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library, which can break when Garmin changes its login.
- The Strava steps automate the strava.com website, and the page details they rely on are listed at the top of [`strava_web.py`](strava_web.py). If Strava changes its site, the bot reports which step failed. If only the photos fail, the activity is still uploaded and the bot tells you to add them in the Strava app.
- Telegram compresses photos sent the normal way. To keep full resolution, send them "as file".
