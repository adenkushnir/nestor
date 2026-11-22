// The wall's cards: the big clock and the weather line with the timer chips, the Next card (or "Nothing else today",
// or the ringing card with Stop and Snooze), the rail with Later today, the trains, men's foil and now playing, and
// the night clock in the sleeping period. Filled from Nestor's /wall/state every 20 seconds and its live feed.
const REFRESH_SECONDS = 20;
const WAKE_SECONDS = 30;  // Touching the night clock shows the full wall this long
const TOAST_SECONDS = 2.6;
const NIGHT_COLOUR = "255, 176, 90";  // dim amber
const NIGHT_BRIGHT = 0.22;
let data = null;
let fetchedAt = 0;
let live = {john: "idle", ringing: null, sleeping: false, alarm: null, timers: []};
let wokeUntil = 0;
let toastUntil = 0;
const BIG_SECONDS = 30;  // A bigger screen closes by itself after this long
const BIG_TITLES = {days: "Your week", weather: "Weather · next 12 hours", fencing: "Men's foil this week"};
const BIG_VIEWS = {week: "days", weather: "weather", fencing: "fencing"};  // John's names for the screens
const big = {open: null, closesAt: 0};
let bigSeen = null;  // The last bigger-screen request from John that was acted on
const OFFLINE_AFTER = 2;  // Updates missed in a row before the wall shows it's reconnecting
let missed = 0;
let offline = false;

// Make text safe to put in the page (titles and places come from your calendar)
function esc(text) {
  return String(text ?? "").replace(/[&<>"']/g, (character) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
    "'": "&#39;"})[character]);
}

// A small train or plane picture for the Next card's status line
function statusIcon(kind) {
  // A plane for flights, a train front otherwise
  if (kind === "flight") {
    return '<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">' +
      '<path d="M2 13l9-2V5a1.5 1.5 0 0 1 3 0v6l8 2v2l-8-1v4l2 1.5V21l-3.5-1L9 21v-1.5L11 18v-4l-9 1z" ' +
      'fill="currentColor"/></svg>';
  }
  return '<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">' +
    '<rect x="5" y="3" width="14" height="14" rx="3" fill="none" stroke="currentColor" stroke-width="2"/>' +
    '<path d="M5 10h14M9 21l-2 0 2-4M15 21l2 0-2-4" ' +
    'stroke="currentColor" stroke-width="2" fill="none"/><circle cx="9" cy="13.5" r="1.2" fill="currentColor"/>' +
    '<circle cx="15" cy="13.5" r="1.2" fill="currentColor"/></svg>';
}

// The weather line by the clock: temperature and words, and "Rain from 4 PM" when rain is coming
function weatherLine() {
  const weather = data && data.weather;

  // No weather yet (or no home location): leave the line out
  if (!weather || weather.temp === null) {
    return "";
  }
  const rain = weather.rain_from ? `<span class="rainnote">· ${esc(weather.rain_from)}</span>` : "";
  return `<div class="row tapme" data-open="weather" style="margin-top:8px">` +
    `<span style="font-size:26px;font-weight:600">${esc(weather.temp)}°</span>` +
    `<span style="font-size:15px">${esc(weather.words)}</span>${rain}</div>`;
}

// The Next card: the start time big on the left with the countdown, the details on the right; orange when it's time
// to go
function nextCard(next) {
  const late = next.status && next.status.late ? " late" : "";
  const status = next.status ? `<div class="nstatus${late}">${statusIcon(next.status.kind)}` +
    `<span>${esc(next.status.text)}</span></div>` : "";
  const place = next.place ? `<div>${esc(next.place)}</div>` : "";
  const leave = next.leave ? `<div class="nleave">${esc(next.leave)}</div>` : "";
  const bring = next.bring ? `<div>Bring: ${esc(next.bring)}</div>` : "";
  return `<div class="gelcard${next.urgent ? " urgent" : ""} nextsplit"><div class="nbig"><div class="ntime">` +
    `${esc(next.time)}<small>${esc(next.ampm)}</small></div><div class="nsoon">${esc(next.soon)}</div></div>` +
    `<div class="ndetail"><div class="ntitle">${esc(next.title)}</div>${place}${leave}${bring}${status}</div></div>`;
}

// The free-time card that takes the Next card's place when nothing else is on today
function freeCard() {
  const evening = new Date().getHours() >= 16;
  return `<div class="gelcard freecard"><div class="freetitle">Nothing else today</div>` +
    `<div class="freesub">${evening ? "Enjoy the evening." : "Enjoy your day."}</div></div>`;
}

