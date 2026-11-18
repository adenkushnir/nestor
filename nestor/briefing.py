# The briefing: the day ahead ("start my day": greeting and date, weather, sunrise and sunset, reminders, what Datebook
# has due or waiting, and GitHub news from overnight) or a preview of tomorrow ("goodnight").
# Built as data first (JSON for the API, the phone page and the wall display), then turned into spoken lines.
import datetime
import logging
from nestor import weather
from nestor.announcer import read_history
from nestor.datebook import datebook_day
from nestor.datebook import read_moment
from nestor.reminders import todays_reminders
from nestor.spoken import speakable
from nestor.spoken import spoken_clock
from nestor.spoken import spoken_day
from nestor.spoken import spoken_hhmm
from nestor.spoken import spoken_list
OVERNIGHT_HOURS = 16
MAX_GITHUB_ITEMS = 3
MAX_WAITING_ITEMS = 3
MAX_EVENTS = 5
ONLINE_PLACES = ("http", "www.", "zoom", "meet.google", "teams.microsoft")  # Places not worth reading out
DAYS = ("today", "tomorrow")
log = logging.getLogger(__name__)

# "Good morning", "Good afternoon" or "Good evening" for the time of day
def greeting(now):
    # Morning until noon, afternoon until 6
    if now.hour < 12:
        return "Good morning"
    elif now.hour < 18:
        return "Good afternoon"
    else:
        return "Good evening"

# Texts of the GitHub alerts from the last 16 hours, oldest first
def overnight_github(now):
    since = (now - datetime.timedelta(hours=OVERNIGHT_HOURS)).isoformat(timespec="seconds")
    return [entry["text"] for entry in read_history() if entry["source"] == "github" and entry["time"] >= since]

# Build the briefing data for "today" (the day ahead) or "tomorrow" (the goodnight preview), with its spoken lines
# and text at the end
def build_briefing(settings, now=None, day="today"):
    now = now or datetime.datetime.now()
    days_ahead = DAYS.index(day)
    date = now.date() + datetime.timedelta(days=days_ahead)
    data = {"generated": now.isoformat(timespec="seconds"), "day": day, "date": date.isoformat(),
            "greeting": greeting(now), "weather": None, "weather_problem": None, "reminders": todays_reminders(date),
            "datebook": None, "github": overnight_github(now) if day == "today" else []}
    location = str(settings.get("home_location") or "").strip()

    # Weather needs a home location and the internet; without them the briefing goes on without it
    if not location:
        data["weather_problem"] = "home_location isn't set in config.yaml"
    else:
        # A failed lookup is noted, not fatal
        try:
            data["weather"] = weather.forecast(location, settings.get("temperature_unit", "fahrenheit"), days_ahead)
        except Exception as error:
            log.warning("No weather for the briefing: %s", error)
            data["weather_problem"] = str(error)

    # Datebook's part is left out, not fatal, if its snapshot can't be read
    try:
        data["datebook"] = datebook_day(date, now, settings.get("class_names"))
    except Exception as error:
        log.warning("No Datebook part for the briefing: %s", error)
    data["lines"] = spoken_lines(data, now)
    data["text"] = " ".join(data["lines"])
    return data

# Turn the briefing data into the sentences Nestor says
def spoken_lines(data, now):
    date = datetime.date.fromisoformat(data["date"])

    # The day ahead opens with a greeting, the preview with tomorrow's date
    if data["day"] == "today":
        lines = [f"{data['greeting']}. It's {date.strftime('%A')}, {date.strftime('%B')} {date.day}."]
    else:
        lines = [f"Tomorrow is {date.strftime('%A')}, {date.strftime('%B')} {date.day}."]
    lines += weather_lines(data["weather"], now)
    lines += event_lines(data["datebook"], now, data["day"])
    lines += reminder_lines(data)
    lines += datebook_lines(data["datebook"], now, data["day"])

    # GitHub news is only for the morning
    if data["day"] == "today":
        lines += github_lines(data["github"])
    return lines

