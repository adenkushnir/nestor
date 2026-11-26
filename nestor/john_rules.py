# John's rules: Aden's own list of how John talks and answers, on top of his built-in style. Each rule has a category,
# its words, an on/off switch, and optionally when it applies (clock times, days, or Nestor's own times like quiet
# hours or the phone being away). Kept in data/john_rules.json, edited from Claude Desktop through the connector,
# checked for clashes by Claude, and shown as an organized page for an artifact.
import datetime
import html
import logging
import os
import re
from nestor.config import DATA_DIR
from nestor.storage import read_json
from nestor.storage import write_json
RULES_PATH = os.path.join(DATA_DIR, "john_rules.json")
CATEGORIES = ("Personality", "How he answers", "Words and names", "Topics", "Never do")
NESTOR_TIMES = {"quiet_hours": "during quiet hours", "awake_hours": "outside quiet hours",
                "phone_away": "while the phone is away", "phone_home": "while the phone is home"}
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}
DAY_GROUPS = {"weekdays": DAYS[:5], "weekends": DAYS[5:], "every day": DAYS}
CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
MAX_RULES = 100
log = logging.getLogger(__name__)

# Every rule, in the order they were added
def read_rules():
    return read_json(RULES_PATH, [])

# Save the whole list
def save_rules(rules):
    write_json(RULES_PATH, rules[:MAX_RULES])

# A clock time as "22:00" (empty when there's none); raises ValueError when it can't be read
def clock_time(text):
    text = str(text or "").strip()

    # Empty, or HH:MM in 24-hour time
    if not text:
        return ""
    match = CLOCK.match(text)

    # Only real clock times
    if not match:
        raise ValueError(f"{text!r} isn't a time; use HH:MM, like 22:00")
    return f"{int(match.group(1)):02d}:{match.group(2)}"

# Days as a list of mon..sun from words like "weekends", "sat, sun" or "mon tue" (empty for any day)
def day_list(text):
    words = str(text or "").lower().replace(",", " ").split()
    days = []

    # Each word: a group of days or one day
    for word in words:
        # Groups, or a day by its first three letters
        if word in ("weekdays", "weekends"):
            days.extend(DAY_GROUPS[word])
        elif word[:3] in DAYS:
            days.append(word[:3])
        else:
            raise ValueError(f"{word!r} isn't a day; use mon..sun, weekdays or weekends")
    return [day for day in DAYS if day in days]

# Check a rule's fields and tidy them; raises ValueError when something's wrong
def checked(category, text, starts="", ends="", nestor_time="", days=""):
    # A rule needs a known category and words
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {', '.join(CATEGORIES)}")
    elif not str(text or "").strip():
        raise ValueError("a rule needs its words")
    elif nestor_time and nestor_time not in NESTOR_TIMES:
        raise ValueError(f"nestor_time must be one of {', '.join(NESTOR_TIMES)} (or empty)")
    starts, ends = clock_time(starts), clock_time(ends)

    # Clock times come in pairs
    if bool(starts) != bool(ends):
        raise ValueError("give both from and to for a time of day, like 22:00 to 07:00")
    return {"category": category, "text": str(text).strip(), "from": starts, "to": ends,
            "nestor_time": nestor_time or "", "days": day_list(days)}

# Add a rule (switched on) and return it
def add_rule(category, text, starts="", ends="", nestor_time="", days="", now=None):
    now = now or datetime.datetime.now()
    rules = read_rules()
    rule = dict(checked(category, text, starts, ends, nestor_time, days), id=max([0] + [r["id"] for r in rules]) + 1,
                on=True, added=now.isoformat(timespec="seconds"), changed=now.isoformat(timespec="seconds"))
    save_rules(rules + [rule])
    return rule

# Find a rule by its number; raises ValueError when there's none
def find_rule(rules, rule_id):
    found = next((rule for rule in rules if rule["id"] == int(rule_id)), None)

    # A rule that doesn't exist says so
    if found is None:
        raise ValueError(f"there's no rule {rule_id}")
    return found