// Later today's rows (only what's still to come, without second lines, as the bigger text needs)
function laterRows() {
  const rows = data.later || [];

  // Nothing left: say so
  if (!rows.length) {
    return '<div class="small muted" style="padding:4px 6px">All done for today</div>';
  }
  return rows.map((row) => `<div class="ev"><div class="t">${esc(row.time)}</div><div class="n">` +
    `<span>${esc(row.title)}</span>${row.tag ? `<span class="chip">${esc(row.tag)}</span>` : ""}</div></div>`).join("");
}

// The train board: the one that just left faded, the next ones with track and status (late in orange, cancelled in red
// and struck through), or a line when there are no more tonight
function trainCard() {
  const board = data.trains;
  const title = board.title.replace(/ Penn Station| Station/g, "");

  // An empty board means the trains are done for the night
  if (!board.rows.length) {
    return `<div class="glass pad"><span class="label">Trains · ${esc(title)}</span><div class="notrains">` +
      "No more trains tonight</div></div>";
  }
  const rows = board.rows.map((train) => {
    const row = {gone: " gone", cancelled: " cancelled"}[train.state] || "";
    const colour = {late: "warn", cancelled: "bad"}[train.state] || (train.track === "Tr —" ? "muted" : "");
    return `<div class="train${row}"><span class="tt">${esc(train.time)}</span><span class="muted">` +
      `${esc(train.track)}</span><span class="${colour}">${esc(train.status)}</span></div>`;
  }).join("");
  return `<div class="glass pad"><span class="label">Trains · ${esc(title)}</span>` +
    `<div style="margin-top:3px">${rows}</div></div>`;
}

// The men's foil card: this week's schedule, with LIVE for an event on now (no Watch or Results buttons)
function foilCard() {
  const rows = data.foil.map((event) => `<div class="frow"><span class="fday${event.live ? " live" : ""}">` +
    `${esc(event.day)}</span><span class="grow fname"><b>${esc(event.name)}</b>` +
    `<span class="muted"> · ${esc(event.where)}</span></span>` +
    `<span class="muted">${esc(event.time)}</span></div>`).join("");
  return `<div class="glass pad tapme" data-open="fencing"><span class="label">Men's foil</span>` +
    `<div style="margin-top:3px">${rows}</div></div>`;
}

// The now-playing card: album art, song, artist and album, and how far it's got (show only, no controls)
function musicCard() {
  const music = data.music;
  const art = music.art ? ` style="background-image:url('${esc(music.art)}')"` : "";
  return `<div class="glass pad row"><div class="art"${art}></div><div class="grow"><div class="small" ` +
    `style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(music.track)}</div>` +
    `<div class="small muted" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">` +
    `${esc(music.artists.join(", "))}${music.album ? ` · ${esc(music.album)}` : ""}</div>` +
    `<div class="bar" style="margin-top:5px"><i id="musicBar"></i></div></div></div>`;
}

