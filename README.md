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

Nestor plays a chime and speaks at the speaker's own volume (it never changes the volume for announcements, since
every change makes the speaker's sound; only alarms turn it up). Audio that was playing in the speaker's
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

The briefing gives:
- the date, the weather (Open-Meteo, free, no key), and sunrise and sunset;
- what's still on your calendar today (the first 5, from Datebook) and when to leave for the next thing;
- today's reminders (Nestor's and Datebook's), and bills and assignments due, grouped by class ("for Movie VFX, Unit
  11 Discussion Forum and Unit 11 Homework"). Canvas course codes are never read out; set short class names in
  `class_names` in `config.yaml`;
- the plans waiting in Datebook;
- GitHub news from overnight.

The tomorrow preview gives tomorrow's weather, how many things are on your calendar, the first one and when to
leave for it, what to bring, reminders, what's due and the waiting plans. Set `home_location` in `config.yaml` to
`"Town, ST"`, a ZIP code or `"lat,lon"` for the weather.

To use `remind` and `briefing` from any folder, add these to `~/.bashrc`:

```bash
alias remind='"/c/Vibes/Google Home/.venv/Scripts/python" "/c/Vibes/Google Home/remind.py"'
alias briefing='"/c/Vibes/Google Home/.venv/Scripts/python" "/c/Vibes/Google Home/briefing.py"'
```

## Hey John

John is Nestor's voice assistant. Call him in any of these ways, and he answers out loud on the speaker:
- **"Hey John"**, wait for the tone, then ask;
- in one breath: **"Hey John, what time is it?"**;
- with his name at the end: **"What time is it, John?"**, **"Set a timer for 5 minutes, John"**, **"Goodnight
  John"**, **"Good morning John"**.

"Good morning / start my day" and "goodnight" run straight away without asking Claude. Things he can do:


