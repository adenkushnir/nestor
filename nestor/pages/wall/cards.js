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
  return `<div class="row" style="margin-top:8px">` +
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
  return `<div class="glass pad"><span class="label">Men's foil</span><div style="margin-top:3px">${rows}</div></div>`;
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
    '<div class="chips" id="chips"></div></div>';
  const later = `<div class="glass pad stack${below > 1 ? " tight" : ""}" ` +
    'style="flex:1;gap:2px;min-height:0;overflow:hidden">' +
    `<div class="row"><span class="label">Later today</span>${header}</div>${laterRows()}</div>`;
  const rail = later + (data.trains ? trainCard() : "") + (data.foil.length ? foilCard() : "") +
    (data.music ? musicCard() : "");
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

// Ask Nestor for everything the wall shows, then redraw the cards and tell the scene the weather
async function refresh() {
  // A failed check keeps what's showing until the next one
  try {
    const reply = await fetch("/wall/state", {cache: "no-store", signal: AbortSignal.timeout(15000)});

    // Only a good answer replaces what's showing
    if (reply.ok) {
      data = await reply.json();
      fetchedAt = Date.now();
      setScene(data.weather);
      renderCards();
    }
  } catch (error) {
    console.warn("The wall couldn't reach Nestor:", error);
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

// Taps on the wall: Stop and Snooze, and a touch on the night clock shows the full wall for 30 seconds
function onTap(event) {
  const button = event.target.closest("[data-ring]");

  // A ring button, or the night clock
  if (button) {
    ringButton(button.dataset.ring);
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

    // A ring starting, ending or changing redraws the left card
    if (data && JSON.stringify(before.ringing) !== JSON.stringify(live.ringing)) {
      renderCards();
    }
    showClock();
  });
}
document.getElementById("screen").addEventListener("click", onTap);
refresh();
followLive();
setInterval(refresh, REFRESH_SECONDS * 1000);
setInterval(showClock, 1000);
