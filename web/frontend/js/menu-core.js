import { clampNumber } from "./utils.js";
import { app, refs } from "./state.js";

// Aesthetic life for every Sgurr core: the god-eye layer stack (depth,
// cosmos, divinity, interior) injected into all of them, cursor attention
// for the menu and post-game cores, and a rare "surfacing" idle beat on the
// menu. Everything here is decorative and only runs while the in-app
// Animations setting is on — so users who turn it off, and the headless
// smoke tests (animations off), get static, undisturbed cores.

function motionOn() {
  return app.animationMode !== "Off";
}

// Structural depth: a static volumetric light/shadow layer that makes the
// orb read as a lit sphere. Purely decorative.
function buildDepth(core) {
  if (!core || core.querySelector(".core-depth")) {
    return;
  }
  const depth = document.createElement("span");
  depth.className = "core-depth";
  core.appendChild(depth);
}

// A slow cosmos inside the glass: nebula clouds, dim aurora ribbons, two
// counter-turning fields of soft mottled cells, and a twinkling starfield.
// Screen-blended luminous internal structure.
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

  // The pupil rides above every luminous layer, so the cosmos can never
  // wash it out.
  const pupil = document.createElement("span");
  pupil.className = "core-pupil";

  const fragment = document.createDocumentFragment();
  fragment.append(nebula, aurora, mottleFine, mottle, stars, pupil);
  core.appendChild(fragment);
}

// The apparatus of godhead: a breathing presence behind everything, wheeling
// shafts of corona light, a brilliant eclipse arc precessing around the rim,
// and paired halo ripples. All peripheral — the eye itself is untouched.
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

// Inject the interior child layers once. They paint above the molten face and
// below the outer ring, so the motes and the half-seen form float in the glass.
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
  const surge = document.createElement("span");
  surge.className = "core-surge";

  const fragment = document.createDocumentFragment();
  fragment.append(embers, form, surge);
  core.appendChild(fragment);
}

// The pupil's attention model, shared by every gazing core — the menu hero
// core and the post-game result cores; in-game cores keep their status role
// and do not gaze. Mostly an eye ignores the cursor and keeps to its idle
// wander. Now and then a settled cursor happens to catch its interest, and
// while interested it genuinely follows — a lagged, smooth pursuit — until
// the interest decays and it drifts back to its own thoughts. Waving the
// cursor over an orb, though, reliably wins its attention. Dilation stays
// faint throughout: a flicker of engagement, not a display.
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

// Give a core an eye and enrol it in the attention model.
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