# Change a rule's words, category or times (empty fields keep what it has) and return it
def edit_rule(rule_id, category="", text="", starts="", ends="", nestor_time="", days="", now=None):
    now = now or datetime.datetime.now()
    rules = read_rules()
    rule = find_rule(rules, rule_id)
    days_now = " ".join(rule["days"])
    fields = checked(category or rule["category"], text or rule["text"], starts or rule["from"], ends or rule["to"],
                     nestor_time or rule["nestor_time"], days or days_now)
    rule.update(fields, changed=now.isoformat(timespec="seconds"))
    save_rules(rules)
    return rule

# Clear when a rule applies, so it applies all the time; returns it
def clear_times(rule_id, now=None):
    rules = read_rules()
    rule = find_rule(rules, rule_id)
    rule.update({"from": "", "to": "", "nestor_time": "", "days": [],
                 "changed": (now or datetime.datetime.now()).isoformat(timespec="seconds")})
    save_rules(rules)
    return rule

# Switch a rule on or off and return it
def switch_rule(rule_id, on, now=None):
    rules = read_rules()
    rule = find_rule(rules, rule_id)
    rule.update(on=bool(on), changed=(now or datetime.datetime.now()).isoformat(timespec="seconds"))
    save_rules(rules)
    return rule

# Remove a rule and return what it was
def remove_rule(rule_id):
    rules = read_rules()
    rule = find_rule(rules, rule_id)
    save_rules([kept for kept in rules if kept is not rule])
    return rule

# Is a time of day inside a from-to window (which can run past midnight, like 22:00 to 07:00)
def in_window(moment, starts, ends):
    now = moment.strftime("%H:%M")
    return starts <= now < ends if starts <= ends else now >= starts or now < ends

# Does a rule apply right now: switched on, on one of its days, inside its clock times and its Nestor time
def applies(rule, now, quiet, phone_home):
    nestor_time = rule.get("nestor_time") or ""
    nestor_ok = {"": True, "quiet_hours": quiet, "awake_hours": not quiet, "phone_away": not phone_home,
                 "phone_home": phone_home}.get(nestor_time, True)
    day_ok = not rule.get("days") or DAYS[now.weekday()] in rule["days"]
    clock_ok = not rule.get("from") or in_window(now, rule["from"], rule["to"])
    return bool(rule.get("on")) and nestor_ok and day_ok and clock_ok

# The rules that apply right now, as the lines added to John's instructions ("" when none do)
def prompt_block(now, quiet, phone_home):
    active = [rule for rule in read_rules() if applies(rule, now, quiet, phone_home)]

    # Nothing applies: nothing to add
    if not active:
        return ""
    lines = [f"- ({rule['category']}) {rule['text']}" for rule in active]
    return ("\n\nAden's own rules for you, which win over the style above wherever they differ:\n" +
            "\n".join(lines))

# When a rule applies, in words: "22:00–07:00 · weekends · during quiet hours", or "always"
def when_text(rule):
    parts = []

    # Its clock times, its days and its Nestor time, when it has them
    if rule.get("from"):
        parts.append(f"{rule['from']}–{rule['to']}")

    if rule.get("days"):
        days = rule["days"]
        group = next((name for name, members in DAY_GROUPS.items() if list(members) == days), None)
        parts.append(group or ", ".join(DAY_NAMES[day] for day in days))

    if rule.get("nestor_time"):
        parts.append(NESTOR_TIMES[rule["nestor_time"]])
    return " · ".join(parts) or "always"

# Ask Claude which rules a new (or changed) rule clashes with; returns their numbers (empty when none, or when Claude
# can't be asked)
def clashes(client, model, text, rules, skip_id=None):
    others = [rule for rule in rules if rule["id"] != skip_id]

    # Nothing to clash with
    if not others or client is None:
        return []
    listed = "\n".join(f"{rule['id']}: {rule['text']} ({when_text(rule)})" for rule in others)
    question = (f"These are rules for a voice assistant:\n{listed}\n\nNew rule: {text}\n\nWhich of the rules above "
                "contradict the new rule (they can't both be followed at the same time)? Reply with only their "
                "numbers separated by commas, or the word none.")

    # A failed check lets the rule through
    try:
        reply = client.messages.create(model=model, max_tokens=50, messages=[{"role": "user", "content": question}])
        answer = "".join(block.text for block in reply.content if block.type == "text")
    except Exception as error:
        log.warning("John's rules couldn't be checked for clashes: %s", error)
        return []
    known = {rule["id"] for rule in others}
    return [int(number) for number in re.findall(r"\d+", answer) if int(number) in known]

