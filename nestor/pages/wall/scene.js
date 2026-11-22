// The wall's scene: the rooftop garden in the light of the day and the weather, the hare who walks it (John's face),
// the falling weather and the gentle motions. Ported from the approved final mockup with every pick fixed.
// The weathers (scene pictures) and what the hare wears in each
const WEATHERS = [
  {id: "clear", picture: "clear", outfit: "sun", fair: true},
  {id: "partly", picture: "partly", outfit: "", fair: true},
  {id: "overcast", picture: "overcast", outfit: "", fair: true},
  {id: "rain", picture: "wet", outfit: "umbrella", fair: false},
  {id: "storm", picture: "storm", outfit: "umbrella", fair: false},
  {id: "snow", picture: "snow", outfit: "snow", fair: false},
  {id: "fog", picture: "fog", outfit: "fog", fair: false}
];
// His three spots: where his feet go and how tall he is there
const SPOTS = [
  {id: "tree", x: 212, y: 300, tall: 72},
  {id: "pool", x: 302, y: 285, tall: 70},
  {id: "pergola", x: 362, y: 288, tall: 50}
];
const IDLES = ["watch", "tie", "look"];
const WALK_FRAMES = ["cycle2-1", "cycle2-2", "cycle2-3", "cycle2-4", "cycle2-5", "cycle2-6", "cycle2-7", "cycle2-8"];
// The hare's poses: each cut-out's size at the standing height, and where his eyes are (fractions)
const POSES = {standing: 230, poses: {
  "umbrella-watch": {"w": 144, "h": 262, "eyes": [[0.432, 0.31], [0.517, 0.304]]},
  "snow-watch": {"w": 65, "h": 230, "eyes": [[0.29, 0.265], [0.477, 0.261]]},
  "fog-watch": {"w": 65, "h": 230, "eyes": [[0.328, 0.263], [0.497, 0.259]]},
  "stand": {"w": 65, "h": 230, "eyes": [[0.287, 0.252], [0.513, 0.252]]},
  "watch": {"w": 65, "h": 230, "eyes": [[0.302, 0.264], [0.5, 0.26]]},
  "tie": {"w": 65, "h": 230, "eyes": [[0.362, 0.259], [0.508, 0.252]]},
  "look": {"w": 70, "h": 230, "eyes": [[0.395, 0.255], [0.486, 0.256]]},
  "umbrella": {"w": 144, "h": 262, "eyes": [[0.422, 0.305], [0.523, 0.299]]},
  "sunglasses": {"w": 65, "h": 230, "eyes": [[0.273, 0.264], [0.498, 0.255]]},
  "snow": {"w": 65, "h": 230, "eyes": [[0.316, 0.26], [0.514, 0.254]]},
  "fog": {"w": 65, "h": 230, "eyes": [[0.355, 0.257], [0.521, 0.254]]},
  "listening": {"w": 65, "h": 230, "eyes": [[0.334, 0.259], [0.51, 0.255]]},
  "thinking": {"w": 68, "h": 230, "eyes": [[0.334, 0.259], [0.51, 0.255]]},
  "dozing": {"w": 72, "h": 160, "eyes": []},
  "sun-watch": {"w": 65, "h": 230, "eyes": [[0.302, 0.264], [0.5, 0.26]]},
  "sun-tie": {"w": 65, "h": 230, "eyes": [[0.301, 0.266], [0.519, 0.251]]},
  "sun-look": {"w": 70, "h": 230, "eyes": [[0.421, 0.257], [0.517, 0.257]]},
  "sun-listening": {"w": 65, "h": 230, "eyes": [[0.265, 0.265], [0.537, 0.257]]},
  "sun-thinking": {"w": 68, "h": 230, "eyes": [[0.424, 0.257], [0.554, 0.251]]},
  "umbrella-listening": {"w": 144, "h": 262, "eyes": [[0.396, 0.305], [0.514, 0.297]]},
  "umbrella-thinking": {"w": 144, "h": 262, "eyes": [[0.396, 0.305], [0.514, 0.297]]},
  "snow-listening": {"w": 64, "h": 230, "eyes": [[0.28, 0.256], [0.502, 0.252]]},
  "snow-thinking": {"w": 64, "h": 230, "eyes": [[0.28, 0.256], [0.502, 0.252]]},
  "fog-listening": {"w": 65, "h": 230, "eyes": [[0.328, 0.26], [0.561, 0.249]]},
  "fog-thinking": {"w": 65, "h": 230, "eyes": [[0.328, 0.26], [0.561, 0.249]]},
  "dozing-umbrella": {"w": 114, "h": 183, "eyes": []},
  "dozing-snow": {"w": 115, "h": 166, "eyes": []},
  "dozing-fog": {"w": 112, "h": 158, "eyes": []},
  "cycle2-1": {"w": 91, "h": 226, "eyes": [[0.612, 0.261], [0.821, 0.26]]},
  "cycle2-2": {"w": 67, "h": 227, "eyes": [[0.612, 0.261], [0.821, 0.26]]},
  "cycle2-3": {"w": 56, "h": 227, "eyes": [[0.589, 0.261], [0.851, 0.264]]},
  "cycle2-4": {"w": 72, "h": 227, "eyes": [[0.649, 0.259], [0.856, 0.263]]},
  "cycle2-5": {"w": 91, "h": 225, "eyes": [[0.649, 0.259], [0.856, 0.263]]},
  "cycle2-6": {"w": 64, "h": 227, "eyes": [[0.649, 0.259], [0.856, 0.263]]},
  "cycle2-7": {"w": 77, "h": 226, "eyes": [[0.54, 0.26], [0.707, 0.261]]},
  "cycle2-8": {"w": 87, "h": 228, "eyes": [[0.54, 0.26], [0.707, 0.261]]},
  "sun-cycle2-1": {"w": 92, "h": 226, "eyes": [[0.546, 0.264], [0.709, 0.266]]},
  "sun-cycle2-2": {"w": 67, "h": 227, "eyes": [[0.579, 0.267], [0.76, 0.266]]},
  "sun-cycle2-3": {"w": 57, "h": 227, "eyes": [[0.579, 0.267], [0.76, 0.266]]},
  "sun-cycle2-4": {"w": 72, "h": 227, "eyes": [[0.656, 0.263], [0.856, 0.263]]},
  "sun-cycle2-5": {"w": 91, "h": 225, "eyes": [[0.656, 0.263], [0.856, 0.263]]},
  "sun-cycle2-6": {"w": 64, "h": 227, "eyes": [[0.656, 0.263], [0.856, 0.263]]},
  "sun-cycle2-7": {"w": 77, "h": 226, "eyes": [[0.546, 0.264], [0.709, 0.266]]},
  "sun-cycle2-8": {"w": 87, "h": 228, "eyes": [[0.546, 0.264], [0.709, 0.266]]}
}};
// Each light's glass tint and the tint the hare takes on
const LIGHT_LOOKS = {
  morning: {tint: "46, 40, 58", hare: "rgba(255, 180, 140, 0.18)"},
  midday: {tint: "16, 44, 72", hare: ""},
  golden: {tint: "62, 44, 28", hare: "rgba(255, 160, 60, 0.22)"},
  sunset: {tint: "64, 30, 50", hare: "rgba(220, 90, 140, 0.28)"},
  bluehour: {tint: "26, 30, 70", hare: "rgba(50, 50, 150, 0.38)"},
  night: {tint: "12, 24, 54", hare: "rgba(20, 30, 90, 0.42)"}
};
const LIGHT_SECONDS = 30;  // How often the light of the day moves on
const FADE_MS = 2400;  // A new weather picture fades in over this long
const GAP = {width: 470, height: 334};  // The open gap left of the glass, where the weather falls and things move
const GLINTS = [[372, 300], [405, 293], [440, 288], [465, 286], [242, 321], [318, 331]];
const STARS = Array.from({length: 26}, (_, index) => [130 + (index * 137) % 330, 12 + (index * 71) % 180, index * 0.7]);
// What the rest of the page tells the scene: the weather, the sun, John, a ring, the night clock, the lite look
const wall = {weather: "partly", sunrise: 405, sunset: 1050, john: "idle", ringing: false, night: false,
  sleeping: false, bigOpen: false, lite: false};