// While interested, the pupil looks where the cursor is; the CSS transition
// turns per-move updates into a smooth, slightly trailing pursuit.
function followCursor(gaze, rect) {
  const bounds = rect || gaze.core.getBoundingClientRect();
  if (!bounds.width) {
    return;
  }
  const dx = cursor.x - (bounds.left + bounds.width / 2);
  const dy = cursor.y - (bounds.top + bounds.height / 2);
  const dist = Math.hypot(dx, dy) || 1;
  // Deflection (in % of the pupil's own size) grows as the cursor closes
  // in, capped well short of the rim: it looks, it does not strain.
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

// Per-move update for one eye: faint dilation, pursuit while interested,
// wave detection while idle. Hidden cores (their screen is not showing)
// are skipped entirely.
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

  // Dilation is faint — a flicker of engagement, not a display: the merest
  // widening while it follows, the merest narrowing when the cursor is
  // right on top of it.
  const pupilScale = distance < 1.2 ? 0.97 : gaze.state === "interested" ? 1.02 : 1;
  gaze.core.style.setProperty("--pupil-scale", String(pupilScale));

  if (gaze.state === "interested") {
    followCursor(gaze, rect);
    return;
  }

  // Waving the cursor over an orb reliably wins its attention: enough path
  // length traced near the core within a second, with little net travel —
  // back-and-forth, not a fly-by — reads as a wave.
  if (distance < 1.3) {
    const last = gaze.trail[gaze.trail.length - 1];
    gaze.trail.push({ x: cursor.x, y: cursor.y, t: now, d: last ? Math.hypot(cursor.x - last.x, cursor.y - last.y) : 0 });
    while (gaze.trail.length && now - gaze.trail[0].t > 1100) {
      gaze.trail.shift();
    }
    const waved = gaze.trail.reduce((sum, sample) => sum + sample.d, 0);
    const first = gaze.trail[0];
    const net = Math.hypot(cursor.x - first.x, cursor.y - first.y);
    // Thresholds sized so a pass across the orb, or a there-and-back to a
    // button beyond it, cannot qualify: only a sustained wave can trace
    // this much low-net path this close to the core inside a second.
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

// The menu heart leans a little toward the cursor (the CSS transition
// supplies the lag), and every visible gazing eye gets its per-move update.
function onPointerMove(event) {
  if (!motionOn()) {
    return;
  }
  cursor.x = event.clientX;
  cursor.y = event.clientY;
  const now = performance.now();

  const menuCore = refs.menuCore;
  if (menuCore && app.mode === "menu") {
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

  // When the cursor settles somewhere, each visible idle eye has only a
  // small chance of happening to find it interesting.
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

// A rare idle beat: the ember flares and something rises to regard you, then
// subsides. Randomised interval so it never feels scheduled.
function scheduleSurface() {
  const delay = 15000 + Math.random() * 15000;
  window.setTimeout(() => {
    const core = refs.menuCore;
    if (core && app.mode === "menu" && motionOn() && !document.hidden) {
      const surge = core.querySelector(".core-surge");
      core.classList.add("surfacing");
      // Drop the class only once the flare has fully eased out, so it never
      // gets cut off mid-animation. Fall back to a timer if there's no surge.
      if (surge) {
        surge.addEventListener("animationend", () => core.classList.remove("surfacing"), { once: true });
      } else {
        window.setTimeout(() => core.classList.remove("surfacing"), 4200);
      }
    }
    scheduleSurface();
  }, delay);
}

export function initMenuCore() {
  const core = refs.menuCore;
  if (!core) {
    return;
  }
  const cores = document.querySelectorAll(".sgurr-core");

  // Every core scales its god-eye geometry from --core-size; keep it in
  // step with the rendered size (responsive breakpoints, per-outcome result
  // sizes, the board-relative mate core) regardless of the motion setting.
  const sizer = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const width = entry.borderBoxSize?.[0]?.inlineSize ?? entry.contentRect.width;
      if (width) {
        entry.target.style.setProperty("--core-size", `${Math.round(width)}px`);
      }
    }
  });
  cores.forEach((el) => sizer.observe(el));

  // Each core lives at its own random point in the shared animation cycles,
  // so no two eyes ever pulse, churn or wander in lockstep — most visible in
  // watch mode, where several are on screen at once.
  cores.forEach((el) => {
    el.style.setProperty("--core-phase", `-${(Math.random() * 60).toFixed(1)}s`);
  });

  if (motionOn()) {
    // Every blob is the menu blob: structural depth, the internal cosmos
    // (with its pupil) and the peripheral divinity on all of them, plus the
    // living interior of motes and half-seen forms.
    cores.forEach((el) => {
      buildDepth(el);
      buildCosmos(el);
      buildDivinity(el);
      buildInterior(el);
    });
    // The gazing eyes: the menu hero core and the post-game result cores.
    // In-game cores keep their status role and do not gaze; the intro core
    // keeps its pupil (from the cosmos) but slumbers on, unenrolled.
    watchCursor(core);
    watchCursor(document.querySelector(".result-core-main"));
    watchCursor(document.querySelector(".result-core-secondary"));
  }
  window.addEventListener("pointermove", onPointerMove, { passive: true });
  window.addEventListener("pointerleave", resetRegard);
  window.addEventListener("blur", resetRegard);
  scheduleSurface();
}
