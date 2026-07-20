import { visibleClock } from "./clocks.js";
import { PROCEDURAL_SOUND_NAMES, SOUND_FILES, apiUrl } from "./config.js";
import { app } from "./state.js";
import { clampNumber } from "./utils.js";

function soundUrl(name) {
  return apiUrl(`/assets/sounds/${SOUND_FILES[name]}`);
}

function initAudio() {
  for (const name of Object.keys(SOUND_FILES)) {
    const audio = new Audio(soundUrl(name));
    audio.preload = "auto";
    audio.volume = Math.max(0, Math.min(1, app.soundVolume));
    app.audio[name] = audio;
  }

  const music = new Audio(apiUrl("/assets/music/menu-theme.ogg"));
  music.loop = true;
  music.preload = "auto";
  music.volume = 0;
  app.musicAudio = music;

  for (const [name, file] of Object.entries({
    pulse: "game-pulse.mp3",
    urgent: "game-urgent.mp3",
  })) {
    const track = new Audio(apiUrl(`/assets/music/${file}`));
    track.loop = true;
    track.preload = "auto";
    track.volume = 0;
    app.gameMusicAudio[name] = track;
  }
}

function unlockAudio() {
  if (app.audioUnlocked) {
    return;
  }
  app.audioUnlocked = true;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!app.audioContext && AudioContextClass) {
    app.audioContext = new AudioContextClass();
  }
  app.audioContext?.resume().catch(() => {});
  for (const audio of Object.values(app.audio)) {
    audio.load();
  }
  app.musicAudio?.load();
  for (const track of Object.values(app.gameMusicAudio)) {
    track.load();
  }
  syncMenuMusic({ force: true });
  syncGameMusic({ force: true });
}

function scheduleSynthTone(context, destination, startAt, {
  frequency,
  endFrequency = frequency,
  duration = 0.08,
  gain = 0.1,
  type = "sine",
  attack = 0.006,
}) {
  const oscillator = context.createOscillator();
  const envelope = context.createGain();
  oscillator.type = type;
  oscillator.frequency.setValueAtTime(Math.max(30, frequency), startAt);
  oscillator.frequency.exponentialRampToValueAtTime(
    Math.max(30, endFrequency),
    startAt + duration,
  );
  const rise = Math.min(Math.max(0.002, attack), duration * 0.8);
  envelope.gain.setValueAtTime(0.0001, startAt);
  envelope.gain.exponentialRampToValueAtTime(Math.max(0.0001, gain), startAt + rise);
  envelope.gain.exponentialRampToValueAtTime(0.0001, startAt + duration);
  oscillator.connect(envelope).connect(destination);
  oscillator.start(startAt);
  oscillator.stop(startAt + duration + 0.02);
}

function scheduleSynthNoise(context, destination, startAt, {
  duration = 0.06,
  gain = 0.08,
  frequency = 420,
}) {
  const frameCount = Math.max(1, Math.floor(context.sampleRate * duration));
  const buffer = context.createBuffer(1, frameCount, context.sampleRate);
  const channel = buffer.getChannelData(0);
  for (let index = 0; index < frameCount; index += 1) {
    const decay = 1 - index / frameCount;
    channel[index] = (Math.random() * 2 - 1) * decay;
  }

  const source = context.createBufferSource();
  const filter = context.createBiquadFilter();
  const envelope = context.createGain();
  filter.type = "lowpass";
  filter.frequency.setValueAtTime(frequency, startAt);
  filter.Q.setValueAtTime(0.7, startAt);
  envelope.gain.setValueAtTime(Math.max(0.0001, gain), startAt);
  envelope.gain.exponentialRampToValueAtTime(0.0001, startAt + duration);
  source.buffer = buffer;
  source.connect(filter).connect(envelope).connect(destination);
  source.start(startAt);
  source.stop(startAt + duration + 0.02);
}

