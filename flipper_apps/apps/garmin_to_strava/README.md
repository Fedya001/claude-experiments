# `/garmin_to_strava`

Merges the day's Garmin activities into one and uploads it to Strava, with your title, description and photos. It's one of the [flipper_apps](../../README.md); set up the bot there first.

## Usage
Send one message with your photos attached, with the command in the caption:
```
/garmin_to_strava today | Morning ride to the lake | Coffee stop at km 30
```
The bot then:
1. finds the matching Garmin Connect activities that have GPS and downloads each as GPX,
2. merges them into one track in time order, the same as [joewein gpxmerge](https://joewein.net/bike/gpxmerge/), with one segment per activity so the gaps count as paused time,
3. uploads the merged track to Strava with the title and description, and sets the sport type from Garmin,
4. adds the photos through strava.com, because the Strava API has no photo upload,
5. reports progress in a single message that it keeps editing, ending with the activity link.

**Selector** (the part before the first `|`): `today`, `yesterday`, `2026-10-24`, `last 2`, `last ride` (meaning the single most recent ride), `rides today`, `last 3 runs`, or `latest activities today`. Types are ride, run, walk, hike and swim. If you leave out the `|` separators, the first line is the selector only if it names a day or `last`; otherwise it's the title and the selector is `today`. So a one-word title like `Ride` stays a title. After the title comes the description. Start with `dry` (or `dry-run`) to get the merged GPX back without uploading.

## Setup
All commands run inside the `flipper_apps/` folder, not this app folder. Each command has two forms:
- **Python venv:** `python -m apps.garmin_to_strava.cli …`
- **Docker:** `dc run --rm bot python -m apps.garmin_to_strava.cli …`. `dc` is the Compose shortcut from the [main README](../../README.md#docker-only), and anything saved still lands in `./data` on the host.

### 1. Connect Garmin
Garmin has no public API for personal accounts, so the bot logs in as you once and keeps the login token. It lasts about a year. The token, like everything the app stores, is kept in `data/garmin_to_strava/`.

```bash
python -m apps.garmin_to_strava.cli auth-garmin    # Python venv
dc run --rm bot python -m apps.garmin_to_strava.cli auth-garmin   # Docker
```
Enter your Garmin email and password when asked, and the MFA code if your account uses one. Then check that the token was saved:
```bash
ls data/garmin_to_strava/garmin_tokens/     # should list garmin_tokens.json
```

**Optional:** put `GARMIN_EMAIL` and `GARMIN_PASSWORD` in `.env`. The bot then logs in again by itself when the token expires. This doesn't work if your account uses MFA; in that case just repeat the command above.

**Troubleshooting:** "Garmin isn't connected yet" or "Username and password are required" means the bot found no token. Usually the command wasn't run, or it was run from a different folder than `flipper_apps/`. Run it again from `flipper_apps/`.

### 2. Connect Strava
#### 2a. API access (uploads)
1. Go to <https://www.strava.com/settings/api> and create an API application:
   - **Application Name**: anything, for example "Flipper Apps".
   - **Category**: for example "Data Importer".
   - **Website**: anything, for example `http://localhost`.
   - **Authorization Callback Domain**: `localhost`.
2. Copy **Client ID** and **Client Secret** into `.env` as `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET`.
3. Authorize the app for your account:
   ```bash
   python -m apps.garmin_to_strava.cli auth-strava    # Python venv
   dc run --rm bot python -m apps.garmin_to_strava.cli auth-strava   # Docker
   ```
   Open the printed URL in any browser and click **Authorize**. You end up on a `http://localhost/exchange_token?…&code=…` page that fails to load. That's expected: copy the whole URL from the address bar and paste it into the terminal.
4. Check that `data/garmin_to_strava/strava_tokens.json` now exists.

#### 2b. Photos (optional)
The Strava API can't upload photos, so the bot adds them through the strava.com website using a saved browser login. Creating that login opens a real browser window, so it needs a computer with a screen. It won't work inside Docker or over SSH.

On your laptop, with the Python venv from the [main README](../../README.md#python-venv):
```bash
python -m apps.garmin_to_strava.cli auth-web     # log in to strava.com in the window that opens
```
If the bot runs on another machine, copy the saved login there:
```bash
scp data/garmin_to_strava/strava_web_state.json <user>@<server>:<path>/flipper_apps/data/garmin_to_strava/
```
Without this step, uploads still work, and the bot tells you to add photos in the Strava app.

**Also turn off Garmin → Strava auto-sync** in Garmin Connect. Otherwise each activity is already on Strava separately, and the API can't delete those copies. The bot lists any overlapping Strava activities so you can delete them by hand.

### 3. Try it
Do a dry run first. It fetches and merges your real Garmin activities but uploads nothing, and saves the merged GPX in `data/garmin_to_strava/`:
```bash
python -m apps.garmin_to_strava.cli run "dry today | Test"                      # Python venv
dc run --rm bot python -m apps.garmin_to_strava.cli run "dry today | Test"      # Docker
```
Then, with the bot running, send it `/garmin_to_strava dry today`.

## Settings (`.env`)
| Variable | Needed | Purpose |
|---|---|---|
| `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` | yes | Your Strava API application, from [2a](#2a-api-access-uploads) |
| `GARMIN_EMAIL`, `GARMIN_PASSWORD` | no | Log in to Garmin again automatically when the token expires (doesn't work with MFA) |
| `TZ` | recommended | Which day "today" means |

## Caveats
- Garmin has no public personal API. This app uses the unofficial [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library, which can break when Garmin changes its login. If the token expires, repeat [Connect Garmin](#1-connect-garmin).
- The photo step automates the Strava website, and its selectors are in [`strava_web.py`](strava_web.py). If Strava changes its page, that step fails, but the activity is still uploaded and the bot tells you to add the photos by hand. If the web login expires, repeat [Photos](#2b-photos-optional).
- Telegram compresses photos sent the normal way. To keep full resolution, send them "as file".