// John's edge glow: violet while he listens, talks and waits for a follow-up, amber while he thinks; bold, on all four
// edges, steady (Aden's pick on the real screen: the aqua was hard to see)
const GLOW_COLOURS = {listening: "190, 70, 255", thinking: "255, 190, 106", talking: "190, 70, 255",
  followup: "190, 70, 255"};
const GLOW_WIDTH = 28;
let glowShown = "";  // The state and night the glow was last drawn for (steady, so only a change redraws it)
const EDGES = [[0, 0, 800, 0], [800, 0, 800, 480], [800, 480, 0, 480], [0, 480, 0, 0]];
const light = {name: "morning", from: "morning", to: "morning", mix: 0, late: 0};
const hare = {x: 212, y: 300, tall: 72, facing: 1, spot: "tree", pose: "stand", fromPose: "stand", poseAt: 0,
  walk: null, idle: null, nextActAt: 4000};
const images = {};
const poolMask = new Image();
const fxBubbles = [];
let particles = [];
let particlesFor = "";
let lastFrame = 0;
let flashAt = 0;
let flashShown = "0";
const FULL_FPS = Number(new URLSearchParams(location.search).get("fps")) || 30;  // frames a second (?fps= to measure)
const LITE_FPS = 15;
const LITE_FORCED = new URLSearchParams(location.search).get("lite");  // "1" or "0" forces lite on or off
const HOT = 80;  // °C: the chip this hot turns lite on...
const COOL = 74;  // ...and back off once it's down to this
const SLOW_FPS = 20;  // Fewer frames a second than this, twice in a row, turns lite on for a while
const SLOW_CHECK_MS = 10000;
const SLOW_LITE_MS = 600000;  // Lite for slowness lasts 10 minutes before the full look is tried again
let fps = FULL_FPS;
let step = 30 / fps;  // how far things move each frame, compared with 30 frames a second
let hot = false;
let slowUntil = 0;
let slowCount = 0;
let framesCounted = 0;
let countStart = 0;
const drawn = {effects: true, scenefx: true, frontfx: true, edgeglow: true};  // which layers have something on them
let soapStart = -100000;
let shownFrom = "";