# The weather: right now and today's high and low, or tomorrow's outlook; rain only when it's likely
def weather_lines(forecast, now):
    # No weather, nothing to say
    if not forecast:
        return []

    # Today has the temperature now and the sun times; tomorrow just its outlook
    if forecast["now"] is not None:
        lines = [f"It's {forecast['now']} degrees and {forecast['conditions']}, with a high of {forecast['high']} "
                 f"and a low of {forecast['low']}."]
    else:
        lines = [f"Tomorrow looks {forecast['conditions']}, with a high of {forecast['high']} and a low of "
                 f"{forecast['low']}."]

    # Rain only gets a mention when it's likely
    if forecast["rain_from"]:
        lines.append(f"Rain is likely from {spoken_hhmm(forecast['rain_from'])}, so bring an umbrella.")

    # The sun times belong to today's briefing
    if forecast["now"] is not None:
        clock_now = now.strftime("%H:%M")
        sunrise_tense = "was" if clock_now >= forecast["sunrise"] else "is"
        sunset_tense = "was" if clock_now >= forecast["sunset"] else "is"
        lines.append(f"Sunrise {sunrise_tense} at {spoken_hhmm(forecast['sunrise'])}, and sunset {sunset_tense} at "
                     f"{spoken_hhmm(forecast['sunset'])}.")
    return lines

# The short name of an event's place worth saying ("Luigi's" from "Luigi's, 12 Main St"), or "" for none, an online
# link, or a place the title already names
def spoken_place(event):
    place = str(event["place"]).split(",")[0].strip()

    # Leave out empty places, links and places already in the title
    if not place or any(word in place.lower() for word in ONLINE_PLACES) or place.lower() in event["title"].lower():
        return ""
    return place

# What to call an event, plan or due item: its spoken title, and its class if it has one ("Final Group Presentation
# for Leadership")
def spoken_name(item):
    title = item.get("title_spoken") or item["title"]
    return f"{title} for {item['class']}" if item.get("class") else title

# An event said aloud: "CS lecture at 10 AM", "lunch with Sam at 12:30 PM at Luigi's", "Soccer tournament all day"
def spoken_event(event):
    place = spoken_place(event)

    # All-day events have no time of day
    if event["all_day"]:
        words = f"{spoken_name(event)} all day"
    else:
        words = f"{spoken_name(event)} at {spoken_clock(read_moment(event['start']).time())}"
    return f"{words} at {place}" if place else words

# True once a timed event is over (all-day events last the whole day)
def finished(event, now):
    # All-day events aren't over until the day is
    if event["all_day"]:
        return False
    return (read_moment(event["end"]) or read_moment(event["start"])) <= now

# "Leave by 8:35 AM, a 20 minute drive" for an event Datebook planned a leave-by for ("" without one)
def spoken_leave_by(event):
    leave_by = read_moment(event["leave_by"])

    # Only events with a leave-by
    if not leave_by:
        return ""
    travel = speakable(str(event["travel"])).rstrip(".") if event["travel"] else ""
    return f"leave by {spoken_clock(leave_by.time())}" + (f", a {travel}" if travel else "")

# What to bring, as a list: "cleats, $20" becomes "cleats and $20"
def spoken_bring(bring):
    return spoken_list([item.strip() for item in str(bring).split(",") if item.strip()])

# The calendar from Datebook: today's events still to come (the first few) and the next leave-by, or tomorrow's
# first event with its leave-by and what to bring
def event_lines(datebook, now, day):
    # Nothing from Datebook's calendar yet, nothing to say
    if not datebook or not datebook["connected"] or not datebook["has_calendar"]:
        return []
    events = datebook["events"]

    # A day with nothing on it
    if not events:
        return [f"Nothing on your calendar {day}."]

    # Today: what's left of the day, then when to leave for the next thing
    if day == "today":
        remaining = [event for event in events if not finished(event, now)]

        # The whole day may already be over
        if not remaining:
            return ["That's everything on your calendar for today."]
        names = [spoken_event(event) for event in remaining[:MAX_EVENTS]]

        # Say how many more there are beyond the first few
        if len(remaining) > MAX_EVENTS:
            names.append(f"{len(remaining) - MAX_EVENTS} more")
        intro = "On your calendar today" if len(remaining) == len(events) else "Still on your calendar today"
        lines = [f"{intro}: {spoken_list(names)}."]
        next_leave = [event for event in remaining if read_moment(event["leave_by"]) and
                      read_moment(event["leave_by"]) > now]

        # The next leave-by Datebook planned
        if next_leave:
            lines.append(f"For {next_leave[0]['title']}, {spoken_leave_by(next_leave[0])}.")
        return lines
    timed = [event for event in events if not event["all_day"]]
    first = timed[0] if timed else events[0]
    first_words = spoken_event(first) + (f", {spoken_leave_by(first)}" if spoken_leave_by(first) else "")

    # One event is the whole day; more get a count first
    if len(events) == 1:
        lines = [f"On your calendar tomorrow: {first_words}."]
    else:
        lines = [f"You have {len(events)} things on your calendar tomorrow. First up: {first_words}."]

    # What to bring for each event that needs something
    for event in events:
        # Only events with a bring list
        if spoken_bring(event["bring"]):
            lines.append(f"Bring {spoken_bring(event['bring'])} for {spoken_name(event)}.")
    return lines

