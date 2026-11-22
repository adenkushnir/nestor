// The wall's cards: the big clock and the weather line, the Next card (or "Nothing else today"), and the rail with
// Later today, the trains, men's foil and now playing. Filled from Nestor's /wall/state every 20 seconds.
const REFRESH_SECONDS = 20;
let data = null;
let fetchedAt = 0;

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
  return rows.map((row) => `<div class="ev"><div class="t">${esc(row.time)}</div><div class="n">${esc(row.title)}` +
    `${row.tag ? `<span class="chip">${esc(row.tag)}</span>` : ""}</div></div>`).join("");
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
    `${data.next ? nextCard(data.next) : freeCard()}</div><div class="stack">${rail}</div></div>`;
  showClock();
}

// The clock, date and the music's progress, every second (only the text changes, not the cards)
function showClock() {
  const now = new Date();
  const clock = document.getElementById("clock");

  // The cards haven't been drawn yet
  if (!clock) {
    return;
  }
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
refresh();
setInterval(refresh, REFRESH_SECONDS * 1000);
setInterval(showClock, 1000);