// Find an entry by id in a list
function byId(list, id) {
  return list.find((entry) => entry.id === id);
}

// An S-shaped 0-to-1 ramp from start to end, so fades start and end gently (Datebook's curve)
function eased(minute, start, end) {
  const share = Math.min(1, Math.max(0, (minute - start) / Math.max(1, end - start)));
  return share * share * (3 - 2 * share);
}

// The day's keyframes, in minutes relative to today's sunrise and sunset (the same as Datebook's)
function keyframes() {
  const rise = wall.sunrise;
  const set = wall.sunset;
  return [[rise - 80, "night"], [rise - 25, "bluehour"], [rise + 25, "morning"], [rise + 110, "morning"],
    [rise + 230, "midday"], [set - 220, "midday"], [set - 95, "golden"], [set - 30, "sunset"], [set + 10, "sunset"],
    [set + 45, "bluehour"], [set + 95, "night"]];
}

// Work out the light now: the two pictures it sits between, how far the fade has gone, and the late-night dim
function updateLight() {
  const now = new Date();
  const minute = now.getHours() * 60 + now.getMinutes() + now.getSeconds() / 60;
  const keys = keyframes();
  light.from = "night";
  light.to = "night";
  light.mix = 0;

  // Find the two keyframes around the minute (before the first or after the last, it's night)
  for (let index = 0; index < keys.length - 1; index++) {
    // The minute falls in this stretch
    if (minute >= keys[index][0] && minute < keys[index + 1][0]) {
      light.from = keys[index][1];
      light.to = keys[index + 1][1];
      light.mix = light.from === light.to ? 0 : eased(minute, keys[index][0], keys[index + 1][0]);
    }
  }
  light.name = light.mix < 0.5 ? light.from : light.to;

  // Late night dims the scene: easing in from 11 PM, out by 5 AM
  if (minute >= 1380) {
    light.late = eased(minute, 1380, 1410);
  } else if (minute < 300) {
    light.late = 1 - eased(minute, 270, 300);
  } else {
    light.late = 0;
  }
  showScene();
}

// The picture file for a light in the weather now
function pictureUrl(lightName) {
  return `url('screen/img/${lightName}-${byId(WEATHERS, wall.weather).picture}.webp')`;
}

// Show the scene: the earlier light underneath, the later one on top as far as the fade has gone (lite swaps
// halfway); a new weather fades in over 2.4 seconds
function showScene() {
  const base = document.getElementById("scene");
  const top = document.getElementById("sceneTop");
  const fade = document.getElementById("sceneFade");
  const fromUrl = pictureUrl(wall.lite ? light.name : light.from);
  const toUrl = pictureUrl(light.to);
  const screen = document.getElementById("screen");

  // A different picture (the weather changed): hold the old one on top and fade it away
  if (shownFrom && fromUrl !== shownFrom && !wall.lite) {
    fade.style.transition = "none";
    fade.style.backgroundImage = shownFrom;
    fade.style.opacity = "1";
    requestAnimationFrame(() => {
      fade.style.transition = `opacity ${FADE_MS / 1000}s ease-in-out`;
      fade.style.opacity = "0";
    });
  }
  base.style.backgroundImage = fromUrl;
  top.style.backgroundImage = toUrl;
  top.style.transition = wall.lite ? "none" : "opacity 2s linear";
  top.style.opacity = wall.lite ? "0" : String(light.mix);
  shownFrom = fromUrl;
  document.getElementById("lateDim").style.opacity = String(0.3 * light.late);
  screen.style.setProperty("--tint", LIGHT_LOOKS[light.name].tint);
  screen.classList.toggle("lite", wall.lite);
}

// Set the weather and sun times from Nestor (called by the cards whenever new data arrives)
function setScene(weather) {
  const kinds = {clear: "clear", partly: "partly", overcast: "overcast", wet: "rain", storm: "storm", snow: "snow",
    fog: "fog"};

  // Without weather the scene stays as it is
  if (!weather) {
    return;
  }
  const [riseHour, riseMinute] = weather.sunrise.split(":").map(Number);
  const [setHour, setMinute] = weather.sunset.split(":").map(Number);
  wall.sunrise = riseHour * 60 + riseMinute;
  wall.sunset = setHour * 60 + setMinute;
  wall.weather = kinds[weather.scene] || "partly";
  updateLight();
}