# John's built-in style in a few lines, for the top of the page (his full instructions are in brain.py)
BUILT_IN = ("Warm, friendly noir: smooth and unhurried, a kind private eye who's seen it all",
            "Calls you sir, boss or chief now and then, never with a comma before it",
            "One or two short sentences, said aloud: no lists, links or extras",
            "Answers only what was asked",
            "Reads misheard words as what you most likely said")
# Each category's colour and a small line icon (inline SVG paths, drawn in the colour)
STYLE = {"Personality": ("#5adbea", "M12 3a5 5 0 1 1 0 10a5 5 0 0 1 0-10zM4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"),
         "How he answers": ("#52c0f6", "M4 5h16v10H9l-5 4z"),
         "Words and names": ("#8bdc5c", "M7 7h4v4H8l-2 4M15 7h4v4h-3l-2 4"),
         "Topics": ("#ffbe6a", "M3 12l9-9h8v8l-9 9zM16 7h.01"),
         "Never do": ("#ff8a8a", "M12 3a9 9 0 1 1 0 18a9 9 0 0 1 0-18zM6 6l12 12")}

# When a rule applies, as chips: its clock times (blue), days (green) and Nestor time (amber); one "Always" chip when
# it has none
def chips_html(rule):
    chips = []

    # Each part it has, in its own colour
    if rule.get("from"):
        chips.append(f'<span class="chip clock">{rule["from"]}–{rule["to"]}</span>')

    if rule.get("days"):
        days = rule["days"]
        group = next((name for name, members in DAY_GROUPS.items() if list(members) == days), None)
        chips.append(f'<span class="chip days">{html.escape((group or ", ".join(DAY_NAMES[d] for d in days)).title())}'
                     "</span>")

    if rule.get("nestor_time"):
        chips.append(f'<span class="chip nestor">{html.escape(NESTOR_TIMES[rule["nestor_time"]].capitalize())}</span>')
    return "".join(chips) or '<span class="chip always">Always</span>'