function playProceduralSound(name, { volume = 1, rate = 1 } = {}) {
  const context = app.audioContext;
  if (!context || context.state === "closed") {
    return;
  }
  if (context.state === "suspended") {
    context.resume().catch(() => {});
  }

  const speed = Math.max(0.5, Math.min(2, rate));
  const master = context.createGain();
  // Ceiling is above 1.0 so specific sounds (button, move) can be amplified
  // past unity gain; the synth tones peak at ~0.12 internally, so headroom is
  // large and there is no clipping risk.
  master.gain.value = Math.max(0, Math.min(6, app.soundVolume * volume));
  master.connect(context.destination);
  const now = context.currentTime + 0.004;
  const tone = (at, options) => scheduleSynthTone(context, master, now + at / speed, {
    ...options,
    frequency: options.frequency * speed,
    endFrequency: (options.endFrequency || options.frequency) * speed,
    duration: options.duration / speed,
  });
  const noise = (at, options) => scheduleSynthNoise(context, master, now + at / speed, {
    ...options,
    duration: options.duration / speed,
    frequency: options.frequency * speed,
  });

  if (name === "button") {
    tone(0, { frequency: 480, endFrequency: 320, duration: 0.045, gain: 0.12, type: "triangle" });
  } else if (name === "move_self" || name === "move_opponent") {
    const pitch = name === "move_self" ? 142 : 118;
    noise(0, { duration: 0.055, gain: 0.12, frequency: 520 });
    tone(0, { frequency: pitch, endFrequency: pitch * 0.72, duration: 0.07, gain: 0.1, type: "sine" });
  } else if (name === "capture") {
    // Heavier, grittier impact than a normal move: a longer low-frequency
    // crunch plus a deeper thump, so a capture is unmistakable by ear.
    noise(0, { duration: 0.11, gain: 0.2, frequency: 300 });
    tone(0, { frequency: 140, endFrequency: 46, duration: 0.17, gain: 0.14, type: "triangle" });
  } else if (name === "castle") {
    for (const at of [0, 0.085]) {
      noise(at, { duration: 0.05, gain: 0.11, frequency: 480 });
      tone(at, { frequency: 132, endFrequency: 92, duration: 0.065, gain: 0.09, type: "sine" });
    }
  } else if (name === "promote") {
    [392, 523.25, 659.25, 783.99].forEach((frequency, index) => {
      tone(index * 0.055, { frequency, duration: 0.12, gain: 0.065, type: "sine" });
    });
  } else if (name === "check") {
    tone(0, { frequency: 260, endFrequency: 330, duration: 0.085, gain: 0.095, type: "triangle" });
    tone(0.065, { frequency: 520, endFrequency: 610, duration: 0.13, gain: 0.11, type: "triangle" });
  } else if (name === "illegal") {
    tone(0, { frequency: 180, endFrequency: 105, duration: 0.16, gain: 0.1, type: "sawtooth" });
  } else if (name === "game_start") {
    [196, 293.66, 392].forEach((frequency, index) => {
      tone(index * 0.07, { frequency, endFrequency: frequency * 1.04, duration: 0.2, gain: 0.07, type: "sine" });
    });
  } else if (name === "game_end") {
    [392, 293.66, 196].forEach((frequency, index) => {
      tone(index * 0.075, { frequency, endFrequency: frequency * 0.9, duration: 0.2, gain: 0.065, type: "triangle" });
    });
  } else if (name === "boss_rumble") {
    // The disturbance: a hard impact, then rockfall noise over a deep groan
    // that bends downward like something vast shifting its weight.
    noise(0, { duration: 0.16, gain: 0.42, frequency: 140 });
    tone(0, { frequency: 92, endFrequency: 30, duration: 0.5, gain: 0.26, type: "sine" });
    noise(0.06, { duration: 1.3, gain: 0.34, frequency: 95 });
    noise(0.2, { duration: 0.95, gain: 0.2, frequency: 180 });
    tone(0.1, { frequency: 56, endFrequency: 32, duration: 1.55, gain: 0.2, type: "triangle" });
    tone(0.16, { frequency: 112, endFrequency: 55, duration: 1.05, gain: 0.08, type: "sawtooth" });
  } else if (name === "boss_reveal") {
    // The name card: a slow low swell (open fifth) with a breath of air.
    tone(0, { frequency: 49, duration: 2.8, gain: 0.12, type: "sine", attack: 0.9 });
    tone(0.12, { frequency: 98, duration: 2.5, gain: 0.09, type: "triangle", attack: 0.85 });
    tone(0.25, { frequency: 146.83, duration: 2.3, gain: 0.05, type: "triangle", attack: 0.75 });
    noise(0.2, { duration: 1.9, gain: 0.045, frequency: 240 });
  }
}