// What he's wearing now: the weather's outfit ("" is the plain suit); no sunglasses at night
function outfit() {
  const dress = byId(WEATHERS, wall.weather).outfit;
  return light.name === "night" && dress === "sun" ? "" : dress;
}

// The picture for an action in the outfit he's wearing (stand, a walking stride, an idle moment, John, dozing)
function poseFor(action) {
  const dress = outfit();
  let pose = action;

  // Each outfit names its pictures its own way; walking in bad weather uses the suit's strides
  if (dress === "sun") {
    pose = action === "stand" ? "sunglasses" : action === "dozing" ? "dozing" : `sun-${action}`;
  } else if (dress && action === "stand") {
    pose = dress;
  } else if (dress && (action === "listening" || action === "thinking")) {
    pose = `${dress}-${action}`;
  } else if (dress && action === "dozing") {
    pose = `dozing-${dress}`;
  } else if (dress && action === "watch") {
    pose = `${dress}-watch`;
  }
  return POSES.poses[pose] ? pose : POSES.poses[dress] ? dress : action;
}

// Change to a pose with a short fade from the one before
function setPose(pose, now) {
  // Already in that pose: nothing to fade
  if (pose === hare.pose) {
    return;
  }
  hare.fromPose = hare.pose;
  hare.pose = pose;
  hare.poseAt = now;
}

// How long until he does something again: 20 to 40 seconds
function actGap() {
  return 20000 + Math.random() * 20000;
}

// Start walking to a spot
function walkTo(spotId, now) {
  const spot = byId(SPOTS, spotId);
  const distance = Math.hypot(spot.x - hare.x, spot.y - hare.y);
  hare.walk = {fromX: hare.x, fromY: hare.y, fromTall: hare.tall, to: spot, start: now,
    duration: Math.max(1200, distance * 22), distance};
  hare.facing = spot.x < hare.x ? -1 : 1;
  hare.spot = spotId;
  hare.idle = null;
}

// What he does at night: doze on the pool's rim when it's dry, or doze in his weather gear where he is
function night(now, fair) {
  // Dry nights: walk to the pool's rim first
  if (fair && hare.spot !== "pool") {
    walkTo("pool", now);
    return;
  }
  setPose(poseFor("dozing"), now);
}

// Decide what he does next: called every frame
function direct(now) {
  const fair = byId(WEATHERS, wall.weather).fair;

  // Something is ringing: he stops and taps his watch until it's stopped
  if (wall.ringing) {
    hare.walk = null;
    hare.idle = null;
    setPose(poseFor("watch"), now);
    return;
  }

  // A bigger screen is open: he steps aside to the big tree and waits
  if (wall.bigOpen) {
    // Walk over first if he isn't there yet
    if (hare.spot !== "tree" && !hare.walk) {
      walkTo("tree", now);
    }

    // Once there, he stands and waits
    if (!hare.walk) {
      setPose(poseFor("stand"), now);
      return;
    }
  }

  // John needs him: stop where he is and listen or think, in whatever he's wearing
  if (wall.john !== "idle") {
    hare.walk = null;
    hare.idle = null;
    setPose(poseFor({listening: "listening", thinking: "thinking", talking: "stand", followup: "listening"}[wall.john]),
      now);
    return;
  }

  // Walking: move along until he's there, stepping through the strides
  if (hare.walk) {
    const progress = Math.min(1, (now - hare.walk.start) / hare.walk.duration);
    hare.x = hare.walk.fromX + (hare.walk.to.x - hare.walk.fromX) * progress;
    hare.y = hare.walk.fromY + (hare.walk.to.y - hare.walk.fromY) * progress;
    hare.tall = hare.walk.fromTall + (hare.walk.to.tall - hare.walk.fromTall) * progress;
    const travelled = hare.walk.distance * progress;
    // Each stride moves him a set share of his height, so his feet stay planted
    hare.pose = poseFor(WALK_FRAMES[Math.floor(travelled / (hare.tall * 0.12)) % WALK_FRAMES.length]);
    hare.fromPose = hare.pose;

    // Arrived: stand in his outfit
    if (progress >= 1) {
      hare.walk = null;
      hare.poseAt = now;
      hare.pose = poseFor("stand");
      hare.fromPose = hare.pose;
      hare.nextActAt = now + actGap();
    }
    return;
  }

  // Night has its own plan
  if (light.name === "night") {
    night(now, fair);
    return;
  }

  // An idle moment that has run its time ends back in the resting pose
  if (hare.idle && now > hare.idle.until) {
    hare.idle = null;
    hare.nextActAt = now + actGap();
  }

  // Nothing going on: hold his outfit's pose, and on dry days pick the next thing to do when it's time
  if (!hare.idle) {
    setPose(poseFor("stand"), now);

    // Time for something new, on dry days only
    if (fair && now > hare.nextActAt) {
      // Half the time a walk to another spot, otherwise an idle moment
      if (Math.random() < 0.5) {
        const others = SPOTS.filter((spot) => spot.id !== hare.spot);
        walkTo(others[Math.floor(Math.random() * others.length)].id, now);
      } else {
        const idle = IDLES[Math.floor(Math.random() * IDLES.length)];
        hare.idle = {pose: idle, until: now + 3500};
        setPose(poseFor(idle), now);
      }
    }
  }
}