// A countdown's time left as 4:32 (or 1:04:32 past an hour)
function clockLeft(seconds) {
  const whole = Math.max(0, Math.ceil(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor(whole % 3600 / 60);
  const rest = String(whole % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

// One timer chip: a ring that fills up as the time runs out, the name and the time left
function chipHtml(timer, now) {
  const left = (Date.parse(timer.ends) - now) / 1000;
  const share = timer.total ? Math.min(1, Math.max(0, 1 - left / timer.total)) : 0;
  const around = 2 * Math.PI * 7;
  return '<span class="tchip"><svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">' +
    '<circle cx="9" cy="9" r="7" fill="none" stroke="rgba(255,255,255,0.3)" stroke-width="2.5"/>' +
    `<circle cx="9" cy="9" r="7" fill="none" stroke="#5adbea" stroke-width="2.5" ` +
    `stroke-dasharray="${around * share} ${around}" transform="rotate(-90 9 9)"/></svg>` +
    `<b>${esc(timer.label)}</b>${clockLeft(left)}</span>`;
}

// The ringing card over the left side: what's ringing, with Stop and Snooze side by side
function ringCard() {
  return `<div class="gelcard urgent ringcard"><div class="label" style="background:rgba(80,30,0,0.35)">` +
    `${esc(live.ringing.sub)}</div><div class="rtitle">${esc(live.ringing.title)}</div><div class="rbtns">` +
    '<button class="gel bigstop" type="button" data-ring="stop">Stop</button>' +
    '<button class="ghost snooze" type="button" data-ring="snooze">Snooze 9 min</button></div></div>';
}

// Show a short message at the bottom of the screen after a tap
function showToast(message) {
  const toast = document.getElementById("wallToast");
  toast.textContent = message;
  toast.classList.add("show");
  toastUntil = Date.now() + TOAST_SECONDS * 1000;
}

// Is the night clock showing: in the sleeping period, unless a touch woke the wall for a while
function nightShowing() {
  return live.sleeping && Date.now() > wokeUntil;
}

// The night clock: black, with the time and the first alarm in dim amber (brighter while something rings, with its
// card in the corner)
function drawNight() {
  const night = document.getElementById("night");
  const showing = nightShowing();
  const now = new Date();
  night.classList.toggle("on", showing);
  wall.night = showing;

  // Nothing to draw while it's hidden
  if (!showing) {
    return;
  }
  const bright = live.ringing ? Math.max(NIGHT_BRIGHT, 0.5) : NIGHT_BRIGHT;
  const alarm = live.alarm ? `<div class="nline">Alarm ${esc(live.alarm)}</div>` : "";
  night.innerHTML = `<div class="nclock" style="color:rgba(${NIGHT_COLOUR}, ${bright})">` +
    `${now.getHours() % 12 || 12}:${String(now.getMinutes()).padStart(2, "0")}` +
    `<small>${now.getHours() < 12 ? "AM" : "PM"}</small>${alarm}</div>` +
    (live.ringing ? `<div class="nring">${ringCard()}</div>` : "");
}

// Draw the clock area, the Next card and the rail from the latest data
function renderCards() {
  const header = data.updated ? `<span class="hcount stalehead">${esc(data.updated)}</span>` :
    data.counts ? `<span class="hcount">${esc(data.counts)}</span>` : "";
  const below = (data.foil.length ? 1 : 0) + (data.music ? 1 : 0);
  const clock = '<div class="shadow"><div class="row" style="align-items:flex-end;gap:10px">' +
    '<span id="clock" style="font-size:112px;font-weight:300;line-height:0.85;letter-spacing:-2px"></span>' +
    '<span id="ampm" style="font-size:24px;padding-bottom:8px"></span></div>' +
    `<div id="date" style="font-size:21px;margin-top:8px"></div>${weatherLine()}` +
    (offline ? '<div class="offbadge">Reconnecting to Nestor…</div>' : "") +
    '<div class="chips" id="chips"></div></div>';
  const later = `<div class="glass pad stack tapme${below > 1 ? " tight" : ""}" data-open="days" ` +
    'style="flex:1;gap:2px;min-height:0;overflow:hidden">' +
    `<div class="row"><span class="label">Later today</span>${header}</div>${laterRows()}</div>`;
  const rail = later + (data.trains ? trainCard() : "") + (data.foil.length ? foilCard() : "") +
    (data.music ? musicCard() : "");
  document.getElementById("cards").classList.toggle("offline", offline);
  document.getElementById("cards").innerHTML = '<div style="position:absolute;inset:10px;display:grid;' +
    'grid-template-columns:1.4fr 1fr;gap:10px">' +
    `<div class="stack" style="justify-content:space-between;padding:6px 6px 0">${clock}` +
    `${live.ringing ? ringCard() : data.next ? nextCard(data.next) : freeCard()}</div>` +
    `<div class="stack">${rail}</div></div>`;
  showClock();
}

// The clock, date, timer chips, the music's progress and the night clock, every second (only these change, not the
// cards)
function showClock() {
  const now = new Date();
  const clock = document.getElementById("clock");
  drawNight();

  // The toast goes after its time
  if (toastUntil && Date.now() > toastUntil) {
    document.getElementById("wallToast").classList.remove("show");
    toastUntil = 0;
  }

  drawBig();

  // The cards haven't been drawn yet
  if (!clock) {
    return;
  }
  document.getElementById("chips").innerHTML = live.timers.map((timer) => chipHtml(timer, now.getTime())).join("");
  clock.textContent = `${now.getHours() % 12 || 12}:${String(now.getMinutes()).padStart(2, "0")}`;
  document.getElementById("ampm").textContent = now.getHours() < 12 ? "AM" : "PM";
  document.getElementById("date").textContent = now.toLocaleDateString("en-US", {weekday: "long", month: "long",
    day: "numeric"});
  const bar = document.getElementById("musicBar");

  // The music's bar moves on between updates
  if (bar && data.music.duration_ms) {
    const progress = data.music.progress_ms + (Date.now() - fetchedAt);
    bar.style.width = `${Math.min(100, 100 * progress / data.music.duration_ms)}%`;
  }
}

// Note whether Nestor answers: after two missed updates the cards dim with a "Reconnecting" badge, and they come back
// with the first answer
function setOffline(missedOne) {
  missed = missedOne ? missed + 1 : 0;
  const now = missed >= OFFLINE_AFTER;

  // Only a change redraws the cards (there must be something to show)
  if (now !== offline) {
    offline = now;

    // Redraw what's there, dimmed or not
    if (data) {
      renderCards();
    }
  }
}

// Ask Nestor for everything the wall shows, then redraw the cards and tell the scene the weather and the chip's heat
async function refresh() {
  // A failed check keeps what's showing until the next one
  try {
    const reply = await fetch("/wall/state", {cache: "no-store", signal: AbortSignal.timeout(15000)});

    // Only a good answer replaces what's showing
    if (reply.ok) {
      const first = !data;
      data = await reply.json();
      fetchedAt = Date.now();
      missed = 0;
      offline = false;
      setScene(data.weather);
      chipHeat(data.chip_temp);
      renderCards();

      // ?open=days (or weather, fencing) opens a bigger screen when the page loads, for checking it
      if (first && new URLSearchParams(location.search).get("open")) {
        openBig(new URLSearchParams(location.search).get("open"));
      }
    } else {
      setOffline(true);
    }
  } catch (error) {
    console.warn("The wall couldn't reach Nestor:", error);
    setOffline(true);
  }
}
// Tell Nestor to stop or snooze what's ringing, then say what happened
async function ringButton(what) {
  const alarmAtNight = live.ringing && live.ringing.kind === "alarm" && live.sleeping;

  // A failed call says so rather than nothing
  try {
    const reply = await fetch(`/timers/${what}`, {method: "POST", signal: AbortSignal.timeout(10000)});

    // Say what happened: snoozed, stopped, or the day started
    if (!reply.ok) {
      showToast("Nestor didn't answer; try again");
    } else if (what === "snooze") {
      showToast("Snoozed for 9 minutes");
    } else {
      showToast(alarmAtNight ? "Good morning: stopping the alarm started your day" : "Stopped");
    }
  } catch (error) {
    showToast("Nestor didn't answer; try again");
  }
}

// The week screen: today in full (what's done faded), then the next 6 days
function daysView() {
  const week = data.big.week;
  const today = week.today.map((row) => `<div class="bev${row.past ? " past" : ""}"><span class="bt">` +
    `${esc(row.time)}</span><span class="grow"><b>${esc(row.title)}</b>` +
    `${row.tag ? `<span class="chip">${esc(row.tag)}</span>` : ""}` +
    `${row.place ? `<span class="muted"> · ${esc(row.place)}</span>` : ""}` +
    `${row.leave ? `<div class="bleave">${esc(row.leave)}</div>` : ""}` +
    `${row.bring ? `<div class="muted">Bring: ${esc(row.bring)}</div>` : ""}</span></div>`).join("");
  const days = week.days.map((day) => `<div class="bday"><span class="bdname">${esc(day.day)}</span>` +
    `<span class="grow">${day.items.length ? day.items.map(esc).join("<br>") : '<span class="muted">Nothing on</span>'}` +
    "</span></div>").join("");
  return `<div class="bcols"><div><span class="label">Today · ${esc(week.today_name)}</span>` +
    `${today || '<div class="muted" style="margin-top:6px">Nothing today</div>'}</div>` +
    `<div><span class="label">Coming up</span>${days}</div></div>`;
}

// The weather screen in words: the big rain line, the line under it, and the parts of the day
function weatherView() {
  const weather = data.big.weather;

  // The forecast may not have come in yet
  if (!weather) {
    return '<div class="sbanner">The forecast isn\'t in yet</div>';
  }
  const parts = weather.parts.map((part) => `<div class="spart"><span class="sname">${esc(part.name)}</span>` +
    `<span class="sspan">${esc(part.span)}</span><span class="stemps">${esc(part.temps)}</span>` +
    `<span class="swords">${esc(part.words)}</span><span class="lbar"><i style="width:${Number(part.rain) || 0}%">` +
    "</i></span></div>").join("");
  return `<div class="sbanner">${esc(weather.banner)}</div><div class="ssub">${esc(weather.under)}</div>` +
    `<div class="sparts">${parts}</div>`;
}

// The men's foil screen: this week's events by day, LIVE with today's stage (just the schedule)
function fencingView() {
  const days = data.big.fencing;

  // A week with nothing on says so
  if (!days.length) {
    return '<div class="sbanner">No men\'s foil this week</div>';
  }
  return days.map((day) => `<div class="fbday"><span class="label">${esc(day.day)}</span>` + day.events.map((event) =>
    `<div class="fbev">${event.live ? '<span class="fday live">LIVE</span>' :
      `<span class="fbtime">${esc(event.time)}</span>`}<span class="grow"><b>${esc(event.name)}</b>` +
    `<div class="muted">${esc([event.where, event.days].filter(Boolean).join(" · "))}` +
    `${event.live && event.stage ? ` · now: ${esc(event.stage)}` : ""}</div></span></div>`).join("") +
    "</div>").join("");
}

// Open a bigger screen over the wall, closing by itself after 30 seconds; the hare steps aside to the big tree
function openBig(kind) {
  // Only screens there's data for
  if (!data || !BIG_TITLES[kind]) {
    return;
  }
  big.open = kind;
  big.closesAt = Date.now() + BIG_SECONDS * 1000;
  wall.bigOpen = true;
  renderBig();
}

// Close the bigger screen and go back to the wall
function closeBig() {
  big.open = null;
  wall.bigOpen = false;
  renderBig();
}

// Draw the bigger screen, or nothing when none is open
function renderBig() {
  const holder = document.getElementById("big");
  holder.classList.toggle("open", Boolean(big.open));

  // Nothing open: empty
  if (!big.open) {
    holder.innerHTML = "";
    return;
  }
  const views = {days: daysView, weather: weatherView, fencing: fencingView};
  holder.innerHTML = `<div class="bigcard glass"><div class="bighead"><span class="bigtitle">${BIG_TITLES[big.open]}` +
    '</span><span class="grow"></span><span class="bigclose" id="bigCountdown"></span>' +
    '<button class="ghost" type="button" data-big="close">Close</button></div>' +
    `<div class="bigbody">${views[big.open]()}</div></div>`;
  drawBig();
}

// Count down to closing by itself, and close when the time is up
function drawBig() {
  // Only while a screen is open
  if (!big.open) {
    return;
  }
  const left = Math.ceil((big.closesAt - Date.now()) / 1000);

  // Time's up: back to the wall
  if (left <= 0) {
    closeBig();
    return;
  }
  document.getElementById("bigCountdown").textContent = `Closes in ${left} s`;
}

// Taps on the wall: Stop and Snooze, the bigger screens' cards and Close, and a touch on the night clock shows the full
// wall for 30 seconds
function onTap(event) {
  const button = event.target.closest("[data-ring]");
  const close = event.target.closest("[data-big]");
  const open = event.target.closest("[data-open]");

  // A ring button, Close, a card that opens its screen, or the night clock
  if (button) {
    ringButton(button.dataset.ring);
  } else if (close) {
    closeBig();
  } else if (open && !big.open) {
    openBig(open.dataset.open);
  } else if (event.target.closest("#night")) {
    wokeUntil = Date.now() + WAKE_SECONDS * 1000;
    drawNight();
  }
}

// Follow Nestor's live feed: John's state, what's ringing, the sleeping period and the timers (the browser reconnects
// by itself if it drops)
function followLive() {
  const feed = new EventSource("/wall/live");
  feed.addEventListener("live", (event) => {
    const before = live;
    live = JSON.parse(event.data);
    wall.john = live.john;
    wall.ringing = Boolean(live.ringing);
    wall.sleeping = live.sleeping;
    const request = live.big;

    // A ring starting, ending or changing redraws the left card (and a new ring closes a bigger screen)
    if (data && JSON.stringify(before.ringing) !== JSON.stringify(live.ringing)) {
      renderCards();

      // Stop and Snooze must be reachable
      if (live.ringing) {
        closeBig();
      }
    }

    // A new ask from John opens or closes a bigger screen (one asked before the page loaded is only noted)
    if (bigSeen === null) {
      bigSeen = request ? request.id : 0;
    } else if (request && request.id !== bigSeen) {
      bigSeen = request.id;

      // Close, or open the screen asked for
      if (request.view === "close") {
        closeBig();
      } else {
        openBig(BIG_VIEWS[request.view]);
      }
    }
    showClock();
  });
}
document.getElementById("screen").addEventListener("click", onTap);
refresh();
followLive();
setInterval(refresh, REFRESH_SECONDS * 1000);
setInterval(showClock, 1000);
