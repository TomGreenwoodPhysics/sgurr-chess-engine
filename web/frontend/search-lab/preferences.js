import { THEMES, THEME_ORDER, initialTheme } from "../js/config.js";

const refs = {
  theme: document.querySelector("#labThemeSelect"),
  themeColour: document.querySelector('meta[name="theme-color"]'),
};

let themeKey = initialTheme;
let audioContext = null;

function applyTheme(nextTheme) {
  themeKey = THEME_ORDER.includes(nextTheme) ? nextTheme : "wood";
  const theme = THEMES[themeKey];
  for (const [name, value] of Object.entries(theme.vars)) {
    document.documentElement.style.setProperty(name, value);
  }
  document.documentElement.dataset.theme = themeKey;
  refs.theme.value = themeKey;
  refs.themeColour?.setAttribute("content", theme.vars["--bg"]);
  localStorage.setItem("sgurrTheme", themeKey);
  // Cache the palette so the next page can apply it before first paint.
  localStorage.setItem("sgurrThemeVars", JSON.stringify(theme.vars));
  document.dispatchEvent(new CustomEvent("sgurrthemechange", { detail: { themeKey } }));
}

function playInterfaceSound({ rate = 1, volume = 1 } = {}) {
  const storedMasterVolume = Number(localStorage.getItem("sgurrMasterVolume") ?? "1");
  const masterVolume = Number.isFinite(storedMasterVolume)
    ? Math.max(0, Math.min(1, storedMasterVolume))
    : 1;
  const storedVolume = Number(localStorage.getItem("sgurrSoundVolume") || "0.8");
  const soundVolume = Number.isFinite(storedVolume)
    ? Math.max(0, Math.min(1, storedVolume))
    : 0.8;
  if (masterVolume === 0 || soundVolume === 0) return;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return;

  audioContext ||= new AudioContextClass();
  if (audioContext.state === "suspended") audioContext.resume().catch(() => {});

  const startedAt = audioContext.currentTime + 0.004;
  const oscillator = audioContext.createOscillator();
  const envelope = audioContext.createGain();
  oscillator.type = "triangle";
  oscillator.frequency.setValueAtTime(480 * rate, startedAt);
  oscillator.frequency.exponentialRampToValueAtTime(320 * rate, startedAt + 0.045);
  envelope.gain.setValueAtTime(0.0001, startedAt);
  envelope.gain.exponentialRampToValueAtTime(Math.max(0.0001, masterVolume * soundVolume * volume * 0.12), startedAt + 0.006);
  envelope.gain.exponentialRampToValueAtTime(0.0001, startedAt + 0.045);
  oscillator.connect(envelope).connect(audioContext.destination);
  oscillator.start(startedAt);
  oscillator.stop(startedAt + 0.065);
}

function initInterfaceSounds() {
  document.addEventListener("click", (event) => {
    const control = event.target instanceof Element
      ? event.target.closest("button, .back-link")
      : null;
    if (!control || control.disabled || control.dataset.sound === "none") return;
    playInterfaceSound();
  });
  document.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLSelectElement)) return;
    playInterfaceSound({ rate: 1.08, volume: 0.78 });
  });
}

function cycleSelect(select, step) {
  if (!select || !select.options.length) return;
  const next = (select.selectedIndex + step + select.options.length) % select.options.length;
  select.selectedIndex = next;
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

// Match the main app shortcuts. T changes theme and D changes detail.
function initLabShortcuts() {
  window.addEventListener("keydown", (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target;
    if (target instanceof HTMLElement && target.matches("input, textarea, select")) return;
    const key = event.key.toLowerCase();
    if (key === "t") {
      event.preventDefault();
      cycleSelect(refs.theme, event.shiftKey ? -1 : 1);
      playInterfaceSound({ rate: 1.06, volume: 0.5 });
    } else if (key === "d") {
      const detail = document.querySelector("#labDetailSelect");
      if (!detail) return;
      event.preventDefault();
      cycleSelect(detail, event.shiftKey ? -1 : 1);
      playInterfaceSound({ rate: 1.02, volume: 0.5 });
    }
  });
}

function initLabPreferences() {
  for (const key of THEME_ORDER) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = THEMES[key].label;
    refs.theme.appendChild(option);
  }
  applyTheme(themeKey);

  refs.theme.addEventListener("change", () => applyTheme(refs.theme.value));
  initInterfaceSounds();
  initLabShortcuts();
}

export { initLabPreferences };