// How loud John's voice is at a moment, a wobble standing in for the real speech (as in the mockup)
function voiceLevel(time) {
  return Math.max(0, Math.sin(time * 9) * 0.35 + Math.sin(time * 23 + 1) * 0.25 + Math.sin(time * 3.3) * 0.3 + 0.35);
}

// The colour and strength of his LED eyes now (they show John's state)
function eyeGlow(now) {
  // While John talks, his eyes pulse with the voice
  if (wall.john === "talking") {
    return {colour: "90, 230, 255", strength: 0.4 + 0.6 * voiceLevel(now / 1000)};
  }

  // Listening: bright aqua, quick pulse; thinking: amber, slow; dozing: off; otherwise a soft aqua breath
  if (hare.pose.includes("listening")) {
    return {colour: "120, 240, 255", strength: 0.8 + 0.2 * Math.sin(now / 120)};
  } else if (hare.pose.includes("thinking")) {
    return {colour: "255, 190, 106", strength: 0.55 + 0.35 * Math.sin(now / 400)};
  } else if (hare.pose.startsWith("dozing")) {
    return null;
  }
  return {colour: "90, 230, 255", strength: 0.35 + 0.2 * Math.sin(now / 900)};
}

// Draw one pose of the hare onto a pen with a given opacity
function drawPose(pen, pose, alpha, now) {
  const image = images[pose];
  const info = POSES.poses[pose];

  // The picture has to have loaded
  if (!image || !image.complete || !info) {
    return;
  }
  const scale = hare.tall / POSES.standing;
  const breathing = hare.walk ? 1 + Math.abs(Math.sin(now / 260 * Math.PI / 2)) * 0.015 :
    1 + Math.sin(now / 900) * 0.006;
  const height = info.h * scale * breathing;
  const width = info.w * scale;
  pen.save();
  pen.globalAlpha = alpha;
  pen.translate(hare.x, hare.y);
  pen.scale(hare.facing, 1);
  pen.drawImage(image, -width / 2, -height, width, height);
  const glow = eyeGlow(now);

  // His LED eyes glow over the picture's eyes
  for (const [eyeX, eyeY] of glow ? info.eyes : []) {
    const x = -width / 2 + eyeX * width;
    const y = -height + eyeY * height;
    const radius = Math.max(1.2, hare.tall * 0.02);
    const shine = pen.createRadialGradient(x, y, 0, x, y, radius * 2.4);
    shine.addColorStop(0, `rgba(255, 255, 255, ${0.9 * glow.strength})`);
    shine.addColorStop(0.35, `rgba(${glow.colour}, ${0.9 * glow.strength})`);
    shine.addColorStop(1, `rgba(${glow.colour}, 0)`);
    pen.fillStyle = shine;
    pen.fillRect(x - radius * 2.4, y - radius * 2.4, radius * 4.8, radius * 4.8);
  }
  pen.restore();
}

// A canvas the hare is drawn on first, so the light's tint only falls on him (made once, used every frame)
const hareLayer = document.createElement("canvas");
hareLayer.width = GAP.width;
hareLayer.height = GAP.height;

// Draw the hare (with his shadow, the pose fade and the light's tint) onto a pen
function drawHare(pen, now) {
  const layerPen = hareLayer.getContext("2d");
  const fade = Math.min(1, (now - hare.poseAt) / 300);
  layerPen.globalCompositeOperation = "source-over";
  layerPen.clearRect(0, 0, 800, 480);

  // Fading between two poses: the old one fades out under the new one
  if (fade < 1 && hare.fromPose !== hare.pose) {
    drawPose(layerPen, hare.fromPose, 1 - fade, now);
  }
  drawPose(layerPen, hare.pose, hare.fromPose !== hare.pose ? fade : 1, now);

  // He takes on the light: dark blue at night, warm at golden hour
  if (LIGHT_LOOKS[light.name].hare) {
    layerPen.globalCompositeOperation = "source-atop";
    layerPen.fillStyle = LIGHT_LOOKS[light.name].hare;
    layerPen.fillRect(0, 0, 800, 480);
  }
  const width = hare.tall * 0.42;
  pen.fillStyle = "rgba(20, 50, 20, 0.28)";
  pen.beginPath();
  pen.ellipse(hare.x, hare.y, width * 0.6, hare.tall * 0.035, 0, 0, Math.PI * 2);
  pen.fill();
  pen.drawImage(hareLayer, 0, 0);
}

