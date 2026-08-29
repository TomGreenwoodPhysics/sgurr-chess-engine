import { playSound, syncMenuMusic, unlockAudio } from "./audio.js";
import { INTRO_BLACKOUT_DURATION_MS, INTRO_HANDOFF_DURATION_MS, INTRO_NAME_DURATION_MS, INTRO_REVEAL_DURATION_MS, INTRO_WAKE_DURATION_MS } from "./config.js";
import { app, refs } from "./state.js";

// Use only the in-app setting. The intro plays by default regardless of the OS preference.
function introMotionEnabled() {
  return app.animationMode !== "Off";
}

function initIntro() {
  if (!refs.introScreen || !refs.introCoreTrigger || !refs.menuCore) {
    app.intro.complete = true;
    document.body.classList.remove(
      "intro-pending",
      "intro-revealing",
      "intro-background-ready",
    );
    return;
  }

  refs.introScreen.hidden = false;
  refs.introScreen.dataset.state = "dormant";
  refs.introScreen.dataset.motion = introMotionEnabled() ? "on" : "off";
  prepareIntroTitle();
  if (introMotionEnabled()) {
    spawnIntroMotes();
  }
  refs.introState.textContent = "Sgurr v8.2";
  refs.introCore.classList.add("dormant");
  refs.introCore.classList.remove("ready", "thinking");
  refs.introCoreTrigger.disabled = false;
  refs.wakeSgurrButton.disabled = false;
  refs.wakeSgurrButton.textContent = "Enter";
  refs.menuScreen.inert = true;
  refs.appShell.inert = true;
}

function prepareIntroTitle() {
  const h1 = document.querySelector("#introTitle");
  if (!h1 || h1.dataset.lettered) {
    return;
  }
  const text = h1.textContent.trim();
  h1.dataset.lettered = "1";
  h1.setAttribute("aria-label", text);
  h1.replaceChildren(
    ...[...text].map((ch, i) => {
      const span = document.createElement("span");
      span.className = "intro-letter";
      span.style.setProperty("--i", i);
      span.textContent = ch;
      span.setAttribute("aria-hidden", "true");
      return span;
    }),
  );
}

function spawnIntroMotes() {
  if (!refs.introScreen || refs.introScreen.querySelector(".intro-mote")) {
    return;
  }
  const fragment = document.createDocumentFragment();
  for (let i = 0; i < 14; i += 1) {
    const mote = document.createElement("span");
    mote.className = "intro-mote";
    mote.setAttribute("aria-hidden", "true");
    mote.style.setProperty("--mx", `${6 + Math.random() * 88}%`);
    mote.style.setProperty("--my", `${10 + Math.random() * 78}%`);
    mote.style.setProperty("--md", `${9 + Math.random() * 14}s`);
    mote.style.setProperty("--mdelay", `${-Math.random() * 20}s`);
    mote.style.setProperty("--ms", `${1.5 + Math.random() * 2.2}px`);
    fragment.appendChild(mote);
  }
  refs.introScreen.appendChild(fragment);
}

// Create falling dust when the core is disturbed.
function spawnDisturbanceDust() {
  if (!refs.introScreen) {
    return;
  }
  const fragment = document.createDocumentFragment();
  const grains = [];
  for (let i = 0; i < 18; i += 1) {
    const grain = document.createElement("span");
    grain.className = "intro-dust";
    grain.setAttribute("aria-hidden", "true");
    grain.style.setProperty("--dx", `${4 + Math.random() * 92}%`);
    grain.style.setProperty("--dw", `${1.4 + Math.random() * 2.4}px`);
    grain.style.setProperty("--dd", `${700 + Math.random() * 800}ms`);
    grain.style.setProperty("--ddelay", `${Math.random() * 450}ms`);
    grain.style.setProperty("--dsway", `${(Math.random() - 0.5) * 60}px`);
    fragment.appendChild(grain);
    grains.push(grain);
  }
  refs.introScreen.appendChild(fragment);
  window.setTimeout(() => {
    for (const grain of grains) {
      grain.remove();
    }
  }, 2400);
}

// Replace the delayed CSS animation with a fade from its current state.
// This keeps early interaction from leaving the prompt over the title card.
function dismissIntroCopy() {
  const copy = refs.introCopy;
  if (!copy || typeof copy.getAnimations !== "function") {
    return;
  }
  const arriving = copy.getAnimations();
  if (!arriving.length) {
    return;
  }
  const { opacity, transform } = window.getComputedStyle(copy);
  for (const animation of arriving) {
    animation.cancel();
  }
  copy.style.animation = "none";
  if (typeof copy.animate !== "function") {
    return;
  }
  // Keep the prompt hidden for all later intro states.
  copy.animate(
    [
      { opacity, transform },
      { opacity: 0, transform: "translateX(-50%) translateY(16px)" },
    ],
    { duration: 520, easing: "ease", fill: "forwards" },
  );
}

// Synchronise the intro and menu core phases for a seamless handoff.
// The menu core is still hidden here.
function syncMenuCorePhase() {
  const phase = refs.introCore?.style.getPropertyValue("--core-phase");
  if (phase) {
    refs.menuCore.style.setProperty("--core-phase", phase);
  }
}

