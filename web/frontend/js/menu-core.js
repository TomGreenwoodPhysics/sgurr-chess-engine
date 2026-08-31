import { clampNumber } from "./utils.js";
import { app, refs } from "./state.js";

// Decorative layers for every core; cursor tracking for menu and result cores.
// Animation mode controls both effects.

function motionOn() {
  return app.animationMode !== "Off";
}

// Add static lighting that gives the core depth.
function buildDepth(core) {
  if (!core || core.querySelector(".core-depth")) {
    return;
  }
  const depth = document.createElement("span");
  depth.className = "core-depth";
  core.appendChild(depth);
}

// Add the nebula, aurora, mottling, and stars inside the core.
function buildCosmos(core) {
  if (!core || core.querySelector(".core-nebula")) {
    return;
  }
  const nebula = document.createElement("span");
  nebula.className = "core-nebula";
  const aurora = document.createElement("span");
  aurora.className = "core-aurora";
  const mottle = document.createElement("span");
  mottle.className = "core-mottle";
  const mottleFine = document.createElement("span");
  mottleFine.className = "core-mottle-fine";

  const stars = document.createElement("span");
  stars.className = "core-stars";
  for (let i = 0; i < 26; i += 1) {
    const star = document.createElement("span");
    star.className = "core-star";
    star.style.setProperty("--sx", `${5 + Math.random() * 90}%`);
    star.style.setProperty("--sy", `${5 + Math.random() * 90}%`);
    star.style.setProperty("--ss", `${0.5 + Math.random() * 1.5}%`);
    star.style.setProperty("--so", `${0.5 + Math.random() * 0.5}`);
    star.style.setProperty("--sdur", `${3 + Math.random() * 5}s`);
    star.style.setProperty("--sdelay", `${-Math.random() * 8}s`);
    stars.appendChild(star);
  }

  // Keep the pupil above the light layers.
  const pupil = document.createElement("span");
  pupil.className = "core-pupil";

  const fragment = document.createDocumentFragment();
  fragment.append(nebula, aurora, mottleFine, mottle, stars, pupil);
  core.appendChild(fragment);
}

// Add the corona, eclipse arc, and halo behind the core.
function buildDivinity(core) {
  if (!core || core.querySelector(".core-presence")) {
    return;
  }
  const presence = document.createElement("span");
  presence.className = "core-presence";
  const corona = document.createElement("span");
  corona.className = "core-corona";
  const eclipse = document.createElement("span");
  eclipse.className = "core-eclipse";
  const aureole = document.createElement("span");
  aureole.className = "core-aureole";
  const aureoleLate = document.createElement("span");
  aureoleLate.className = "core-aureole aureole-late";

  const fragment = document.createDocumentFragment();
  fragment.append(presence, corona, aureole, aureoleLate, eclipse);
  core.appendChild(fragment);
}

// Insert interior layers between the face and outer ring.
function buildInterior(core) {
  if (!core || core.querySelector(".core-embers")) {
    return;
  }

  const width = core.getBoundingClientRect().width || 560;
  const embers = document.createElement("span");
  embers.className = "core-embers";
  for (let i = 0; i < 9; i += 1) {
    const mote = document.createElement("span");
    mote.className = "core-ember";
    mote.style.setProperty("--ex", `${8 + Math.random() * 84}%`);
    mote.style.setProperty("--es", `${1.8 + Math.random() * 3.4}%`);
    mote.style.setProperty("--edur", `${7 + Math.random() * 7}s`);
    mote.style.setProperty("--edelay", `${-Math.random() * 12}s`);
    mote.style.setProperty("--esway", `${(Math.random() - 0.5) * width * 0.05}px`);
    embers.appendChild(mote);
  }

  const form = document.createElement("span");
  form.className = "core-form";

  const fragment = document.createDocumentFragment();
  fragment.append(embers, form);
  core.appendChild(fragment);
}

// Menu and result cores may track a still cursor or respond to a wave.
// In-game cores do not use this behaviour.
const gazes = [];
const cursor = { x: 0, y: 0 };
let settleTimer = 0;

function buildPupil(core) {
  if (!core || core.querySelector(".core-pupil")) {
    return;
  }
  const pupil = document.createElement("span");
  pupil.className = "core-pupil";
  core.appendChild(pupil);
}

// Register a core with the attention model.
function watchCursor(core) {
  if (!core) {
    return;
  }
  buildPupil(core);
  gazes.push({
    core,
    state: "idle",
    release: 0,
    cooldownUntil: 0,
    trail: [],
    seen: false,
  });
}

function setPupilGaze(gaze, x, y) {
  gaze.core.style.setProperty("--gaze-x", `${x.toFixed(2)}%`);
  gaze.core.style.setProperty("--gaze-y", `${y.toFixed(2)}%`);
}

function clearPupilGazes() {
  window.clearTimeout(settleTimer);
  settleTimer = 0;
  for (const gaze of gazes) {
    window.clearTimeout(gaze.release);
    gaze.release = 0;
    gaze.cooldownUntil = 0;
    gaze.state = "idle";
    gaze.trail.length = 0;
    setPupilGaze(gaze, 0, 0);
    gaze.core.style.setProperty("--pupil-scale", "1");
  }
}