# The rules as one organized page for an artifact, in the wall's Frutiger Aero look: a night-sky page with a glossy
# header, John's built-in style, counts, filters by category (and to hide switched-off rules), then a glass card per
# category with its colour and icon, each rule with a numbered gel badge, its words, time chips and an On/Off switch
def page_html(rules, now=None):
    now = now or datetime.datetime.now()
    on = sum(1 for rule in rules if rule["on"])
    timed = sum(1 for rule in rules if rule.get("from") or rule.get("days") or rule.get("nestor_time"))
    sections = []
    filters = ['<button class="filter lit" data-show="all">All</button>']

    # One card per category that has rules, and a filter for it
    for category in CATEGORIES:
        members = [rule for rule in rules if rule["category"] == category]

        # Skip empty categories
        if not members:
            continue
        colour, icon = STYLE[category]
        key = category.lower().replace(" ", "-")
        filters.append(f'<button class="filter" data-show="{key}" style="--c:{colour}">{html.escape(category)}'
                       f"<b>{len(members)}</b></button>")
        rows = "".join(
            f'<li class="{"on" if rule["on"] else "off"}"><span class="n">{rule["id"]}</span><div class="t">'
            f'<p>{html.escape(rule["text"])}</p><div class="chips">{chips_html(rule)}</div></div>'
            f'<span class="sw" title="Ask Claude to switch it"><i></i>{"On" if rule["on"] else "Off"}</span></li>'
            for rule in members)
        sections.append(f'<section data-cat="{key}" style="--c:{colour}"><h2><svg viewBox="0 0 24 24" '
                        f'aria-hidden="true"><path d="{icon}"/></svg>{html.escape(category)}<em>{len(members)}</em>'
                        f"</h2><ul>{rows}</ul></section>")
    body = "".join(sections) or ('<p class="empty">No rules yet. Tell Claude a rule for John, like “never call me '
                                 'chief”, to add the first one.</p>')
    built_in = "".join(f"<li>{html.escape(line)}</li>" for line in BUILT_IN)
    stamp = f"{now.strftime('%b')} {now.day}, {now.hour % 12 or 12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"
    return """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>John's rules</title><style>
:root{color-scheme:dark}*{box-sizing:border-box;min-width:0}
body{margin:0;color:#eef5ff;font:17px/1.5 "Segoe UI",system-ui,sans-serif;min-height:100vh;overflow-x:clip;
background:radial-gradient(900px 500px at 85% -10%,rgba(90,219,234,.35),transparent 60%),
radial-gradient(700px 500px at -10% 30%,rgba(82,192,246,.25),transparent 60%),
linear-gradient(180deg,#071a33 0%,#0d3358 45%,#12546f 100%)}
main{max-width:880px;margin:0 auto;padding:32px max(18px,4vw) 48px}
.hero{position:relative;overflow:hidden;border-radius:26px;padding:26px 26px 22px;border:1px solid rgba(255,255,255,
.35);
background:linear-gradient(180deg,rgba(255,255,255,.28),rgba(255,255,255,0) 48%),linear-gradient(135deg,#2fa7ea,
#0e86c4 55%,#0a98b0);
box-shadow:0 18px 40px rgba(0,0,0,.35),inset 0 1px 0 rgba(255,255,255,.6)}
.hero:after{content:"";position:absolute;top:0;left:-40%;width:30%;height:100%;transform:skewX(-20deg);
background:linear-gradient(90deg,transparent,rgba(255,255,255,.28),transparent);animation:shine 7s ease-in-out infinite}
@keyframes shine{0%,70%{left:-40%}100%{left:130%}}
@media (prefers-reduced-motion:reduce){.hero:after{animation:none;display:none}}
h1{margin:0;font-size:clamp(34px,6vw,48px);line-height:1.05;letter-spacing:-.02em}
.tag{margin:6px 0 0;font-size:16px;opacity:.95}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}
.stat{background:rgba(0,40,80,.35);border:1px solid rgba(255,255,255,.3);border-radius:999px;padding:5px 14px;
font-weight:600;font-size:15px}
.style{margin:18px 0;border-radius:20px;padding:16px 20px;background:rgba(16,44,72,.72);border:1px solid rgba(255,255,
255,.18)}
.style h2{margin:0 0 8px;font-size:13px;letter-spacing:.9px;text-transform:uppercase;color:#d6e8ff}
.style ul{margin:0;padding-left:20px;color:#d6e8ff}.style li{margin:3px 0}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 16px}
.filter{--c:#9fd8ff;min-height:44px;padding:0 16px;border-radius:22px;border:1px solid rgba(255,255,255,.25);
cursor:pointer;
background:rgba(16,44,72,.7);color:#eef5ff;font:inherit;font-size:15px;font-weight:600;display:inline-flex;gap:8px;
align-items:center}
.filter b{background:var(--c);color:#06243c;border-radius:999px;padding:0 8px;font-size:13px}
.filter.lit{background:linear-gradient(180deg,#52c0f6,#178de0);border-color:#9fd8ff}
.filter:focus-visible{outline:3px solid #ffbe6a;outline-offset:2px}
.hideoff{margin-left:auto}
section{--c:#9fd8ff;position:relative;margin:0 0 16px;border-radius:22px;padding:18px 20px 8px;overflow:hidden;
background:linear-gradient(180deg,rgba(255,255,255,.1),rgba(255,255,255,0) 40%),rgba(16,44,72,.72);
border:1px solid rgba(255,255,255,.18);box-shadow:0 10px 26px rgba(0,0,0,.25)}
section:before{content:"";position:absolute;left:0;right:0;top:0;height:4px;background:var(--c)}
h2{display:flex;align-items:center;gap:10px;margin:0 0 6px;font-size:20px}
h2 svg{width:26px;height:26px;fill:none;stroke:var(--c);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
h2 em{font-style:normal;font-size:14px;color:#b4c6e0;font-weight:400}
ul.r{list-style:none}section ul{list-style:none;margin:0;padding:0}
section li{display:grid;grid-template-columns:auto 1fr auto;gap:16px;align-items:center;padding:14px 0;
border-top:1px solid rgba(255,255,255,.1)}
section li:first-child{border-top:0}
.n{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;font-weight:700;color:#06243c;
background:radial-gradient(circle at 35% 30%,#fff 0,var(--c) 45%,color-mix(in srgb,var(--c) 70%,#000) 100%);
box-shadow:0 3px 10px rgba(0,0,0,.35)}
.t p{margin:0;font-size:19px;font-weight:600}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.chip{font-size:13px;font-weight:600;border-radius:999px;padding:2px 10px;border:1px solid}
.chip.clock{color:#9fd8ff;border-color:rgba(159,216,255,.6);background:rgba(82,192,246,.15)}
.chip.days{color:#b8f08f;border-color:rgba(139,220,92,.6);background:rgba(139,220,92,.13)}
.chip.nestor{color:#ffd59a;border-color:rgba(255,190,106,.6);background:rgba(255,190,106,.13)}
.chip.always{color:#d6e8ff;border-color:rgba(214,232,255,.4);background:rgba(214,232,255,.08)}
.sw{display:inline-flex;align-items:center;gap:8px;font-size:14px;font-weight:700;color:#d6e8ff}
.sw i{width:44px;height:24px;border-radius:12px;position:relative;background:rgba(255,255,255,.18);
border:1px solid rgba(255,255,255,.3)}
.sw i:after{content:"";position:absolute;top:2px;left:2px;width:18px;height:18px;border-radius:50%;background:#eef5ff;
box-shadow:0 1px 3px rgba(0,0,0,.4)}
li.on .sw i{background:linear-gradient(180deg,#8bdc5c,#46a926);border-color:#b8f08f}
li.on .sw i:after{left:22px}
li.off{opacity:.5}li.off .t p{text-decoration:line-through;text-decoration-color:rgba(255,255,255,.4)}
body.hiding li.off{display:none}
.empty{color:#b4c6e0;font-size:18px}
.foot{color:#b4c6e0;font-size:15px;margin-top:22px}
@media (max-width:560px){section li{grid-template-columns:auto 1fr}.sw{grid-column:2}}
</style></head><body><main>
<div class="hero"><h1>John's rules</h1><p class="tag">How John talks and answers, on top of his built-in style.</p>
<div class="stats"><span class="stat">""" + f"{on} on" + """</span><span class="stat">""" + \
        f"{len(rules) - on} off" + """</span><span class="stat">""" + f"{timed} timed" + \
        """</span><span class="stat">Updated """ + stamp + """</span></div></div>
<div class="style"><h2>His built-in style</h2><ul>""" + built_in + """</ul></div>
<div class="filters">""" + "".join(filters) + """
<button class="filter hideoff" id="hideoff">Hide switched off</button></div>
""" + body + """<p class="foot">To change a rule, ask Claude: “turn off rule 3”, “make rule 2 weekends only”,
“add a rule:
never mention the weather unless I ask”.</p></main><script>
{const show=(key)=>{document.querySelectorAll('section').forEach((s)=>{s.hidden=key!=='all'&&s.dataset.cat!==key});
document.querySelectorAll('[data-show]').forEach((b)=>b.classList.toggle('lit',b.dataset.show===key))};
document.querySelectorAll('[data-show]').forEach((b)=>b.addEventListener('click',()=>show(b.dataset.show)));
const off=document.getElementById('hideoff');
off.addEventListener('click',()=>{const on=document.body.classList.toggle('hiding');
off.classList.toggle('lit',on);off.textContent=on?'Show switched off':'Hide switched off'})}
</script></body></html>"""