function finishIntro() {
  if (app.intro.complete) {
    return;
  }

  window.clearTimeout(app.intro.wakeTimer);
  window.clearTimeout(app.intro.nameTimer);
  window.clearTimeout(app.intro.blackoutTimer);
  window.clearTimeout(app.intro.handoffTimer);
  window.clearTimeout(app.intro.revealTimer);
  app.intro.complete = true;
  app.intro.waking = false;
  app.intro.revealing = false;
  refs.menuScreen.style.transition = "none";
  refs.menuScreen.style.opacity = "1";
  refs.menuCore.style.transition = "none";
  refs.menuCore.style.opacity = "1";
  refs.introScreen.hidden = true;
  refs.menuScreen.inert = false;
  refs.appShell.inert = false;
  document.body.classList.remove(
    "intro-pending",
    "intro-revealing",
    "intro-background-ready",
  );
  document.body.classList.add("intro-complete");

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      refs.menuCore.style.removeProperty("transition");
      refs.menuCore.style.removeProperty("opacity");
      refs.menuScreen.style.removeProperty("transition");
      refs.menuScreen.style.removeProperty("opacity");
    });
  });
  syncMenuMusic({ force: true });
}

// Show the title card while the chamber pauses.
function beginIntroNaming() {
  if (app.intro.complete || !app.intro.waking) {
    return;
  }

  refs.introScreen.dataset.state = "naming";
  refs.introState.textContent = "A chess engine built from scratch in C++";
  playSound("boss_reveal", { volume: 0.9 });
  app.intro.nameTimer = window.setTimeout(
    beginIntroHandoff,
    introMotionEnabled() ? INTRO_NAME_DURATION_MS : 20,
  );
}

function beginIntroHandoff() {
  if (app.intro.complete || !app.intro.waking) {
    return;
  }

  refs.introScreen.dataset.state = "blackout";
  app.intro.blackoutTimer = window.setTimeout(
    beginIntroMenuHandoff,
    introMotionEnabled() ? INTRO_BLACKOUT_DURATION_MS : 20,
  );
}

function beginIntroMenuHandoff() {
  if (app.intro.complete || !app.intro.waking) {
    return;
  }

  const motion = introMotionEnabled();
  const trigger = refs.introCoreTrigger;
  refs.menuCore.classList.add("ready", "thinking");
  syncMenuCorePhase();
  const source = trigger.getBoundingClientRect();
  const target = refs.menuCore.getBoundingClientRect();
  const sourceWidth = trigger.offsetWidth;
  const sourceHeight = trigger.offsetHeight;
  const targetWidth = refs.menuCore.offsetWidth;

  refs.introScreen.dataset.state = "transferring";
  document.body.classList.add("intro-background-ready");

  if (
    !motion
    || typeof trigger.animate !== "function"
    || sourceWidth <= 0
    || targetWidth <= 0
  ) {
    beginIntroReveal();
    return;
  }

  // Measure from the centre while the wake scale is still active.
  const dx = (target.left + target.width / 2) - (source.left + source.width / 2);
  const dy = (target.top + target.height / 2) - (source.top + source.height / 2);
  const scale = targetWidth / sourceWidth;

  // Derive the starting scale from the rendered and layout boxes.
  // This prevents a jump when the CSS animation hands off.
  const restScale = source.width / sourceWidth;
  const frame = (x, y, zoom) =>
    `translate(${(x - sourceWidth / 2).toFixed(2)}px, ${(y - sourceHeight / 2).toFixed(2)}px) scale(${zoom.toFixed(4)})`;

  app.intro.handoffAnimation = trigger.animate(
    [
      { transform: frame(0, 0, restScale), offset: 0 },
      {
        transform: frame(dx * 0.34, dy * 0.22 - 16, restScale + (scale - restScale) * 0.28),
        offset: 0.34,
      },
      { transform: frame(dx, dy, scale), offset: 1 },
    ],
    {
      duration: INTRO_HANDOFF_DURATION_MS,
      easing: "cubic-bezier(0.16, 0.82, 0.2, 1)",
      fill: "forwards",
    },
  );

  app.intro.handoffAnimation.finished.then(beginIntroReveal).catch(beginIntroReveal);
  app.intro.handoffTimer = window.setTimeout(
    beginIntroReveal,
    INTRO_HANDOFF_DURATION_MS + 120,
  );
}

function beginIntroReveal() {
  if (app.intro.complete || !app.intro.waking || app.intro.revealing) {
    return;
  }

  app.intro.revealing = true;
  window.clearTimeout(app.intro.handoffTimer);
  refs.introScreen.dataset.state = "departing";
  document.body.classList.add("intro-revealing");
  app.intro.revealTimer = window.setTimeout(
    finishIntro,
    introMotionEnabled() ? INTRO_REVEAL_DURATION_MS : 20,
  );
}

function wakeSgurr() {
  if (app.intro.complete || app.intro.waking) {
    return;
  }

  app.intro.waking = true;
  refs.introScreen.dataset.state = "waking";
  refs.introState.textContent = "Starting Sgurr";
  refs.introCore.classList.remove("dormant");
  refs.introCore.classList.add("ready", "thinking");
  refs.introCoreTrigger.disabled = true;
  refs.wakeSgurrButton.disabled = true;
  refs.wakeSgurrButton.textContent = "Starting";
  unlockAudio();
  playSound("boss_rumble", { volume: 1.15 });
  dismissIntroCopy();

  if (introMotionEnabled()) {
    spawnDisturbanceDust();
    window.setTimeout(() => {
      if (app.intro.waking && !app.intro.complete) {
        refs.introState.textContent = "Sgurr is ready";
      }
    }, 850);
  }

  app.intro.wakeTimer = window.setTimeout(
    beginIntroNaming,
    introMotionEnabled() ? INTRO_WAKE_DURATION_MS : 30,
  );
}

export {
  introMotionEnabled,
  initIntro,
  prepareIntroTitle,
  spawnIntroMotes,
  spawnDisturbanceDust,
  dismissIntroCopy,
  syncMenuCorePhase,
  finishIntro,
  beginIntroNaming,
  beginIntroHandoff,
  beginIntroMenuHandoff,
  beginIntroReveal,
  wakeSgurr,
};