# Nestor's and Datebook's reminders for the day together, timed ones in order and untimed ones last
def reminder_lines(data):
    datebook_reminders = data["datebook"]["reminders"] if data["datebook"] else []
    timed = sorted((reminder["time"], reminder["text"]) for reminder in data["reminders"] + datebook_reminders
                   if reminder["time"])
    items = [f"{text} at {spoken_hhmm(clock)}" for clock, text in timed]
    items += [reminder["text"] for reminder in datebook_reminders if not reminder["time"]]

    # Say them, or that there are none
    if items:
        return [f"{data['day'].capitalize()}: {spoken_list(items)}."]
    return [f"No reminders {data['day']}."]

# A waiting plan said aloud: its title and when, e.g. "dinner at Luigi's Friday at 7 PM"
def spoken_plan(plan, today):
    start = read_moment(plan.get("start"))

    # Plans without a readable start are just their title
    if not start:
        return spoken_name(plan)
    when = spoken_day(start.date(), today)

    # All-day plans and plans with only a date have no time of day
    if "T" in str(plan["start"]) and not plan.get("all_day"):
        when += f" at {spoken_clock(start.time())}"
    return f"{spoken_name(plan)} {when}"

# Everything due on a day in one sentence, grouped by class: "Due today: the electric bill; for Movie VFX, Unit 11
# Discussion Forum and Unit 11 Homework; for Leadership, Final Group Presentation."
def due_line(due, day):
    loose = [item["title_spoken"] for item in due if not item["class"]]
    by_class = {}

    # Gather each class's items, in the order they come
    for item in due:
        # Bills and other items without a class were gathered above
        if item["class"]:
            by_class.setdefault(item["class"], []).append(item["title_spoken"])
    parts = ([spoken_list(loose)] if loose else []) + [f"for {name}, {spoken_list(titles)}"
                                                        for name, titles in by_class.items()]
    return f"Due {day}: " + "; ".join(parts) + "."

# What Datebook adds: bills and assignments due that day, and the plans waiting on the phone to be added
def datebook_lines(datebook, now, day):
    # Nothing from Datebook yet, nothing to say
    if not datebook or not datebook["connected"]:
        return []
    lines = []

    # Bills and assignments due that day, grouped by class
    if datebook["due"]:
        lines.append(due_line(datebook["due"], day))
    waiting = datebook["waiting"]

    # Plans waiting to be added, the soonest few by name
    if waiting:
        count_words = "1 plan" if len(waiting) == 1 else f"{len(waiting)} plans"
        names = [spoken_plan(plan, now.date()) for plan in waiting[:MAX_WAITING_ITEMS]]

        # Say how many more there are beyond the first few
        if len(waiting) > MAX_WAITING_ITEMS:
            names.append(f"{len(waiting) - MAX_WAITING_ITEMS} more")
        lines.append(f"Datebook has {count_words} waiting for you: {spoken_list(names)}.")

    # Warn when the phone hasn't been home for a while, so the calendar and plans may be old
    if datebook["stale"] and (waiting or datebook["events"]):
        updated = datetime.datetime.fromisoformat(datebook["updated"]).date()
        lines.append(f"Datebook last checked in on {spoken_day(updated, now.date())}, so this may be out of date.")
    return lines

# GitHub news from overnight, a few items at most
def github_lines(github_news):
    # Say there's nothing, everything, or the latest few and how many more
    if not github_news:
        return ["Nothing new on GitHub overnight."]
    elif len(github_news) <= MAX_GITHUB_ITEMS:
        return ["Overnight on GitHub: " + " ".join(github_news)]
    else:
        extra_count = len(github_news) - MAX_GITHUB_ITEMS
        return ["Overnight on GitHub: " + " ".join(github_news[-MAX_GITHUB_ITEMS:]) + f" And {extra_count} more."]
