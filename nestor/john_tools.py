# Hey John's tools: what Claude can look up and do through Nestor (Datebook, reminders, timers and alarms, trains, the
# day ahead and goodnight, volume, recent alerts, memory) plus web search, with the context line John sees before each
# thing the user says
import datetime
import json
from nestor import datebook
from nestor import memory
from nestor import reminders
from nestor import routines
from nestor import timers
from nestor import trains
from nestor.announcer import read_history
from nestor.briefing import build_briefing
from nestor.spoken import spoken_clock
from nestor.spoken import spoken_moment
MAX_TOOL_RESULT = 12000  # Characters; a tool result longer than this is cut, so one answer stays affordable
TEXT = {"type": "string"}
WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}

# A tool definition for Claude with a strict schema: every listed property is required
def tool(name, description, properties=None):
    properties = properties or {}
    return {"name": name, "description": description, "strict": True,
            "input_schema": {"type": "object", "properties": properties, "required": list(properties),
                             "additionalProperties": False}}

# Every tool John can use through Nestor
def tool_definitions():
    return [
        tool("datebook_overview", "Read the user's Datebook: their calendar events from today to 14 days ahead (with "
             "places, leave-by times and what to bring), plans waiting to be added to the calendar, bills, "
             "assignments, packages, trips, notes, their Datebook reminders and train trip. Also says whether their "
             "phone is home and whether the copy is old."),
        tool("datebook_action", "Ask Datebook on the user's phone to do something. new_plan sends words to Datebook (a "
             "plan, a reminder or a note, e.g. 'dinner with Sam Friday at 7'); Datebook reads it and shows its usual "
             "prompt on the phone for the user to confirm. add shows the Add to calendar prompt for a waiting plan, "
             "ignore ignores a waiting plan, done marks a bill, assignment or reminder done (use ids from "
             "datebook_overview). The phone acts within seconds when it's home, otherwise when it gets home (up to 10 "
             "minutes later).",
             {"action": {"type": "string", "enum": ["new_plan", "add", "ignore", "done"]},
              "id": {"type": "string", "description": "The item's id for add, ignore and done; empty for new_plan"},
              "text": {"type": "string", "description": "The plan's words for new_plan; empty otherwise"}}),
        tool("add_reminder", "Add a Nestor reminder, spoken at home on the speaker 15 minutes ahead and at its time.",
             {"text": {"type": "string", "description": "What to remind about, e.g. 'take the pizza out'"},
              "at": {"type": "string", "description": "Local date and time, like 2026-11-18T09:30"}}),
        tool("list_reminders", "List Nestor's reminders: one-off ones with their ids, repeating ones, and today's."),
        tool("delete_reminder", "Delete a one-off Nestor reminder by its id (from list_reminders).", {"id": TEXT}),
        tool("start_my_day", "The user said 'start my day' (or good morning, I'm up): ends the sleeping period "
             "and reads the day ahead and anything held overnight aloud. It speaks for itself, so add nothing after "
             "it."),
        tool("goodnight", "The user said 'goodnight' (or going to bed): reads tomorrow's preview aloud, then "
             "starts the sleeping period until morning. It speaks for itself, so add nothing after it."),
        tool("briefing", "Get the briefing as text, to answer questions about the weather, the day or tomorrow.",
             {"day": {"type": "string", "enum": ["today", "tomorrow"]}}),
        tool("set_volume", "Set the speaker's volume (music and everything else), or just how loud Nestor and "
             "John speak.",
             {"target": {"type": "string", "enum": ["speaker", "announcements"]},
              "percent": {"type": "integer", "description": "0 to 100"}}),
        tool("recent_alerts", "The latest alerts Nestor announced or held (Datebook, reminders, GitHub...), newest "
             "first.",
             {"count": {"type": "integer", "description": "How many, 1 to 10"}}),
        tool("set_timer", "Start a timer that rings on the speaker when it's done.",
             {"minutes": {"type": "number", "description": "How long, e.g. 10 or 0.5"},
              "label": {"type": "string", "description": "What it's for, e.g. 'pasta'; empty if not said"}}),
        tool("set_alarm", "Set an alarm that rings on the speaker until stopped. One-off (the next time that time "
             "comes round, or on a date) or repeating on days.",
             {"time": {"type": "string", "description": "24-hour time, like 07:00"},
              "date": {"type": "string", "description": "A date like 2026-11-20 for a one-off on that day; empty "
                       "for the next time that time comes round, or for a repeating alarm"},
              "days": {"type": "string", "description": "For a repeating alarm: daily, weekdays, weekends, or days "
                       "like 'mon, wed, fri'; empty for a one-off"},
              "label": {"type": "string", "description": "What it's for, e.g. 'gym'; empty if not said"}}),
        tool("list_timers", "List the timers and alarms set, with their ids, when they ring and what's left."),
        tool("cancel_timer", "Cancel a timer or alarm by its id (from list_timers).", {"id": TEXT}),
        tool("stop_ringing", "Stop the timer or alarm that's ringing now."),
        tool("snooze", "Snooze the timer or alarm that's ringing now.",
             {"minutes": {"type": "integer", "description": "How long, if said (e.g. 'snooze for 2 minutes'); "
                          "otherwise 9"}}),
        tool("next_trains", "The next NJ Transit trains for a trip, live: departure times, tracks and delays. Leave "
             "both stations empty for the user's saved trip, and set reverse for the way back.",
             {"from_station": {"type": "string", "description": "Station name or code, or empty"},
              "to_station": {"type": "string", "description": "Station name or code, or empty"},
              "reverse": {"type": "boolean", "description": "True for the saved trip's way back"}}),
        tool("remember", "Remember a lasting fact about the user, only when asked.", {"fact": TEXT}),
        tool("forget", "Forget remembered facts containing these words, when asked.", {"about": TEXT}),
    ]

