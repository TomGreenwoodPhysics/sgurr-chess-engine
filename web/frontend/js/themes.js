import { currentTimeControl } from "./clocks.js";
import { THEMES, THEME_ORDER, TIME_CONTROLS } from "./config.js";
import { app, refs } from "./state.js";
import { render } from "./ui.js";

function applyTheme() {
  const theme = THEMES[app.themeKey] || THEMES.wood;
  for (const [name, value] of Object.entries(theme.vars)) {
    document.documentElement.style.setProperty(name, value);
  }
  document.documentElement.dataset.theme = app.themeKey;
  // Keeps the browser chrome in step with the palette; the labs do the same
  // in their own preferences module.
  refs.themeColour?.setAttribute("content", theme.vars["--bg"]);
  localStorage.setItem("sgurrTheme", app.themeKey);
  // Lets the labs paint this palette before their first frame.
  localStorage.setItem("sgurrThemeVars", JSON.stringify(theme.vars));
}

// Mirrors app.animationMode onto the body so CSS can suppress decorative
// layers. Must run before initIntro() so the intro's first frame is already
// correct for users who have animations off.
function applyAnimationMode() {
  document.body.classList.toggle("animations-off", app.animationMode === "Off");
}

function cycleTheme(direction) {
  const index = THEME_ORDER.indexOf(app.themeKey);
  app.themeKey = THEME_ORDER[(index + direction + THEME_ORDER.length) % THEME_ORDER.length];
  applyTheme();
  render();
}

function cycleTime(direction) {
  app.timeIndex = (app.timeIndex + direction + TIME_CONTROLS.length) % TIME_CONTROLS.length;
  localStorage.setItem("sgurrTimeIndex", String(app.timeIndex));
  refs.movetimeSelect.value = currentTimeControl().key;
  render();
}

// ---------------------------------------------------------------------
// The modal layer, and its focus handling.
//
// The dialogs are siblings of #menuScreen and #appShell, so marking those
// two inert lifts the whole background out of the tab order in one move --
// the same primitive the intro uses while it holds the screen. Inert is
// what actually stops focus escaping; the Tab wrap below is polish, so the
// last control cycles back to the first instead of out to browser chrome.
//
// #resultModal is deliberately not in this set. It is render-driven -- ui.js
// shows it from game state rather than from a user action -- so there is no
// trigger element to hand focus back to when it closes.
// ---------------------------------------------------------------------
function userModals() {
  return [
    refs.themeModal,
    refs.timeModal,
    refs.engineModal,
    refs.settingsModal,
    refs.helpModal,
  ];
}

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

let modalReturnFocus = null;

function openModalElement() {
  return userModals().find((modal) => modal && !modal.hidden) || null;
}

function focusablesWithin(root) {
  return [...root.querySelectorAll(FOCUSABLE_SELECTOR)].filter(
    (el) => el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement,
  );
}

function setBackgroundInert(inert) {
  // While the intro still holds the screen it owns these two flags. Closing a
  // modal must never hand the menu back early.
  if (!inert && !app.intro.complete) {
    return;
  }
  refs.menuScreen.inert = inert;
  refs.appShell.inert = inert;
}