// Make the raindrops, snowflakes and fog banks for the weather now (only in the open gap)
function makeParticles() {
  particles = [];
  particlesFor = wall.weather;
  const counts = {rain: 150, storm: 260, snow: 140};
  const count = Math.round((counts[wall.weather] || 0) * GAP.width / 820);

  // Raindrops or snowflakes spread over the gap
  for (let i = 0; i < count; i++) {
    const snowing = wall.weather === "snow";
    particles.push({kind: snowing ? "flake" : "drop", x: Math.random() * GAP.width, y: Math.random() * 480,
      speed: snowing ? 0.6 + Math.random() * 0.8 : 9 + Math.random() * 6,
      size: snowing ? 1.2 + Math.random() * 2 : 9 + Math.random() * 9, sway: Math.random() * Math.PI * 2});
  }

  // Fog banks drifting low, only in fog
  for (let i = 0; i < (wall.weather === "fog" ? 5 : 0); i++) {
    particles.push({kind: "fog", x: Math.random() * GAP.width, y: 200 + Math.random() * 120,
      speed: 0.2 + Math.random() * 0.2, size: 180 + Math.random() * 120});
  }
}

// Clear a layer once when it has nothing to show, so an unchanged canvas isn't redrawn every frame
function clearOnce(id) {
  // Already empty: leave it alone
  if (!drawn[id]) {
    return;
  }
  const canvas = document.getElementById(id);
  canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  drawn[id] = false;
}

// Show the lightning flash's strength, touching the page only when it changes
function showFlash(strength) {
  const opacity = strength.toFixed(2);

  // The same as now: nothing to change
  if (opacity === flashShown) {
    return;
  }
  document.getElementById("flash").style.opacity = opacity;
  flashShown = opacity;
}

// Move and draw the falling weather, kept to the open gap away from the glass, and lightning in a storm
function drawWeather(now) {
  const pen = document.getElementById("effects").getContext("2d");
  const windy = wall.weather === "storm" ? 2.6 : 1.4;

  // A new weather gets new particles
  if (particlesFor !== wall.weather) {
    makeParticles();
  }

  // Dry weather has nothing falling: the layer stays empty
  if (!particles.length && wall.weather !== "storm") {
    clearOnce("effects");
    showFlash(0);
    return;
  }
  pen.clearRect(0, 0, GAP.width, GAP.height);
  drawn.effects = true;
  pen.save();
  pen.beginPath();
  pen.rect(0, 0, GAP.width, GAP.height);
  pen.clip();

  // Each particle moves and draws itself
  for (const particle of particles) {
    // Rain falls at a slant, snow drifts and sways, fog slides sideways
    if (particle.kind === "drop") {
      particle.y += particle.speed * step;
      particle.x += particle.speed * 0.18 * windy * step;
      pen.strokeStyle = "rgba(220, 235, 255, 0.5)";
      pen.lineWidth = 1.2;
      pen.beginPath();
      pen.moveTo(particle.x, particle.y);
      pen.lineTo(particle.x + particle.size * 0.18 * windy, particle.y + particle.size);
      pen.stroke();
    } else if (particle.kind === "flake") {
      particle.y += particle.speed * step;
      particle.x += Math.sin(now / 1000 + particle.sway) * 0.5 * step;
      pen.fillStyle = "rgba(255, 255, 255, 0.9)";
      pen.beginPath();
      pen.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
      pen.fill();
    } else {
      particle.x += particle.speed * step;
      const bank = pen.createRadialGradient(particle.x, particle.y, 10, particle.x, particle.y, particle.size);
      bank.addColorStop(0, light.name === "night" ? "rgba(170, 180, 200, 0.26)" : "rgba(240, 244, 248, 0.34)");
      bank.addColorStop(1, "rgba(240, 244, 248, 0)");
      pen.fillStyle = bank;
      pen.fillRect(particle.x - particle.size, particle.y - particle.size, particle.size * 2, particle.size * 2);
    }

    // Off the gap: start again on the other side
    if (particle.y > 490) {
      particle.y = -20;
      particle.x = Math.random() * GAP.width - 40;
    } else if (particle.x > GAP.width + (particle.kind === "fog" ? particle.size : 20)) {
      particle.x = -(particle.kind === "fog" ? particle.size : 20);
    }
  }
  pen.restore();
  let strength = 0;

  // Soft lightning flashes in a storm
  if (wall.weather === "storm") {
    // Time for the next flash
    if (now > flashAt + 6000) {
      flashAt = now + Math.random() * 3000;
    }
    const since = now - flashAt;
    strength = since > 0 && since < 260 ? 0.28 * (1 - since / 260) : 0;
  }
  showFlash(strength);
}

// Is the sky clear enough for stars and the lens flare
function clearSky() {
  return wall.weather === "clear" || wall.weather === "partly";
}