# Cut a tool result to a sensible size for one answer
def trimmed(text):
    return text if len(text) <= MAX_TOOL_RESULT else text[:MAX_TOOL_RESULT] + " [cut short]"

# Runs John's tools against the rest of Nestor
class JohnTools:
    # Keep the announcer (for speaking and volume), the settings, and the NJ Transit account (None without one)
    def __init__(self, announcer, settings, rail=None):
        self.announcer = announcer
        self.settings = settings
        self.rail = rail
        self.definitions = tool_definitions() + [WEB_SEARCH]

    # The line John sees before what the user said: the time, the sleeping period, whether the phone is home,
    # and (at the start of a conversation) what John remembers
    def context(self, now, first_turn):
        asleep = self.announcer.quiet_hours.is_quiet(now)
        phone = "home" if datebook.phone_home(now) else "not home"
        line = (f"[Now: {now.strftime('%A, %B')} {now.day}, {now.year}, {spoken_clock(now.time())}. "
                f"Sleeping period: {'on' if asleep else 'off'}. Phone: {phone}.")
        ringing = timers.scheduler.ringing if timers.scheduler else None

        # Say what's ringing, so "stop" or "turn it off" makes sense
        if ringing:
            line += f" Ringing now: {timers.ring_line(ringing, now)}"

        # Memories only need saying once per conversation
        if first_turn:
            facts = [known["fact"] for known in memory.read_memory()]
            line += " You remember: " + ("; ".join(facts) if facts else "nothing yet") + "."
        return line + "]"

    # Run one tool call from Claude and return its tool_result block (errors go back as is_error results)
    def run(self, block):
        # A failing tool tells Claude what went wrong instead of stopping the answer
        try:
            result = self.call(block.name, block.input)
            return {"type": "tool_result", "tool_use_id": block.id, "content": trimmed(result)}
        except Exception as error:
            return {"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {error}", "is_error": True}

    # Do what a tool asks and return the result as text
    def call(self, name, arguments):
        # Each tool by name
        if name == "datebook_overview":
            return self.datebook_overview()
        elif name == "datebook_action":
            item_id = arguments["id"].strip()
            item = int(item_id) if item_id.isdigit() else item_id
            queued = datebook.add_action(arguments["action"], item or None, arguments["text"] or None)
            return json.dumps({"queued": queued, "phone_home": datebook.phone_home()})
        elif name == "add_reminder":
            moment = datetime.datetime.fromisoformat(arguments["at"])

            # Reminders must be in the future
            if moment <= datetime.datetime.now():
                raise ValueError("that time has already passed")
            reminder = reminders.add_reminder(arguments["text"], moment)
            return json.dumps({"added": reminder, "said_as": spoken_moment(moment),
                               "during_sleeping_period": self.announcer.quiet_hours.is_quiet(moment)})
        elif name == "list_reminders":
            return json.dumps(reminders.reminders_data())
        elif name == "delete_reminder":
            return json.dumps({"deleted": reminders.delete_reminder(arguments["id"])})
        elif name == "start_my_day":
            routines.start_my_day(self.announcer, self.settings)
            return "Started the day: the briefing is being read aloud now. Reply with nothing."
        elif name == "goodnight":
            briefing = routines.goodnight(self.announcer, self.settings)
            return f"Goodnight done: quiet until {briefing['quiet_until']}. Reply with nothing."
        elif name == "briefing":
            return build_briefing(self.settings, day=arguments["day"])["text"]
        elif name == "set_volume":
            return self.set_volume(arguments["target"], arguments["percent"])
        elif name == "recent_alerts":
            count = max(1, min(10, arguments["count"]))
            return json.dumps(list(reversed(read_history()))[:count])
        elif name == "set_timer":
            return json.dumps({"set": timers.add_timer(arguments["minutes"] * 60, arguments["label"])})
        elif name == "set_alarm":
            alarm = timers.add_alarm(arguments["time"], arguments["label"], arguments["date"], arguments["days"])
            return json.dumps({"set": alarm, "next_rings": timers.next_ring(alarm, datetime.datetime.now()).isoformat(
                timespec="minutes")})
        elif name == "list_timers":
            return json.dumps(timers.timers_data())
        elif name == "cancel_timer":
            return json.dumps({"cancelled": timers.cancel(arguments["id"])})
        elif name in ("stop_ringing", "snooze"):
            ringing = timers.scheduler.stop() if name == "stop_ringing" else timers.scheduler.snooze(
                arguments["minutes"] or timers.SNOOZE_MINUTES)
            return json.dumps({"done": ringing, "note": "" if ringing else "nothing was ringing"})
        elif name == "next_trains":
            return self.next_trains(arguments["from_station"], arguments["to_station"], arguments["reverse"])
        elif name == "remember":
            return json.dumps({"remembered": memory.remember(arguments["fact"])})
        elif name == "forget":
            return json.dumps({"forgotten": memory.forget(arguments["about"])})
        else:
            raise ValueError(f"no tool called {name}")

    # Datebook's copy, cut down to what answers need
    def datebook_overview(self):
        state = datebook.read_state()
        overview = {part: state.get(part) for part in ("events", "waiting", "lists", "notes", "reminders", "trip")}
        overview.update(phone_home=state["phone_home"], copy_is_old=state["stale"], updated=state.get("updated"),
                        has_calendar=state["has_calendar"], connected=state["connected"])
        return json.dumps(overview)

    # Change the speaker's own volume, or the volume Nestor speaks at (until Nestor restarts)
    def set_volume(self, target, percent):
        level = max(0, min(100, percent)) / 100

        # The speaker's volume, or just announcements
        if target == "speaker":
            self.announcer.speaker.set_volume(level)
        else:
            self.announcer.announce_volume = level
        return json.dumps({"target": target, "percent": round(level * 100)})

    # The next trains for the saved trip (Datebook's, else train_from and train_to in config.yaml) or the stations
    # asked about, from NJ Transit's live board
    def next_trains(self, from_station, to_station, reverse):
        # Live trains need the NJ Transit account
        if not self.rail:
            raise RuntimeError("no NJ Transit account: add NJT_USERNAME and NJT_PASSWORD to .env")
        stations = self.rail.stations()
        trip = datebook.read_state().get("trip") or {}
        from_code = trains.find_station(stations, from_station) if from_station.strip() else (
            trip.get("from") or self.settings.get("train_from", ""))
        to_code = trains.find_station(stations, to_station) if to_station.strip() else (
            trip.get("to") or self.settings.get("train_to", ""))

        # Both ends are needed, and reverse swaps them
        if not from_code or not to_code:
            raise ValueError("no trip: name both stations, or set train_from and train_to in config.yaml")
        elif reverse:
            from_code, to_code = to_code, from_code
        next_trains = trains.trains_to(self.rail.departures(from_code), to_code)
        return json.dumps({"from": stations.get(from_code, from_code), "to": stations.get(to_code, to_code),
                           "trains": [{"departs": train["departs"].strftime("%H:%M") if train["departs"] else "",
                                       "track": train["track"], "minutes_late": train["minutes_late"],
                                       "status": train["status"], "said_as": trains.spoken_train(train, spoken_clock),
                                       "arrives": trains.arrival_at(train, to_code).strftime("%H:%M")}
                                      for train in next_trains]})