// CSS transitions smooth the pupil's cursor tracking.
function followCursor(gaze, rect) {
  const bounds = rect || gaze.core.getBoundingClientRect();
  if (!bounds.width) {
    return;
  }
  const dx = cursor.x - (bounds.left + bounds.width / 2);
  const dy = cursor.y - (bounds.top + bounds.height / 2);
  const dist = Math.hypot(dx, dy) || 1;
  // Increase pupil deflection as the cursor approaches, capped within the rim.
  const reach = clampNumber(1.6 - dist / (bounds.width * 2.2), 0.35, 1) * 20;
  setPupilGaze(gaze, (dx / dist) * reach, (dy / dist) * reach);
}

function endInterest(gaze) {
  gaze.state = "idle";
  gaze.trail.length = 0;
  gaze.cooldownUntil = performance.now() + 4000 + Math.random() * 6000;
  setPupilGaze(gaze, 0, 0);
}

function beginInterest(gaze, rect) {
  if (gaze.state === "interested") {
    return;
  }
  gaze.state = "interested";
  gaze.trail.length = 0;
  followCursor(gaze, rect);
  window.clearTimeout(gaze.release);
  gaze.release = window.setTimeout(() => endInterest(gaze), 4500 + Math.random() * 5500);
}

// Update tracking, dilation, and wave detection for a visible eye.
function updateGaze(gaze, now) {
  const rect = gaze.core.getBoundingClientRect();
  gaze.seen = rect.width > 0;
  if (!gaze.seen) {
    return;
  }
  const distance = Math.hypot(
    cursor.x - (rect.left + rect.width / 2),
    cursor.y - (rect.top + rect.height / 2),
  ) / (rect.width / 2);

  // Slightly dilate while tracking and contract at very close range.
  const pupilScale = distance < 1.2 ? 0.97 : gaze.state === "interested" ? 1.02 : 1;
  gaze.core.style.setProperty("--pupil-scale", String(pupilScale));

  if (gaze.state === "interested") {
    followCursor(gaze, rect);
    return;
  }

  // Treat substantial nearby back-and-forth movement as a wave.
  if (distance < 1.3) {
    const last = gaze.trail[gaze.trail.length - 1];
    gaze.trail.push({ x: cursor.x, y: cursor.y, t: now, d: last ? Math.hypot(cursor.x - last.x, cursor.y - last.y) : 0 });
    while (gaze.trail.length && now - gaze.trail[0].t > 1100) {
      gaze.trail.shift();
    }
    const waved = gaze.trail.reduce((sum, sample) => sum + sample.d, 0);
    const first = gaze.trail[0];
    const net = Math.hypot(cursor.x - first.x, cursor.y - first.y);
    // Require sustained low-net movement so a single pass cannot trigger a wave.
    if (waved > rect.width * 1.4 && net < waved * 0.45) {
      beginInterest(gaze, rect);
    }
  } else {
    gaze.trail.length = 0;
  }
}

function resetRegard() {
  refs.menuCore?.style.setProperty("--regard-x", "0px");
  refs.menuCore?.style.setProperty("--regard-y", "0px");
  clearPupilGazes();
}

// Lean the menu heart toward the cursor and update visible eyes.
function onPointerMove(event) {
  if (!motionOn()) {
    return;
  }
  cursor.x = event.clientX;
  cursor.y = event.clientY;
  const now = performance.now();

  // Hold the menu core still until the intro handoff finishes.
  const menuCore = refs.menuCore;
  if (menuCore && app.mode === "menu" && app.intro.complete) {
    const rect = menuCore.getBoundingClientRect();
    if (rect.width) {
      const nx = (event.clientX - (rect.left + rect.width / 2)) / (window.innerWidth / 2);
      const ny = (event.clientY - (rect.top + rect.height / 2)) / (window.innerHeight / 2);
      const reach = 12;
      menuCore.style.setProperty("--regard-x", `${clampNumber(nx, -1, 1) * reach}px`);
      menuCore.style.setProperty("--regard-y", `${clampNumber(ny, -1, 1) * reach}px`);
    }
  }

  for (const gaze of gazes) {
    updateGaze(gaze, now);
  }

  // Give each idle eye a small chance to notice a stationary cursor.
  window.clearTimeout(settleTimer);
  settleTimer = window.setTimeout(() => {
    const settledAt = performance.now();
    for (const gaze of gazes) {
      if (gaze.seen && gaze.state === "idle" && settledAt >= gaze.cooldownUntil && Math.random() < 0.16) {
        beginInterest(gaze);
      }
    }
  }, 350 + Math.random() * 450);
}

export function initMenuCore() {
  const core = refs.menuCore;
  if (!core) {
    return;
  }
  const cores = document.querySelectorAll(".sgurr-core");

  // Keep each core's geometry matched to its rendered size.
  const sizer = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const width = entry.borderBoxSize?.[0]?.inlineSize ?? entry.contentRect.width;
      if (width) {
        entry.target.style.setProperty("--core-size", `${Math.round(width)}px`);
      }
    }
  });
  cores.forEach((el) => sizer.observe(el));

  // Randomise animation phases so visible cores do not move in sync.
  cores.forEach((el) => {
    el.style.setProperty("--core-phase", `-${(Math.random() * 60).toFixed(1)}s`);
  });

  if (motionOn()) {
    // Add depth, interior, pupil, and halo layers to every core.
    cores.forEach((el) => {
      buildDepth(el);
      buildCosmos(el);
      buildDivinity(el);
      buildInterior(el);
    });
    // Enable gaze only for menu and result cores.
    watchCursor(core);
    watchCursor(document.querySelector(".result-core-main"));
    watchCursor(document.querySelector(".result-core-secondary"));
  }
  window.addEventListener("pointermove", onPointerMove, { passive: true });
  window.addEventListener("pointerleave", resetRegard);
  window.addEventListener("blur", resetRegard);
}
