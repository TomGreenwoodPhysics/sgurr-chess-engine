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
}

export { initLabPreferences };