- "What's on my calendar tomorrow?" or "Did my package come?" (from Datebook)
- "Add dinner with Sam Friday at 7 to Datebook" (your phone shows Datebook's prompt to confirm)
- "Remind me in 20 minutes to take the pizza out"
- "Start my day" ends the sleeping period, reads the day ahead, then anything held overnight
- "Goodnight" previews tomorrow and starts the sleeping period until quiet hours end
- "Turn the volume down to 30", "What were the last alerts?", "Remember my locker code is 4412"
- "Set a timer for 10 minutes", "Wake me up at 7", "Set an alarm for 6:45 every weekday"
- "When's the next train?" or "Next train back from New York?" (live NJ Transit)
- Anything else, with web search: "Who won the game last night?"

After an answer, John listens for about 5 seconds for a follow-up without "Hey John". Say "stop" or "never mind" to
end. You'll hear these sounds:
- a rising tone when he's listening;
- a falling tone when he's got it;
- soft taps while Claude is thinking;
- a low tone if something went wrong.

Music is coming in a later milestone. For lights, see [Govee lights](#govee-lights).

### Timers and alarms

Timers and alarms ring on the speaker in bursts of the alarm tone with a few seconds' gap, so John can hear you. The
first burst also says what's ringing ("Your pasta timer is done.", "It's 7 AM. Gym."). While it's ringing:
- **"Stop":** stops it. There's no need for "Hey John" first while something rings, but "Hey John, stop" works too.
- **"Snooze":** rings again in 9 minutes, or as long as you say ("snooze for 2 minutes").

They ring at `alarm_volume` (75% unless set in `config.yaml`). Alarms ring up to 5 minutes and timers up to 1
minute if nobody stops them. They ring even in the sleeping period.
Stopping an alarm during the sleeping period also runs "start my day". Alarms can repeat ("every weekday", "Monday,
Wednesday and Friday"). Ask John to list or cancel them. They're kept in `data/timers.json`.

### Trains

"When's the next train?" reads NJ Transit's live departure board for your trip: the next 3 trains, their tracks and
delays. Ask "the next train back" for the other way, or name any two stations. It uses your NJ Transit developer
account (the same one as Datebook) and keeps its sign-in token in `data/`, because NJ Transit allows only 5 new
tokens a day. Your trip is Datebook's saved trip once Datebook is linked; until then, set `train_from` and
`train_to` in `config.yaml` to the stations' two-letter codes, e.g. `"NB"` and `"NY"`.

**How it works:**
- **Hearing his name:** whenever a speech detector ([Silero](https://github.com/snakers4/silero-vad), via
  [openWakeWord](https://github.com/dscripka/openWakeWord)) hears a short phrase, a tiny Whisper model checks whether
  it starts with "Hey John" or ends in ", John". There's no training. Talking *about* someone named John ("I'll call
  John") doesn't wake him, because speech-to-text only writes the comma when you're talking *to* John. A trained
  openWakeWord model (`hey_john.onnx` in the project folder) is used instead if you have one.
- **Speech to text:** [faster-whisper](https://github.com/SYSTRAN/faster-whisper) turns what you say into text, on
  the PC.
- **The answer:** Claude (Opus 5.5 at low effort) answers, using Nestor's tools.

**Privacy:** your voice never leaves the PC. Only the text of what you said goes to Claude, along with what Nestor
looks up for the answer.

### Setting up John

1. **A Claude API key just for Nestor:** in the [Anthropic Console](https://platform.claude.com), create a new API key
   (name it "Nestor") and set a monthly spend limit if you like.
2. Create a file called `.env` in the project folder (git never sees it) with the key:

   ```
   ANTHROPIC_API_KEY=sk-ant-...
   NJT_USERNAME=your NJ Transit developer username (for trains)
   NJT_PASSWORD=its password
   ```

3. Nothing to train: John listens for the words. (If you ever train an openWakeWord model for "Hey John", save it
   in the project folder as `hey_john.onnx` and it's used instead.)

4. In `config.yaml`, set `john_owner_name` to your name. Once a USB microphone is plugged in, set `microphone` to part
   of its name; `python -m nestor` logs which microphone John is using.
5. Start Nestor (`python -m nestor`). The first start downloads the speech-to-text model (about 500 MB). It logs
   `Hey John is listening on ...`, or lists what's still missing.

John's settings in `config.yaml`:

| Setting | What it does |
|---|---|
| `john_speech_threshold` | How sure the speech detector must be that it hears a voice; `python -m nestor --mic-test` shows its scores |
| `john_wake_whisper` | The small model that checks phrases for "Hey John" (`tiny.en`, downloaded the first time) |
| `john_wake_threshold` | Only with a trained `hey_john.onnx`: lower wakes more easily, but also by mistake |
| `whisper_model` | `small.en` (more accurate) or `base.en` (faster) |
| `john_model`, `john_effort` | The Claude model and effort |
| `john_follow_up_seconds` | How long he listens for a follow-up |

John's memory is in `data/memory.json`. The sleeping period that "goodnight" and "start my day" change is in
`data/sleep.json`.

## Govee lights

Nestor controls Govee lights over the home Wi-Fi with Govee's LAN API. It's local and instant, with no Govee
account. In the Govee Home app, open each light, then its settings, and switch on **LAN Control**. Nestor finds the
lights by itself when it starts. Turn them off for Nestor with `govee: false` in `config.yaml`.

**What the lights do by themselves:**
- **Alerts:** a white flash when an alert is spoken. A Datebook leave-by gets an amber pulse, and "leave now" gets
  red flashes. Afterwards the lights go back to exactly what they were showing, mood included.
- **John:** they glow Datebook's aqua while John listens and thinks.
- **Good morning:** a 2-minute sunrise, from dim candle orange to bright daylight, while the day ahead is read.
- **Goodnight:** a 1-minute fade to off.

**Groups:** name groups of lights in `config.yaml` by their device ids (Nestor logs them when it finds the lights):

```yaml
light_groups:
  "wall": ["2F:3A:..."]
  "living room": ["04:DC:...", "04:5B:..."]
```

"The wall" or "the living room lights" then means just that group; "lights" alone means all of them. Setting one
group during a mood takes only that group out of it.

**By voice:**
- "Lights to blue, John", "the wall at 30 percent", "living room lights off", "focus mode".
- **Moods, as a conversation:** only when you ask for lighting. Just saying what you're doing doesn't start one.
  1. "Hey John, I want lights for a movie I'm watching."
  2. He asks a question or two: what kind, cozy or lively. "A comedy, cozy."
  3. He shows one look at a time on the lights, each with a name he makes up ("This is Popcorn Sunset: warm amber,
     slowly breathing"), and asks what you think. He waits a little longer for your answer after showing a look.
  4. Say "next", "go back", "that one", or tweak it: "warmer", "slower", "more purple", "dimmer".
  5. He remembers what you liked for next time and offers to save it, e.g. "save it as comedy night".
  6. Later: "Comedy night, John", "What moods have I saved?", "Delete the horror one".

**Effects** are made by Nestor, by changing the colours a few times a second:
- steady;
- breathe (slowly brightening and dimming);
- drift (blending between colours);
- flicker (like a candle);
- lightning (dim, with white flashes);
- party (hopping between colours).

Each comes slow, medium or fast. Saved moods are in `data/moods.json`.

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
| `POST /start-my-day` | End the sleeping period, speak the day ahead, then what was held overnight |
| `POST /goodnight` | Speak tomorrow's preview, then start the sleeping period until quiet hours end |
| `GET /timers` | Timers and alarms set, when each rings, and what's ringing |
| `POST /timers/stop`, `POST /timers/snooze` | Stop or snooze what's ringing |
| `DELETE /timers/<id>` | Cancel a timer or alarm |
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
| `GET /datebook/state` | The snapshot, plus `connected`, `updated`, `stale` (no update for 24 hours) and `phone_home` |
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
  "trip": {"from": "NB", "to": "NY", "from_name": "New Brunswick", "to_name": "New York Penn Station"},
  "events": [{"id": "88-1795107600", "title": "Soccer", "start": "2026-11-18T09:00", "end": "2026-11-18T10:30",
              "all_day": false, "place": "Field 3, Buccleuch Park", "calendar": "Personal", "from": "Coach Dan",
              "bring": "cleats, $20", "confirmation": "", "track_url": "", "leave_by": "2026-11-18T08:35",
              "travel": "20 min drive"}]
}
```

`events` are your calendar events from today to 14 days ahead, from the phone's calendars Datebook uses. This is
how Nestor knows your calendar, with no Google login of its own. All-day events have just a date (`"start":
"2026-11-18"`).

**Event heads-ups:** while your phone is home, Nestor says "In 10 minutes: CS lecture." before each event with a
time. All-day events and events Datebook already sends a leave-by for are skipped. Set the minutes with
`event_heads_up_minutes` in `config.yaml` (0 turns it off).

**Is the phone home?** Every call Datebook makes with its token counts. Its waiting request for actions repeats
about every 50 seconds while it's on the home Wi-Fi, so the phone counts as home if it called in the last 5
minutes.

**Actions** wait for the phone for up to 10 minutes, then are dropped, so an old tap never pops up later:
- `{"action": "add", "id": 12}`: Datebook shows its Add to calendar? prompt for that plan.
- `{"action": "ignore", "id": 12}`: Datebook ignores the plan.
- `{"action": "done", "id": 4}`: marks a bill, assignment or reminder done.
- `{"action": "new_plan", "text": "dinner with Sam Friday at 7"}`: Datebook reads it like a typed note and shows the
  prompt.

## Status

Milestones 1 (speaking), 2 (alerts), 3 (reminders and briefing) and 4 (the calendar from Datebook) are done, and
Nestor's side of the Datebook link is ready. Hey John (milestone 5) is being tested: talking, Datebook,
reminders, timers, alarms, trains, start my day and goodnight.