function onModalKeydown(event) {
  if (event.key !== "Tab") {
    return;
  }
  const modal = openModalElement();
  if (!modal) {
    return;
  }
  const focusables = focusablesWithin(modal);
  if (!focusables.length) {
    event.preventDefault();
    return;
  }
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

document.addEventListener("keydown", onModalKeydown);

function openModal(modal) {
  const trigger = document.activeElement;
  closeAllModals({ restoreFocus: false });
  modal.hidden = false;
  setBackgroundInert(true);
  modalReturnFocus = trigger instanceof HTMLElement ? trigger : null;

  // Focus the dialog box itself rather than its first control, so assistive
  // technology reads the title before the buttons. It is not natively
  // focusable, hence the programmatic tabindex. Callers that want a specific
  // control focused simply focuses it after this returns.
  const box = modal.querySelector('[role="dialog"]');
  if (box) {
    box.tabIndex = -1;
    box.focus();
  } else {
    focusablesWithin(modal)[0]?.focus();
  }
}

// Bound directly as a click listener on [data-close-modal], so this is also
// called with a MouseEvent. Read the flag defensively rather than
// destructuring, so only a genuine { restoreFocus: false } suppresses the
// hand-back -- anything else, event object included, restores focus.
function closeAllModals(options) {
  const restoreFocus = options?.restoreFocus !== false;
  for (const modal of userModals()) {
    modal.hidden = true;
  }
  setBackgroundInert(false);
  if (restoreFocus) {
    if (modalReturnFocus?.isConnected) {
      modalReturnFocus.focus();
    }
    modalReturnFocus = null;
  }
}

function setTheme(themeKey) {
  app.themeKey = themeKey;
  applyTheme();
  render();
}

function setTimeIndex(index) {
  app.timeIndex = index;
  localStorage.setItem("sgurrTimeIndex", String(app.timeIndex));
  refs.movetimeSelect.value = currentTimeControl().key;
  render();
}

function saveSettings() {
  localStorage.setItem("sgurrAutoFlip", String(app.autoFlipAsBlack));
  localStorage.setItem("sgurrShowEngineInfo", String(app.showEngineInfo));
  localStorage.setItem("sgurrAnimationMode", app.animationMode);
  localStorage.setItem("sgurrMasterVolume", String(app.masterVolume));
  localStorage.setItem("sgurrSoundVolume", String(app.soundVolume));
  localStorage.setItem("sgurrMusicVolume", String(app.musicVolume));
  localStorage.setItem("sgurrGameMusicVolume", String(app.gameMusicVolume));
  localStorage.removeItem("sgurrSoundEnabled");
  localStorage.removeItem("sgurrMusicEnabled");
  localStorage.removeItem("sgurrGameMusicEnabled");
}

function renderThemeGallery() {
  refs.themeGallery.innerHTML = "";

  for (const key of THEME_ORDER) {
    const theme = THEMES[key];
    const button = document.createElement("button");
    button.type = "button";
    button.className = `theme-card ${key === app.themeKey ? "active" : ""}`;

    const preview = document.createElement("div");
    preview.className = "theme-preview";
    preview.style.setProperty("--preview-light", theme.vars["--board-light"]);
    preview.style.setProperty("--preview-dark", theme.vars["--board-dark"]);
    for (let index = 0; index < 8; index += 1) {
      preview.appendChild(document.createElement("span"));
    }

    const label = document.createElement("strong");
    label.textContent = theme.label;

    button.append(preview, label);
    button.addEventListener("click", () => setTheme(key));
    refs.themeGallery.appendChild(button);
  }
}

function renderTimeGallery() {
  refs.timeGallery.innerHTML = "";

  TIME_CONTROLS.forEach((control, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `time-card ${index === app.timeIndex ? "active" : ""}`;
    button.innerHTML = `
      <strong>${control.label}</strong>
      <span>${Math.round(control.baseSeconds / 60)} min + ${control.incrementSeconds}s increment</span>
    `;
    button.addEventListener("click", () => setTimeIndex(index));
    refs.timeGallery.appendChild(button);
  });
}

function renderSettings() {
  applyAnimationMode();
  refs.autoFlipInput.checked = app.autoFlipAsBlack;
  refs.showEngineInfoInput.checked = app.showEngineInfo;
  refs.animationModeSelect.value = app.animationMode;
  refs.masterVolumeInput.value = String(app.masterVolume);
  refs.masterVolumeValue.textContent = `${Math.round(app.masterVolume * 100)}%`;
  refs.soundVolumeInput.value = String(app.soundVolume);
  refs.soundVolumeValue.textContent = `${Math.round(app.soundVolume * 100)}%`;
  refs.musicVolumeInput.value = String(app.musicVolume);
  refs.musicVolumeValue.textContent = `${Math.round(app.musicVolume * 100)}%`;
  refs.gameMusicVolumeInput.value = String(app.gameMusicVolume);
  refs.gameMusicVolumeValue.textContent = `${Math.round(app.gameMusicVolume * 100)}%`;
}

export {
  applyAnimationMode,
  applyTheme,
  cycleTheme,
  cycleTime,
  openModal,
  closeAllModals,
  setTheme,
  setTimeIndex,
  saveSettings,
  renderThemeGallery,
  renderTimeGallery,
  renderSettings,
};