// One glass lens bubble with a rainbow rim and a shine, like Datebook's
function lensBubble(pen, x, y, radius, alpha) {
  const body = pen.createRadialGradient(x - radius * 0.35, y - radius * 0.35, radius * 0.1, x, y, radius);
  body.addColorStop(0, `rgba(255, 255, 255, ${0.5 * alpha})`);
  body.addColorStop(0.65, `rgba(200, 245, 255, ${0.06 * alpha})`);
  body.addColorStop(0.88, `rgba(120, 220, 255, ${0.35 * alpha})`);
  body.addColorStop(0.95, `rgba(255, 170, 255, ${0.4 * alpha})`);
  body.addColorStop(1, "rgba(255, 255, 255, 0)");
  pen.fillStyle = body;
  pen.beginPath();
  pen.arc(x, y, radius, 0, Math.PI * 2);
  pen.fill();
  pen.fillStyle = `rgba(255, 255, 255, ${0.7 * alpha})`;
  pen.beginPath();
  pen.ellipse(x - radius * 0.4, y - radius * 0.45, radius * 0.22, radius * 0.1, -0.6, 0, Math.PI * 2);
  pen.fill();
}

// A canvas for the pool's light, cut to the water by the pool's mask (made once, used every frame)
const water = document.createElement("canvas");
water.width = GAP.width;
water.height = GAP.height;

// The layer under the hare: the pool's shimmer and the stars on clear nights (lite keeps none of it)
function drawSceneFx(now) {
  const pen = document.getElementById("scenefx").getContext("2d");
  const time = now / 1000;

  // Lite keeps only the hare and the weather
  if (wall.lite) {
    clearOnce("scenefx");
    return;
  }
  pen.clearRect(0, 0, GAP.width, GAP.height);
  drawn.scenefx = true;
  pen.save();
  pen.beginPath();
  pen.rect(0, 0, GAP.width, GAP.height);
  pen.clip();

  // The pool: wavy light streaks drift slowly across, kept to the water by the pool's mask
  if (poolMask.complete && poolMask.naturalWidth) {
    const waterPen = water.getContext("2d");
    waterPen.globalCompositeOperation = "source-over";
    waterPen.clearRect(0, 0, 800, 480);
    waterPen.strokeStyle = `rgba(255, 255, 255, ${clearSky() ? 0.4 : 0.22})`;
    waterPen.lineWidth = 1.4;

    // A streak every few pixels down the pool
    for (let row = 0; row < 12; row++) {
      const y = 286 + row * 5;
      waterPen.beginPath();

      // Along the streak, bending with the ripples
      for (let x = 190; x <= 410; x += 6) {
        const wave = Math.sin(x * 0.06 + time * 1.2 + row) * 1.6;
        const gap = Math.sin(x * 0.03 - time * 0.7 + row * 2) > 0.2;

        // Streaks break up into short pieces of light
        if (gap) {
          waterPen.moveTo(x, y + wave);
        } else {
          waterPen.lineTo(x, y + wave);
        }
      }
      waterPen.stroke();
    }
    waterPen.globalCompositeOperation = "destination-in";
    waterPen.drawImage(poolMask, 0, 0);
    pen.drawImage(water, 0, 0);
  }

  // Stars twinkling on clear nights
  if (clearSky() && light.name === "night") {
    // Each star with its own twinkle
    for (const [x, y, phase] of STARS) {
      pen.fillStyle = `rgba(255, 255, 255, ${0.35 + 0.5 * Math.max(0, Math.sin(time * 1.7 + phase))})`;
      pen.fillRect(x, y, 1.6, 1.6);
    }
  }
  pen.restore();
}