function syncMenuMusic({ force = false, immediate = false } = {}) {
  const music = app.musicAudio;
  if (!music) {
    return;
  }

  // Hold the menu music back until the intro has fully departed — the cave
  // belongs to the rumble and the reveal swell. finishIntro() force-syncs,
  // so the music fades in the moment the menu actually appears.
  const shouldRun = app.musicEnabled && app.mode === "menu" && app.intro.complete;
  const shouldPlay = shouldRun && !document.hidden;
  const target = shouldPlay ? app.musicVolume : 0;
  if (
    !force
    && app.musicShouldRun === shouldRun
    && app.musicShouldPlay === shouldPlay
    && app.musicFadeTarget === target
  ) {
    return;
  }

  app.musicShouldRun = shouldRun;
  app.musicShouldPlay = shouldPlay;
  app.musicFadeTarget = target;
  if (app.musicFadeFrame !== null) {
    cancelAnimationFrame(app.musicFadeFrame);
    app.musicFadeFrame = null;
  }

  if (shouldPlay) {
    music.play().catch(() => {});
  }

  const from = music.volume;
  const duration = immediate ? 0 : shouldPlay ? 850 : 520;
  const startedAt = performance.now();
  const finish = () => {
    music.volume = target;
    app.musicFadeFrame = null;
    if (!shouldRun) {
      music.pause();
      music.currentTime = 0;
    }
  };

  if (duration === 0 || Math.abs(from - target) < 0.005) {
    finish();
    return;
  }

  const fade = (now) => {
    const progress = Math.min(1, (now - startedAt) / duration);
    const eased = progress * progress * (3 - 2 * progress);
    music.volume = clampNumber(from + (target - from) * eased, 0, 1);
    if (progress >= 1) {
      finish();
      return;
    }
    app.musicFadeFrame = requestAnimationFrame(fade);
  };
  app.musicFadeFrame = requestAnimationFrame(fade);
}

function gameMusicIntensity() {
  const cp = Math.abs(Number(app.latestEval?.value) || 0);
  const lowestClock = Math.min(visibleClock("white"), visibleClock("black"));
  const forcedMate = app.latestEval?.kind === "mate" || cp >= 90000;
  if (forcedMate || lowestClock <= 15 || cp >= 700) {
    return 1;
  }
  if (app.inCheck || lowestClock <= 45 || cp >= 350) {
    return 0.58;
  }
  const material = (Number(app.material?.white) || 0) + (Number(app.material?.black) || 0);
  if (material > 0 && material <= 34) {
    return 0.34;
  }
  return 0;
}

function syncGameMusic({ force = false, immediate = false } = {}) {
  const pulse = app.gameMusicAudio.pulse;
  const urgent = app.gameMusicAudio.urgent;
  if (!pulse || !urgent) {
    return;
  }

  const shouldRun =
    app.gameMusicEnabled &&
    app.mode === "game" &&
    app.humanSide !== null &&
    !app.gameOver;
  const shouldPlay = shouldRun && !document.hidden;
  const intensity = shouldPlay ? gameMusicIntensity() : 0;
  const targets = {
    pulse: shouldPlay ? app.gameMusicVolume * (1 - intensity * 0.52) : 0,
    urgent: shouldPlay ? app.gameMusicVolume * intensity * 0.72 : 0,
  };
  const mixKey = `${shouldRun}:${shouldPlay}:${targets.pulse.toFixed(3)}:${targets.urgent.toFixed(3)}`;
  if (!force && app.gameMusicMixKey === mixKey) {
    return;
  }
  app.gameMusicMixKey = mixKey;

  if (app.gameMusicFadeFrame !== null) {
    cancelAnimationFrame(app.gameMusicFadeFrame);
    app.gameMusicFadeFrame = null;
  }
  if (shouldPlay) {
    pulse.play().catch(() => {});
    if (targets.urgent > 0) {
      urgent.play().catch(() => {});
    }
  }

  const from = { pulse: pulse.volume, urgent: urgent.volume };
  const duration = immediate ? 0 : shouldPlay ? 3200 : 780;
  const startedAt = performance.now();
  const finish = () => {
    pulse.volume = targets.pulse;
    urgent.volume = targets.urgent;
    app.gameMusicFadeFrame = null;
    if (!shouldRun) {
      for (const track of [pulse, urgent]) {
        track.pause();
        track.currentTime = 0;
      }
    } else if (!document.hidden && targets.urgent === 0) {
      urgent.pause();
      urgent.currentTime = 0;
    }
  };

  if (duration === 0) {
    finish();
    return;
  }
  const fade = (now) => {
    const progress = Math.min(1, (now - startedAt) / duration);
    const eased = progress * progress * (3 - 2 * progress);
    pulse.volume = clampNumber(from.pulse + (targets.pulse - from.pulse) * eased, 0, 1);
    urgent.volume = clampNumber(from.urgent + (targets.urgent - from.urgent) * eased, 0, 1);
    if (progress >= 1) {
      finish();
      return;
    }
    app.gameMusicFadeFrame = requestAnimationFrame(fade);
  };
  app.gameMusicFadeFrame = requestAnimationFrame(fade);
}

