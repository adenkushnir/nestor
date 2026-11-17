# Nestor

Nestor makes a Google Nest Audio speaker do things Google Home can't do on its own. It runs as a Python app on a Windows
PC on the same Wi-Fi.

## Planned features

- **Speak anything** from a terminal (`python speak.py "dinner's ready"`) or from any program through a local web API.
- **Alerts** from your computer: Claude Code finished a task, a GitHub Actions run failed, a long command is done.
- **Reminders and a morning briefing** with weather, news, sunrise and sunset, and your Google Calendar.
- **"Hey Google" commands that run Nestor's code**, using Google Home routines: "start my day" ends the sleeping
  period and gives the day ahead, "goodnight" previews tomorrow, plus "what's next" and "next train".
- **Phone control panel** on your home Wi-Fi.
- **"Hey John" voice assistant**: a microphone by the wall screen hears you, Claude answers out loud on the speaker,
  and it can set reminders, add plans to Datebook, search the web and control Nestor.
- **Govee lights**: alert flashes, focus colours, goodnight fade.
- **Datebook** (the [Datebook](https://github.com/adenkushnir/text-to-calendar) phone app): its leave-by alerts,
  travel changes and reminders spoken at home, and its plans, lists and reminders in the briefing.
- **Later:** Nestor running 24/7 on an ASUS Tinker Board with a 7" wall screen showing your day in Datebook's look.

## How it works

Nestor talks to the speaker over the Cast protocol on your local network (no Google account or cloud needed). It turns
text into speech with Microsoft Edge neural voices and serves the audio from the PC so the speaker can play it.

## Setup (Windows, Git Bash)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m nestor --list-speakers
```

Copy `config.example.yaml` to `config.yaml` and set `speaker_name` to your speaker's name from the list. The first time
Nestor runs, Windows asks whether Python may use the network: allow it on **private** networks, because the speaker
fetches its audio from the PC.

## Use

Run the service, which keeps the speaker connection open so messages play quickly:

```bash
.venv/Scripts/python -m nestor
```

Make the speaker talk from any terminal:

```bash
.venv/Scripts/python speak.py "Dinner's ready"
```

If the service isn't running, `speak.py` connects to the speaker itself (a few seconds slower).

From any program on the PC or your home network:

```bash
curl -X POST http://localhost:8765/speak -H "Content-Type: application/json" -d '{"text": "Backup finished"}'
```

Add `"wait": true` to get the reply only after the message has been spoken. Note that anyone on your home Wi-Fi can
reach this API.

Nestor plays a chime, speaks at `announce_volume`, then puts the volume back. Audio that was playing in the speaker's
built-in media player resumes. Music from apps like Spotify stops and has to be restarted by hand.

## Alerts

Alerts are announcements from your computer. Unlike `speak.py`, they respect **quiet hours** (`quiet_hours` in
`config.yaml`, 22:00–08:00 by default). Alerts that arrive at night are saved and played when quiet hours end, starting
with "While you were asleep, 3 messages came in."

Any program can send one:

```bash
curl -X POST http://localhost:8765/alert -H "Content-Type: application/json" -d '{"text": "Backup finished"}'
```

### Long commands: tell.py

`tell.py` runs a command, then says whether it worked and how long it took ("Train finished after 12 minutes", or
"Build failed after 40 seconds, with exit code 1"):

```bash
.venv/Scripts/python tell.py python train.py --epochs 50
.venv/Scripts/python tell.py --name "The export" ./export.sh
```

To use it from any folder as just `tell`, add this line to `~/.bashrc` (Git Bash):

```bash
alias tell='"/c/Vibes/Google Home/.venv/Scripts/python" "/c/Vibes/Google Home/tell.py"'
```

### Claude Code

`hooks/claude_code.py` makes the speaker say "Claude finished in Red Piste after 4 minutes" when a Claude Code reply took
longer than `claude_min_minutes` (1 by default). Shorter replies stay silent. Add it to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "\"C:/Vibes/Google Home/.venv/Scripts/python.exe\" \"C:/Vibes/Google Home/hooks/claude_code.py\""}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "\"C:/Vibes/Google Home/.venv/Scripts/python.exe\" \"C:/Vibes/Google Home/hooks/claude_code.py\""}]}]
  }
}
```

The hook prints nothing and always succeeds, so it never gets in Claude Code's way, even when Nestor isn't running.

### GitHub

While `python -m nestor` runs, it checks your GitHub repos every 5 minutes and announces:

- a CI check that fails ("The Android check failed on Datebook"), and when it passes again;
- new stars;
- new issues and pull requests opened by other people (not you, and not bots).

It uses the GitHub CLI's login (`gh auth login`), so Nestor stores no token. The first check after setup only records
what is already there. Turn it off with `github_watch: false`.

`spoken_names` in `config.yaml` sets how folder, repo and branch names are said, e.g. `"red-piste": "Red Piste"`.

## Reminders

Each reminder is spoken twice: a heads-up 15 minutes before ("In 15 minutes: call mum.") and again at its time
("Reminder: call mum."). Reminders are alerts, so during quiet hours they are held until morning; `remind` warns you
when that will happen. Nestor must be running at the time for a reminder to be spoken.

One-off reminders, with the time at the start or the end:

```bash
.venv/Scripts/python remind.py 18:00 call mum
.venv/Scripts/python remind.py tomorrow 9:30 dentist
.venv/Scripts/python remind.py take the pizza out in 20m
.venv/Scripts/python remind.py fri 7pm dinner with Sam
.venv/Scripts/python remind.py 12/3 2pm haircut
```

Repeating reminders go in `reminders.yaml` (copy `reminders.example.yaml`). Nestor rereads it on every check, so edits
work without a restart:

```yaml
- text: Fencing training
  days: [tue, thu]     # or daily, weekdays, weekends, sun
  time: "18:00"
```

## Briefing

```bash
.venv/Scripts/python briefing.py          # speak it now
.venv/Scripts/python briefing.py --show   # just print it
.venv/Scripts/python briefing.py --json   # the data behind it
.venv/Scripts/python briefing.py --tomorrow   # tomorrow's preview instead (works with --show and --json)
```

The briefing gives the date, the weather (Open-Meteo, free, no key), sunrise and sunset, today's reminders (Nestor's
and Datebook's), bills and assignments due, the plans waiting in Datebook, and GitHub news from overnight. The
tomorrow preview gives tomorrow's weather, reminders, what's due and the waiting plans. Set `home_location` in
`config.yaml` to `"Town, ST"`, a ZIP code or `"lat,lon"` for the weather.

To use `remind` and `briefing` from any folder, add these to `~/.bashrc`:

```bash
alias remind='"/c/Vibes/Google Home/.venv/Scripts/python" "/c/Vibes/Google Home/remind.py"'
alias briefing='"/c/Vibes/Google Home/.venv/Scripts/python" "/c/Vibes/Google Home/briefing.py"'
```

## API

Nestor's web server (port 8765, home network only) is also how the phone page, Datebook and the wall display talk to
it. Everything is JSON.

| Request | What it does |
|---|---|
| `POST /speak` `{"text", "wait"}` | Speak straight away |
| `POST /alert` `{"text", "source", "expires", "key"}` | Speak an alert (see below) |
| `GET /alerts?limit=20` | Recent alerts, newest first, with what happened to each (`status`) |
| `GET /reminders` | One-off, repeating and today's reminders |
| `POST /reminders` `{"text", "at"}` or `{"text", "when": "tomorrow 6pm"}` | Add a one-off reminder |
| `DELETE /reminders/<id>` | Delete a one-off reminder |
| `GET /briefing?day=tomorrow` | The briefing as data and text (`day` is `today` unless given) |
| `POST /briefing` `{"day", "wait"}` | Speak the briefing |
| `GET /health` | Is Nestor running, and which speaker |
| `POST /pair`, `DELETE /pair`, `/datebook/...` | The Datebook link (see [Datebook](#datebook)) |

An alert is spoken straight away, or held during quiet hours and played when they end. Two optional fields change that:
- **`expires`**: a date and time, like `2026-11-17T18:40:00` (a time zone is allowed). If the alert can't be spoken by
  then, it's dropped instead of played late.
- **`key`**: an alert with the same key as one in the last 12 hours isn't spoken again.

The answer's `status` says what happened: `spoken`, `held`, `dropped` or `repeat`. Alerts with `"source": "datebook"`
are tidied for speaking ("6:37 PM · 20 min drive" is read as "6:37 PM, 20 minute drive").

## Datebook

Nestor and the [Datebook](https://github.com/adenkushnir/text-to-calendar) Android app work together on the home
Wi-Fi. Nothing goes over the internet, and away from home Datebook simply doesn't send anything.

**Finding Nestor:** Nestor announces itself on the network as `_nestor._tcp` (mDNS), so Datebook finds it with no
address to type, also after Nestor moves to another computer.

**Pairing**, once per phone:

```bash
.venv/Scripts/python -m nestor --pair
```

This prints a 6-digit code that works for 10 minutes (5 wrong tries and it stops working). Type it in Datebook under
Settings > Nestor. Datebook gets a token it sends with every call. Nestor keeps only a fingerprint of it, in
`data/paired.json`; delete that file to unpair every phone. Pages on the same computer as Nestor (the wall display)
need no token.

| Request | What it does |
|---|---|
| `POST /pair` `{"code", "device"}` | Pair with the code; answers `{"token"}` |
| `DELETE /pair` | Unpair the phone whose token is sent |
| `PUT /datebook/state` | Datebook sends its whole snapshot; it replaces the last one |
| `GET /datebook/state` | The snapshot, plus `connected`, `updated` and `stale` (no update for 24 hours) |
| `GET /datebook/events` | The snapshot as a live feed (Server-Sent Events), for the wall display |
| `POST /datebook/actions` | Ask the phone to do something (from the wall display or Hey John) |
| `GET /datebook/actions?wait=50` | Datebook collects the waiting actions, holding the request open up to 50 seconds |

Datebook calls send `Authorization: Bearer <token>`.

**The snapshot** (every part is optional; dates are `2026-11-20`, times `2026-11-20T19:00`):

```json
{
  "waiting": [{"id": 12, "title": "Dinner at Luigi's", "start": "2026-11-20T19:00", "end": "", "all_day": false,
               "place": "Luigi's, 12 Main St", "from": "Jake", "kind": "event", "change": ""}],
  "lists": {
    "packages": [{"id": 6, "title": "Cleats", "carrier": "UPS", "number": "1Z...", "track_url": "https://...",
                  "expected": "2026-11-19"}],
    "bills": [{"id": 4, "title": "Electric bill", "due": "2026-11-20"}],
    "assignments": [{"id": 5, "title": "CS essay", "due": "2026-11-21T23:59"}],
    "trips": [{"id": 3, "title": "Chicago", "start": "2026-12-04", "end": "2026-12-07"}]
  },
  "notes": [{"id": 9, "text": "Gate code 4412"}],
  "reminders": [{"id": 7, "text": "Call the dentist", "at": "2026-11-18T09:00"}],
  "trip": {"from": "NB", "to": "NY", "from_name": "New Brunswick", "to_name": "New York Penn Station"}
}
```

**Actions** wait for the phone for up to 10 minutes, then are dropped, so an old tap never pops up later:
- `{"action": "add", "id": 12}`: Datebook shows its Add to calendar? prompt for that plan.
- `{"action": "ignore", "id": 12}`: Datebook ignores the plan.
- `{"action": "done", "id": 4}`: marks a bill, assignment or reminder done.
- `{"action": "new_plan", "text": "dinner with Sam Friday at 7"}`: Datebook reads it like a typed note and shows the
  prompt.

## Status

Milestones 1 (speaking), 2 (alerts) and 3 (reminders and briefing) are done, and Nestor's side of the Datebook link is
ready; the other features are on the way.
