# flipper_apps

A collection of small apps you write yourself, in the spirit of Flipper Zero apps, all reachable from one **Telegram bot**. The bot is the gateway: each app is one command, and the bot routes `/command` messages to it, along with any text and photos. Adding an app means dropping a folder into `apps/`.

The gateway talks to the official [Telegram Bot API](https://core.telegram.org/bots/api) directly with `httpx` and long polling, so it needs no bot framework, webhook or public URL.

| Command | What it does |
|---|---|
| `/help` | Lists the commands, or shows the usage of one: `/help garmin_to_strava` |
| `/ping` | Example app that replies with `pong` |
| `/garmin_to_strava` | Merges Garmin activities and uploads them to Strava with photos |

## Layout
```
bot/        the Telegram gateway: Bot API client, App base class, app discovery, polling runner
apps/       your apps, one package each, exporting APP = SomeApp()
tests/
```

## Adding an app
1. Create `apps/my_app/__init__.py`:
   ```python
   from bot.app import App, Context

   class MyApp(App):
       command = "my_app"            # a-z, 0-9, _ only (Telegram rule)
       description = "Shown in /help and in the command menu"
       usage = "/my_app <args> — longer help"

       def handle(self, ctx: Context) -> None:
           msg = ctx.reply("working…")
           ctx.edit(msg, f"done: {ctx.text}, {len(ctx.photos)} photos")

   APP = MyApp()
   ```
2. Restart the bot. The app is discovered automatically and the Telegram command menu is updated.

`ctx` gives each call:
- `text`: everything after the command.
- `photos` / `documents`: downloaded files. All photos of an album are collected into one call, and images sent "as file" count as photos.
- `reply` / `edit` / `send_file`.
- `data_dir`: persistent, at `data/<command>/`.
- `work_dir`: temporary, deleted after the call.

Each call runs in its own thread. If an app raises an exception, the error is reported in the chat.

## Setting up the Telegram bot
1. In Telegram, open [@BotFather](https://t.me/BotFather) and send `/newbot`.
2. Choose a display name (for example "Flipper Apps") and a username that ends in `bot` (for example `my_flipper_apps_bot`).
3. BotFather replies with a token like `123456789:AAH…`. Put it in `.env` as `TELEGRAM_TOKEN`, and keep it secret: anyone with it can control the bot. If it leaks, send `/revoke` to BotFather to get a new one.
4. Message [@userinfobot](https://t.me/userinfobot) to get your numeric user id, and put it in `.env` as `ALLOWED_USER_IDS`. The bot ignores everyone not listed there.
5. Open a chat with your new bot and press **Start**. Bots can't message you first.

You don't need to set up the command menu: the gateway registers every app's command with Telegram (`setMyCommands`) each time it starts. For testing, a second bot with its own token keeps your everyday bot untouched.

## Running
Needs **Python 3.11+**. Check with `python3 --version`, then set up a virtual environment in this folder in one of two ways.

**Option A: your `python3` is already 3.11 or newer**
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

**Option B: your Python is older (for example 3.6 on Ubuntu 18.04)**

Install a newer Python next to the system one with [uv](https://docs.astral.sh/uv/). It needs no `sudo`. Don't replace the system `python3`, because the OS depends on it.
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # then open a new terminal
uv venv -p 3.12                                   # downloads Python 3.12 if needed
source .venv/bin/activate
python --version                                  # should print 3.12.x
uv pip install -r requirements.txt
```

**Then, with either option:**
```bash
playwright install chromium   # browser for the Strava photo step
cp .env.example .env          # fill in TELEGRAM_TOKEN and ALLOWED_USER_IDS (see above)
python -m bot
```
Send `/ping` to the bot to check that it's running. Run `source .venv/bin/activate` again in every new terminal before using `python`.

### Deploying (always on)
**Requirements:**
- An always-on Linux machine, such as a ~€4/month VPS (Hetzner), a Raspberry Pi or Fly.io with a volume.
- [Docker](https://docs.docker.com/engine/install/).
- About 3 GB of free disk space, because the image is large (check with `df -h`).
- On a Raspberry Pi, a 64-bit OS: `uname -m` must print `aarch64`.

The image includes its own Python 3.12, so the host's Python version doesn't matter.

#### Step 1: choose your Compose command
Docker Compose comes in two forms, and you only need the one that works on your machine. Try them in this order:
```bash
docker compose version     # Compose v2 plugin (newer Docker)
docker-compose version     # standalone Compose (older setups)
```
Use the first one that prints a version. Then define the `dc` shortcut that **every command below uses**:
```bash
alias dc='docker compose'      # if the first one worked
alias dc='docker-compose'      # if only the second one worked
```
To keep the shortcut in new terminals, add the same alias line to `~/.bashrc` (or `~/.zshrc`), for example `echo "alias dc='docker-compose'" >> ~/.bashrc`.

If you see `unknown shorthand flag: 'd' in -d`, you used `docker compose` but the v2 plugin isn't installed. Use `docker-compose` instead, or install the plugin with `sudo apt-get install docker-compose-plugin`.

#### Step 2: start the bot
Run these inside the `flipper_apps/` folder, after you've created `.env` and done the app logins:
```bash
dc up -d --build      # build the image and start it in the background
dc logs -f            # wait for "polling; commands: …", then Ctrl+C
```
Then send `/ping` to the bot in Telegram.

#### Everyday commands
| Task | Command |
|---|---|
| Is it running? | `dc ps`: `Up` means running, `Restarting` means it keeps crashing (check the logs) |
| Follow the logs | `dc logs -f` (Ctrl+C stops following; the bot keeps running) |
| Last 100 log lines | `dc logs --tail 100` |
| Stop | `dc stop`. It stays stopped, even after a reboot, until you start it again. |
| Start again | `dc start` |
| Restart | `dc restart` |
| Apply changes to `.env` | `dc up -d`. A plain `restart` keeps the old settings. |
| Update to the latest code | `git pull && dc up -d --build` |
| Remove the container | `dc down`. Your tokens in `data/` are kept, and `dc up -d` brings it back. |

#### What happens on errors
- **An error inside one app**, such as a failed Garmin login, is reported to you in the chat. The bot keeps running.
- **Network or Telegram outages** don't stop the bot. It waits and retries on its own.
- **If the bot process itself dies**, for example from a bad config or running out of memory, Docker starts it again automatically. That's because of `restart: unless-stopped` in `docker-compose.yml`. If it keeps crashing, Docker waits longer between attempts.
- **A config mistake**, such as an empty `TELEGRAM_TOKEN`, makes it crash on every start. `dc ps` then shows `Restarting`, and `dc logs --tail 20` shows the reason. Fix `.env`, then run `dc up -d`.
- **A bot you stopped yourself** with `dc stop` is never restarted automatically.

#### Starting automatically after a server reboot
The container comes back after a reboot as long as the Docker service itself starts at boot. Enable that once:
```bash
sudo systemctl enable docker
systemctl is-enabled docker     # should print "enabled"
```
To test it, run `sudo reboot`, then `dc ps` after the machine is back. If you stopped the bot with `dc stop` before the reboot, it stays stopped.

#### Troubleshooting: `no space left on device`
The build needs several GB of temporary space. Check what's using it and remove unused Docker data:
```bash
df -h                      # free space per disk
docker system df           # space used by Docker
docker system prune -a     # remove unused images, stopped containers, build cache
docker builder prune -a    # remove the remaining build cache
```
Then run `dc up -d --build` again.

`./data` is mounted into the container and holds all tokens and sessions. Set `TZ` in `.env` so that "today" means your day.

---

## `/garmin_to_strava`

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

### One-time setup (on your laptop)
```bash
pip install -r requirements.txt && playwright install chromium
python -m apps.garmin_to_strava.cli auth-garmin   # email, password, MFA code; caches tokens (~1 year)
python -m apps.garmin_to_strava.cli auth-strava   # needs STRAVA_CLIENT_ID/SECRET in .env
python -m apps.garmin_to_strava.cli auth-web      # opens a browser: log in to strava.com (for photos)
python -m apps.garmin_to_strava.cli run "dry today | Test"   # try it without Telegram
```
- **Strava API app**: create one at <https://www.strava.com/settings/api> and set *Authorization Callback Domain* to `localhost`. During `auth-strava`, the browser ends up on a `localhost` page that fails to load. That's expected: copy that URL and paste it into the terminal.
- Copy `data/garmin_to_strava/` to the server along with the code.
- **Turn off Garmin → Strava auto-sync.** Otherwise the separate activities are already on Strava, and the API can't delete them. The bot lists any overlapping Strava activities so you can delete them by hand.

### Caveats
- Garmin has no public personal API. This app uses the unofficial [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library, which can break when Garmin changes its login. If the cached tokens expire, re-run `auth-garmin`.
- The photo step automates the Strava website, and its selectors are in `apps/garmin_to_strava/strava_web.py`. If Strava changes its page, that step fails, but the activity is still uploaded and the bot tells you to add the photos by hand. If the web session expires, re-run `auth-web`.
- Telegram compresses photos sent the normal way. To keep full resolution, send them "as file".
