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
  localStorage.setItem("sgurrTheme", app.themeKey);
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

function openModal(modal) {
  closeAllModals();
  modal.hidden = false;
}

function closeAllModals() {
  for (const modal of [
    refs.themeModal,
    refs.timeModal,
    refs.settingsModal,
    refs.helpModal,
    refs.fenModal,
  ]) {
    modal.hidden = true;
  }
  refs.fenError.textContent = "";
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
  localStorage.setItem("sgurrSoundEnabled", String(app.soundEnabled));
  localStorage.setItem("sgurrSoundVolume", String(app.soundVolume));
  localStorage.setItem("sgurrMusicEnabled", String(app.musicEnabled));
  localStorage.setItem("sgurrMusicVolume", String(app.musicVolume));
  localStorage.setItem("sgurrGameMusicEnabled", String(app.gameMusicEnabled));
  localStorage.setItem("sgurrGameMusicVolume", String(app.gameMusicVolume));
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
  refs.autoFlipInput.checked = app.autoFlipAsBlack;
  refs.showEngineInfoInput.checked = app.showEngineInfo;
  refs.animationModeSelect.value = app.animationMode;
  refs.soundEnabledInput.checked = app.soundEnabled;
  refs.soundVolumeInput.value = String(app.soundVolume);
  refs.musicEnabledInput.checked = app.musicEnabled;
  refs.musicVolumeInput.value = String(app.musicVolume);
  refs.gameMusicEnabledInput.checked = app.gameMusicEnabled;
  refs.gameMusicVolumeInput.value = String(app.gameMusicVolume);
}

export {
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