// The layer over the hare: the golden-hour lens flare, lens bubbles and the giant soap bubble (none in lite)
function drawFrontFx(now) {
  const pen = document.getElementById("frontfx").getContext("2d");
  const time = now / 1000;
  const flare = clearSky() && light.name === "golden";

  // A giant soap bubble every 3 minutes
  if (now - soapStart > 180000) {
    soapStart = now;
  }

  // Sometimes a new lens bubble starts below the gap
  if (fxBubbles.length < 4 && Math.random() < 0.003 * step) {
    fxBubbles.push({x: 40 + Math.random() * 400, y: 350, radius: 8 + Math.random() * 12,
      speed: 0.25 + Math.random() * 0.25, sway: Math.random() * Math.PI * 2});
  }

  // Lite keeps only the hare and the weather; with no flare, bubble or soap bubble the layer stays empty
  if (wall.lite || (!flare && !fxBubbles.length && now - soapStart > 14000)) {
    clearOnce("frontfx");
    return;
  }
  pen.clearRect(0, 0, GAP.width, GAP.height);
  drawn.frontfx = true;
  pen.save();
  pen.beginPath();
  pen.rect(0, 0, GAP.width, GAP.height);
  pen.clip();

  // A lens flare from the low sun at golden hour
  if (flare) {
    const pulse = 0.85 + 0.15 * Math.sin(time * 0.6);
    const rings = [[0.1, 34, "255, 210, 140"], [0.3, 12, "140, 230, 255"], [0.5, 22, "255, 190, 120"],
      [0.68, 8, "160, 255, 220"], [0.9, 42, "255, 220, 170"]];

    // Rings strung along a line from the sun toward the lower left
    for (const [step, radius, colour] of rings) {
      const x = 470 - step * 330;
      const y = 30 + step * 290;
      const ring = pen.createRadialGradient(x, y, radius * 0.2, x, y, radius);
      ring.addColorStop(0, `rgba(${colour}, ${0.06 * pulse})`);
      ring.addColorStop(0.8, `rgba(${colour}, ${0.16 * pulse})`);
      ring.addColorStop(1, `rgba(${colour}, 0)`);
      pen.fillStyle = ring;
      pen.fillRect(x - radius, y - radius, radius * 2, radius * 2);
    }
  }

  // Each bubble rises, sways a little and leaves at the top
  for (const bubble of [...fxBubbles]) {
    bubble.y -= bubble.speed * step;
    lensBubble(pen, bubble.x + Math.sin(time + bubble.sway) * 4, bubble.y, bubble.radius, 1);

    // Gone off the top: forget it
    if (bubble.y < -30) {
      fxBubbles.splice(fxBubbles.indexOf(bubble), 1);
    }
  }

  const progress = (now - soapStart) / 14000;

  // It crosses during its first 14 seconds
  if (progress < 1) {
    lensBubble(pen, -70 + progress * 610, 200 - progress * 90 + Math.sin(progress * 9) * 8, 58, 0.9);
  }
  pen.restore();
}

// Draw one edge's glow: a soft band fading inward from the edge, at a strength
function glowSide(pen, side, colour, strength) {
  const [x1, y1, x2, y2] = side;
  const horizontal = y1 === y2;
  const inward = horizontal ? (y1 === 0 ? 1 : -1) : (x1 === 0 ? 1 : -1);
  const band = horizontal ? pen.createLinearGradient(0, y1, 0, y1 + inward * GLOW_WIDTH) :
    pen.createLinearGradient(x1, 0, x1 + inward * GLOW_WIDTH, 0);
  band.addColorStop(0, `rgba(${colour}, ${0.85 * strength})`);
  band.addColorStop(1, `rgba(${colour}, 0)`);
  pen.fillStyle = band;

  // Fill the strip along this edge
  if (horizontal) {
    pen.fillRect(Math.min(x1, x2), inward > 0 ? y1 : y1 - GLOW_WIDTH, Math.abs(x2 - x1), GLOW_WIDTH);
  } else {
    pen.fillRect(inward > 0 ? x1 : x1 - GLOW_WIDTH, Math.min(y1, y2), GLOW_WIDTH, Math.abs(y2 - y1));
  }
}

// John's edge glow: steady violet while he listens, talks and waits for a follow-up, amber while he thinks; half as
// strong in the sleeping period. It's drawn only when that changes.
function drawGlow() {
  const shown = `${wall.john}|${wall.sleeping}`;

  // Nothing while John is idle; nothing new while it's the same
  if (wall.john === "idle") {
    clearOnce("edgeglow");
    glowShown = "";
    return;
  } else if (shown === glowShown) {
    return;
  }
  const pen = document.getElementById("edgeglow").getContext("2d");
  pen.clearRect(0, 0, 800, 480);
  drawn.edgeglow = true;
  glowShown = shown;

  // Every edge glows the same
  for (const side of EDGES) {
    glowSide(pen, side, GLOW_COLOURS[wall.john] || GLOW_COLOURS.listening, wall.sleeping ? 0.5 : 1);
  }
}

// One frame (capped at fps a second)
function frame(now) {
  requestAnimationFrame(frame);

  // Skip frames to stay at the frame rate
  if (now - lastFrame < 1000 / fps - 3) {
    return;
  }
  lastFrame = now;
  countFrame(now);
  drawGlow();

  // The night clock covers the scene: nothing else needs drawing
  if (wall.night) {
    return;
  }
  direct(now);
  const pen = document.getElementById("actor").getContext("2d");
  pen.clearRect(0, 0, GAP.width, GAP.height);
  drawHare(pen, now);
  drawWeather(now);
  drawSceneFx(now);
  drawFrontFx(now);
}

// Load every pose of the hare and the pool's mask, then start the light and the frames (?lite=1 forces the lite look)
function startScene() {
  setLite(LITE_FORCED === "1");

  // Every pose of the hare
  for (const pose of Object.keys(POSES.poses)) {
    images[pose] = new Image();
    images[pose].src = `screen/img/hare-${pose}.png`;
  }
  poolMask.src = "screen/img/pool-mask.png";
  updateLight();
  setInterval(updateLight, LIGHT_SECONDS * 1000);
  requestAnimationFrame(frame);
}
startScene();