function playSound(name, { volume = 1, rate = 1, delay = 0, condition = null } = {}) {
  const procedural = PROCEDURAL_SOUND_NAMES.has(name);
  if (!app.soundEnabled || (!app.audio[name] && !procedural)) {
    return;
  }

  const start = () => {
    if (!app.soundEnabled || (condition && !condition())) {
      return;
    }
    if (procedural) {
      playProceduralSound(name, { volume, rate });
      return;
    }
    try {
      const audio = app.audio[name].cloneNode(true);
      audio.volume = Math.max(0, Math.min(1, app.soundVolume * volume));
      audio.playbackRate = Math.max(0.5, Math.min(2, rate));
      audio.play().catch(() => {});
    } catch {
      // Browsers may block audio before the first user gesture.
    }
  };

  if (delay > 0) {
    window.setTimeout(start, delay);
  } else {
    start();
  }
}

// Scored to the 4200ms checkmate reveal on the board, so the sounds land
// on the visuals instead of arriving with the modal afterwards. Sgurr's
// feast and Sgurr's death take different scores; each leaves the result
// modal to play only a quiet epilogue.
function playCheckmateRevealSound(humanWon) {
  const during = () => app.mode === "game" && app.gameOver && app.reason === "checkmate";
  if (humanWon) {
    // the eye arrives guttering, keens as it convulses, and ruptures
    playSound("result_sgurr_energy", { volume: 0.42, rate: 1.12 });
    playSound("result_sgurr_alien", { volume: 0.5, rate: 0.68, delay: 1450, condition: during });
    playSound("result_human_explosion", { volume: 0.95, delay: 2950, condition: during });
    return;
  }
  // the feast: a rumble as the eye materialises, a hum as it regards the
  // king, the wet swallow as he goes down, a bright call at the blink
  playSound("boss_rumble", { volume: 0.45, rate: 1.25 });
  playSound("result_sgurr_energy", { volume: 0.4, rate: 0.9, delay: 1300, condition: during });
  playSound("result_sgurr_burble", { volume: 0.85, rate: 0.9, delay: 2750, condition: during });
  playSound("result_sgurr_alien", { volume: 0.55, rate: 1.18, delay: 3350, condition: during });
}

function playResultSound(outcome) {
  // A checkmate with animations on has just played the full board score,
  // so the modal adds only an epilogue. Every other ending (resignation,
  // flag, stalemate, animations off) gets its full account here.
  const revealScored = app.reason === "checkmate" && app.animationMode !== "Off";
  if (outcome === "human-win") {
    // the fanfare stands alone: the modal shows a dead husk, not a blast
    playSound("result_human_victory", { volume: 0.84 });
    return;
  }
  if (outcome === "sgurr-win" || outcome === "watch-white-win" || outcome === "watch-black-win") {
    if (revealScored) {
      // epilogue over the king adrift in the glass: one low call, then a
      // slow burble from somewhere very deep
      playSound("result_sgurr_alien", { volume: 0.4, rate: 0.7 });
      playSound("result_sgurr_burble", { volume: 0.32, rate: 0.68, delay: 480 });
      return;
    }
    const defeatMix = outcome === "sgurr-win" ? 0.4 : 1;
    playSound("result_sgurr_energy", { volume: 0.58 * defeatMix });
    playSound("result_sgurr_alien", { volume: 0.82 * defeatMix, rate: 0.86, delay: 70 });
    playSound("result_sgurr_burble", { volume: 0.58 * defeatMix, rate: 0.78, delay: 190 });
    return;
  }
  playSound("result_draw", { volume: 0.5, rate: 0.92 });
}

function playMoveSound(moveInfo, { byHuman = false } = {}) {
  if (!moveInfo) {
    return;
  }

  const san = moveInfo.san || "";
  const uci = moveInfo.uci || "";

  if (app.gameOver) {
    playSound("game_end");
  } else if (app.inCheck || san.includes("+") || san.includes("#")) {
    playSound("check");
  } else if (san.includes("=") || uci.length === 5) {
    playSound("promote");
  } else if (san.includes("O-O")) {
    playSound("castle");
  } else if (san.includes("x")) {
    playSound("capture", { volume: 2.7 });
  } else {
    playSound(byHuman ? "move_self" : "move_opponent", { volume: 4.0 });
  }
}

export {
  soundUrl,
  initAudio,
  unlockAudio,
  scheduleSynthTone,
  scheduleSynthNoise,
  playProceduralSound,
  syncMenuMusic,
  gameMusicIntensity,
  syncGameMusic,
  playSound,
  playCheckmateRevealSound,
  playResultSound,
  playMoveSound,
};
