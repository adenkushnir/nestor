# Understands times the way people write them: "18:00", "6:30pm", "noon", "in 20m", "tomorrow 9am", "fri 7pm",
# "12/3 2pm" (month/day, like Datebook) and "dec 3 2pm"; and finds such a time at the start or end of a reminder
import datetime
import re
WEEKDAYS = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2, "thu": 3, "thur": 3,
            "thurs": 3, "thursday": 3, "fri": 4, "friday": 4, "sat": 5, "saturday": 5, "sun": 6, "sunday": 6}
MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
          "oct": 10, "nov": 11, "dec": 12}
UNIT_MINUTES = {"m": 1, "min": 1, "mins": 1, "minute": 1, "minutes": 1, "h": 60, "hr": 60, "hrs": 60, "hour": 60,
                "hours": 60, "d": 1440, "day": 1440, "days": 1440}
CLOCK_PATTERN = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm|a|p)?$")
OFFSET_PART = re.compile(r"(\d+)\s*([a-z]+)")
MAX_WHEN_WORDS = 5

# Read a clock time like "18:00", "6pm", "6:30 pm" or "noon"; None if it isn't one
def parse_clock(text):
    text = text.strip().lower().replace(".", "")

    # The two times with names of their own
    if text in ("noon", "midday"):
        return datetime.time(12, 0)
    elif text == "midnight":
        return datetime.time(0, 0)
    match = CLOCK_PATTERN.match(text)

    # A bare number like "6" is too vague: it needs minutes or am/pm
    if not match or (match.group(2) is None and match.group(3) is None):
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2) or 0)
    half = (match.group(3) or "")[:1]

    # Check the numbers make sense for the clock used
    if minutes > 59 or (half and not 1 <= hours <= 12) or hours > 23:
        return None

    # Convert the 12-hour clock to 24 hours
    if half == "p" and hours < 12:
        hours += 12
    elif half == "a" and hours == 12:
        hours = 0
    return datetime.time(hours, minutes)

# Read a day like "today", "tomorrow", "fri", "12/3", "2026-12-03", "dec 3" or "3 dec"; None if it isn't one
def parse_day(text, today):
    words = text.split()

    # Relative days and weekdays
    if text == "today":
        return today
    elif text == "tomorrow":
        return today + datetime.timedelta(days=1)
    elif text in WEEKDAYS:
        return today + datetime.timedelta(days=(WEEKDAYS[text] - today.weekday()) % 7)
    month = day = year = None

    # Numeric dates: ISO first, then month/day with an optional year
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        year, month, day = (int(part) for part in text.split("-"))
    elif re.fullmatch(r"\d{1,2}/\d{1,2}(/\d{2,4})?", text):
        parts = [int(part) for part in text.split("/")]
        month, day = parts[0], parts[1]
        year = (parts[2] + 2000 if parts[2] < 100 else parts[2]) if len(parts) == 3 else None
    elif len(words) == 2 and words[0][:4].rstrip(".") in MONTHS and words[1].isdigit():
        month, day = MONTHS[words[0][:4].rstrip(".")], int(words[1])
    elif len(words) == 2 and words[1][:4].rstrip(".") in MONTHS and words[0].isdigit():
        month, day = MONTHS[words[1][:4].rstrip(".")], int(words[0])

    # Full month names ("december") are looked up by their first three letters
    if month is None and len(words) == 2:
        for first, second in ((words[0], words[1]), (words[1], words[0])):
            # Name and number in either order
            if first[:3] in MONTHS and second.isdigit():
                month, day = MONTHS[first[:3]], int(second)

    # Not a date at all
    if month is None:
        return None

    # A date without a year means the next time it comes round
    try:
        date = datetime.date(year or today.year, month, day)
    except ValueError:
        return None
    return date.replace(year=date.year + 1) if year is None and date < today else date

# Read an offset like "20m", "20 minutes", "1h30m" or "1 hour 30 minutes" and add it to now; None if it isn't one
def parse_offset(text, now):
    text = text.replace(" and ", " ")
    parts = OFFSET_PART.findall(text)

    # The whole phrase must be number-and-unit pairs
    if not parts or OFFSET_PART.sub("", text).strip():
        return None
    total_minutes = 0

    # Add up each part
    for amount, unit in parts:
        # Unknown units make it not an offset
        if unit not in UNIT_MINUTES:
            return None
        total_minutes += int(amount) * UNIT_MINUTES[unit]
    return now + datetime.timedelta(minutes=total_minutes) if total_minutes > 0 else None

# Turn a phrase like "tomorrow at 9am" into a future datetime; None if it isn't a time or is in the past
def parse_when(phrase, now=None):
    now = now or datetime.datetime.now()
    text = " ".join(phrase.lower().replace(",", " ").split())
    text = re.sub(r"^(at|on) ", "", text).replace(" at ", " ")
    words = text.split()

    # "in 20 minutes" style offsets
    if words and words[0] == "in":
        return parse_offset(" ".join(words[1:]), now)
    clock = parse_clock(text)

    # A clock time alone means today if it's still ahead, otherwise tomorrow
    if clock:
        moment = datetime.datetime.combine(now.date(), clock)
        return moment if moment > now else moment + datetime.timedelta(days=1)

    # A day of one or two words, then a clock time
    for day_word_count in (1, 2):
        date = parse_day(" ".join(words[:day_word_count]), now.date())
        clock = parse_clock(" ".join(words[day_word_count:]))

        # Both parts must be there
        if date and clock:
            moment = datetime.datetime.combine(date, clock)

            # A weekday whose time has already passed today means next week
            if moment <= now and words[0] in WEEKDAYS:
                moment += datetime.timedelta(days=7)
            return moment if moment > now else None
    return None

# Split reminder words into (when, what), with the time at the start ("18:00 call mum") or end ("call mum at 6pm");
# returns (None, text) when no time is found
def split_when_and_text(words, now=None):
    # Longest time phrase first, at the start and then at the end
    for word_count in range(min(MAX_WHEN_WORDS, len(words)), 0, -1):
        moment = parse_when(" ".join(words[:word_count]), now)

        # Time at the start, possibly with its day at the end ("9:30am standup tomorrow")
        if moment:
            rest = words[word_count:]
            clock = parse_clock(" ".join(words[:word_count]).replace("at ", ""))
            day = parse_day(rest[-1].lower(), (now or datetime.datetime.now()).date()) if rest else None

            # Join the clock time to the day named at the end
            if clock and day and len(rest) > 1:
                day_moment = parse_when(f"{rest[-1]} {' '.join(words[:word_count])}", now)
                return day_moment or moment, " ".join(rest[:-1]).strip()
            return moment, " ".join(rest).strip()
        moment = parse_when(" ".join(words[-word_count:]), now)

        # Time at the end
        if moment and word_count < len(words):
            return moment, " ".join(words[:-word_count]).strip()
    return None, " ".join(words)
