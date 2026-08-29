const RAMP_STEPS = 32;
const INTENSITY_STEPS = 24;
const SETTLE_EPSILON = 0.003;
// Exponential easing constants in milliseconds. Motion settles in about 3x each value.
const NODE_TAU = 88;
const AMBIENT_TAU = 150;
const CORE_TAU = 105;
const FEATURE_TRACE_DURATION = 2200;
const NNUE_SCALE = 400;
const NNUE_DIVISOR = 255 * 64;

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function mix(a, b, amount) {
  return a + (b - a) * amount;
}

function percentile(values, ratio = 0.94) {
  const sorted = values
    .filter((value) => Number.isFinite(value))
    .map((value) => Math.abs(value))
    .sort((a, b) => a - b);
  if (!sorted.length) return 1;
  return Math.max(1, sorted[Math.floor((sorted.length - 1) * ratio)]);
}

function parseColour(value, fallback) {
  const match = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(value || "").trim());
  if (!match) return fallback;
  const digits = match[1].length === 3
    ? [...match[1]].map((digit) => digit + digit).join("")
    : match[1];
  return [
    parseInt(digits.slice(0, 2), 16),
    parseInt(digits.slice(2, 4), 16),
    parseInt(digits.slice(4, 6), 16),
  ];
}

function mixColour(from, to, amount) {
  return [
    mix(from[0], to[0], amount),
    mix(from[1], to[1], amount),
    mix(from[2], to[2], amount),
  ];
}

function rgbToHsl([red, green, blue]) {
  const r = red / 255;
  const g = green / 255;
  const b = blue / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const lightness = (max + min) / 2;
  const chroma = max - min;
  if (!chroma) return [0, 0, lightness];
  const saturation = lightness > 0.5 ? chroma / (2 - max - min) : chroma / (max + min);
  let hue;
  if (max === r) hue = (g - b) / chroma + (g < b ? 6 : 0);
  else if (max === g) hue = (b - r) / chroma + 2;
  else hue = (r - g) / chroma + 4;
  return [hue * 60, saturation, lightness];
}

function hslToRgb([hue, saturation, lightness]) {
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const sector = ((hue % 360) + 360) % 360 / 60;
  const second = chroma * (1 - Math.abs((sector % 2) - 1));
  const parts = sector < 1 ? [chroma, second, 0]
    : sector < 2 ? [second, chroma, 0]
      : sector < 3 ? [0, chroma, second]
        : sector < 4 ? [0, second, chroma]
          : sector < 5 ? [second, 0, chroma]
            : [chroma, 0, second];
  const lift = lightness - chroma / 2;
  return parts.map((part) => clamp((part + lift) * 255, 0, 255));
}

function hueGap(a, b) {
  const gap = Math.abs(((a - b) % 360 + 360) % 360);
  return Math.min(gap, 360 - gap);
}

// Use the second accent when the first is too close to the cool pole.
function warmBase(accent, accent2, cool) {
  const coolHue = rgbToHsl(cool)[0];
  return hueGap(rgbToHsl(accent)[0], coolHue) < 45 ? accent2 : accent;
}

// Place clipped-high lanes on a third colour family away from both poles.
function crestHue(warm, cool) {
  const warmHue = rgbToHsl(warm)[0];
  const coolHue = rgbToHsl(cool)[0];
  const options = [warmHue + 120, warmHue - 120];
  return hueGap(options[0], coolHue) >= hueGap(options[1], coolHue) ? options[0] : options[1];
}

// Increase saturation without changing hue.
function vivid(rgb, amount) {
  const grey = (rgb[0] + rgb[1] + rgb[2]) / 3;
  return rgb.map((channel) => clamp(grey + (channel - grey) * (1 + amount), 0, 255));
}

// Lane direction chooses the colour pole and strength chooses its shade.
function poleRamp(base, floor, crest) {
  const stops = [];
  for (let step = 0; step <= INTENSITY_STEPS; step += 1) {
    const amount = step / INTENSITY_STEPS;
    const channels = amount < 0.55
      ? mixColour(floor, base, amount / 0.55)
      : mixColour(base, crest, (amount - 0.55) / 0.45);
    stops.push(channels.map(Math.round));
  }
  return stops;
}

function buildRamp(negative, positive) {
  const dark = [10, 13, 22];
  const warm = vivid(mixColour(positive, [255, 214, 236], 0.34), 0.5);
  const cool = vivid(mixColour(negative, [206, 248, 255], 0.3), 0.35);
  const negativeStops = poleRamp(vivid(negative, 0.25), mixColour(dark, negative, 0.28), cool);
  const positiveStops = poleRamp(vivid(positive, 0.55), mixColour(dark, positive, 0.3), warm);
  // A separate ring marks lanes pinned at the ceiling.
  const crest = hslToRgb([crestHue(positive, negative), 0.58, 0.44]);

  const table = () => {
    const rows = [];
    for (let lean = 0; lean <= RAMP_STEPS; lean += 1) {
      const towardsPositive = lean / RAMP_STEPS;
      const row = [];
      for (let step = 0; step <= INTENSITY_STEPS; step += 1) {
        const channels = mixColour(negativeStops[step], positiveStops[step], towardsPositive);
        const [red, green, blue] = channels.map(Math.round);
        row.push(`rgb(${red}, ${green}, ${blue})`);
      }
      rows.push(row);
    }
    return rows;
  };

  // Lanes clipped to zero use a quieter fourth colour.
  const [restR, restG, restB] = mixColour(mixColour(dark, negative, 0.55), [120, 110, 190], 0.34).map(Math.round);
  const [crestR, crestG, crestB] = crest.map(Math.round);
  const css = table();
  return {
    css,
    warm: css[RAMP_STEPS][INTENSITY_STEPS],
    cool: css[0][INTENSITY_STEPS],
    crest: `rgb(${crestR}, ${crestG}, ${crestB})`,
    dead: `rgb(${restR}, ${restG}, ${restB})`,
  };
}

// Ease by elapsed time so motion is frame-rate independent.
function approach(holder, key, target, blend) {
  const distance = target - holder[key];
  // Use an epsilon because Float32 values may not equal assigned doubles.
  if (Math.abs(distance) <= SETTLE_EPSILON) {
    holder[key] = target;
    return false;
  }
  holder[key] = holder[key] + distance * blend;
  return true;
}

function formatEval(centipawns) {
  const pawns = centipawns / 100;
  const rounded = Math.abs(pawns) < 0.005 ? 0 : pawns;
  return `${rounded >= 0 ? "+" : "−"}${Math.abs(rounded).toFixed(2)}`;
}

function strongestWeights(values, count = 6) {
  const ranked = Array.from(values, (value, index) => ({
    index,
    value,
    strength: Math.abs(value),
  }))
    .sort((a, b) => b.strength - a.strength)
    .slice(0, count);
  const scale = Math.max(1, ranked[0]?.strength || 1);
  return ranked.map((lane) => ({ ...lane, strength: lane.strength / scale }));
}

function cubicPoint(from, controlA, controlB, to, amount) {
  const inverse = 1 - amount;
  return {
    x: inverse ** 3 * from.x
      + 3 * inverse ** 2 * amount * controlA.x
      + 3 * inverse * amount ** 2 * controlB.x
      + amount ** 3 * to.x,
    y: inverse ** 3 * from.y
      + 3 * inverse ** 2 * amount * controlA.y
      + 3 * inverse * amount ** 2 * controlB.y
      + amount ** 3 * to.y,
  };
}

function quadraticPoint(from, control, to, amount) {
  const inverse = 1 - amount;
  return {
    x: inverse ** 2 * from.x + 2 * inverse * amount * control.x + amount ** 2 * to.x,
    y: inverse ** 2 * from.y + 2 * inverse * amount * control.y + amount ** 2 * to.y,
  };
}

class CortexVisual {
  constructor(canvas, onInspect) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.onInspect = onInspect;
    this.transition = null;
    this.phase = "after";
    this.displayMode = "contribution";
    this.anatomyStage = "idle";
    this.anatomyStarted = performance.now();
    this.hovered = null;
    this.locked = null;
    this.width = 0;
    this.height = 0;
    this.lastFrame = 0;
    this.animationFrame = null;
    this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.inViewport = true;
    this.animateUntil = performance.now() + 8000;
    this.grid = { cell: 10, gridWidth: 0, gutter: 42, top: 0, bottom: 0, whiteLeft: 0, blackLeft: 0, inputY: 0 };
    this.meshPath = null;
    this.glowKey = "";
    this.glowCache = null;
    this.contributionScale = 1;
    this.contributionDeltaScale = 1;
    this.deltaScale = 1;
    this.valueCache = new Map();
    this.connectionCache = null;
    this.nodeIntensity = new Float32Array(768);
    this.nodePolarity = new Float32Array(768);
    this.nodeActivity = new Float32Array(768);
    this.nodeSaturation = new Float32Array(768);
    this.nodeDead = new Float32Array(768);
    this.latticeCache = null;
    this.focusWeight = new Float32Array(768);
    this.focusTarget = new Float32Array(768);
    this.focusOn = false;
    this.focusFade = 0;
    this.featureTrace = null;
    this.scratch = { value: 0, intensity: 0, activity: 0, polarity: 0, saturation: 0, dead: 0 };
    this.corePolarity = 1;
    this.coreBoost = 0;
    this.motionPrimed = false;
    this.settled = true;
    this.rampCache = null;
    this.rampKey = "";
    this.canvas.dataset.displayMode = this.displayMode;
    this.canvas.dataset.anatomy = this.anatomyStage;
    this.canvas.dataset.motion = "settled";
    this.canvas.dataset.feature = "idle";
    this.canvas.dataset.trace = "idle";

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    if ("IntersectionObserver" in window) {
      this.intersectionObserver = new IntersectionObserver(([entry]) => {
        this.inViewport = entry.isIntersecting;
        if (this.inViewport) this.wake(1800);
      }, { threshold: 0.01 });
      this.intersectionObserver.observe(canvas);
    }
    canvas.addEventListener("pointermove", (event) => this.handlePointer(event));
    canvas.addEventListener("pointerleave", () => {
      if (!this.locked) {
        this.hovered = null;
        this.onInspect?.(null);
        this.wake(300);
      }
    });
    canvas.addEventListener("click", (event) => {
      const target = this.targetFromPointer(event);
      const sameTarget = target
        && this.locked
        && target.perspective === this.locked.perspective
        && target.index === this.locked.index;
      if (!target || sameTarget) {
        this.locked = null;
        this.hovered = null;
        this.onInspect?.(null);
      } else {
        this.hovered = target;
        this.locked = { ...target };
        this.onInspect?.(this.laneDetails(this.locked));
      }
      this.wake(1800);
      this.draw(performance.now());
    });
    canvas.addEventListener("keydown", (event) => this.handleKey(event));
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) this.wake(1800);
    });
    this.resize();
  }

  setTransition(transition) {
    this.transition = transition;
    this.valueCache.clear();
    this.connectionCache = null;
    this.latticeCache = null;
    const afterValues = [
      ...transition.after.whiteContribution,
      ...transition.after.blackContribution,
    ];
    const deltaValues = [...transition.whiteDelta, ...transition.blackDelta];
    this.contributionScale = percentile(afterValues);
    if (transition.before) {
      const beforeSign = transition.before.sideToMove === 0 ? 1 : -1;
      const afterSign = transition.after.sideToMove === 0 ? 1 : -1;
      const contributionDeltas = [];
      for (const perspective of ["white", "black"]) {
        const beforeValues = perspective === "white"
          ? transition.before.whiteContribution
          : transition.before.blackContribution;
        const afterPerspectiveValues = perspective === "white"
          ? transition.after.whiteContribution
          : transition.after.blackContribution;
        for (let index = 0; index < 384; index += 1) {
          contributionDeltas.push(afterPerspectiveValues[index] * afterSign - beforeValues[index] * beforeSign);
        }
      }
      this.contributionDeltaScale = percentile(contributionDeltas);
    } else {
      this.contributionDeltaScale = this.contributionScale;
    }
    this.deltaScale = percentile(deltaValues);
    this.locked = null;
    this.hovered = null;
    this.featureTrace = null;
    this.canvas.dataset.trace = "idle";
    this.wake();
  }

  setPhase(phase) {
    this.phase = phase;
    this.connectionCache = null;
    this.latticeCache = null;
    this.wake(2400);
  }

  setDisplayMode(mode) {
    if (!["contribution", "change", "activation", "clipped"].includes(mode)) return;
    this.displayMode = mode;
    this.connectionCache = null;
    this.latticeCache = null;
    this.canvas.dataset.displayMode = mode;
    this.wake(2400);
  }

  rankConnections() {
    const candidates = [];
    for (const perspective of ["white", "black"]) {
      for (let index = 0; index < 384; index += 1) {
        const state = this.nodeState(perspective, index);
        candidates.push({ perspective, index, strength: state.intensity, positive: state.value >= 0 });
      }
    }
    candidates.sort((a, b) => b.strength - a.strength);
    return candidates.slice(0, 42);
  }

  // Normalise driven lane magnitudes against their combined 88th percentile.
  setFocus(whiteValues, blackValues) {
    if (!whiteValues || !blackValues) {
      this.focusTarget.fill(0);
      this.focusOn = false;
      this.canvas.dataset.feature = "idle";
      this.wake(2200);
      return;
    }
    const scale = percentile([...whiteValues, ...blackValues], 0.88);
    for (let index = 0; index < 384; index += 1) {
      this.focusTarget[index] = clamp(Math.abs(whiteValues[index]) / scale, 0, 1) ** 1.5;
      this.focusTarget[384 + index] = clamp(Math.abs(blackValues[index]) / scale, 0, 1) ** 1.5;
    }
    this.focusOn = true;
    this.canvas.dataset.feature = "active";
    this.wake(2600);
  }

  setFeatureTrace({ piece, whiteIndex, blackIndex, whiteWeights, blackWeights }) {
    this.setFocus(whiteWeights, blackWeights);
    this.featureTrace = {
      piece,
      whiteIndex,
      blackIndex,
      lanes: {
        white: strongestWeights(whiteWeights),
        black: strongestWeights(blackWeights),
      },
      started: performance.now(),
    };
    this.canvas.dataset.trace = this.reducedMotion ? "ready" : "playing";
    this.wake(FEATURE_TRACE_DURATION + 400);
  }

  replayFeatureTrace() {
    if (!this.featureTrace) return;
    this.featureTrace.started = performance.now();
    this.canvas.dataset.trace = this.reducedMotion ? "ready" : "playing";
    this.wake(FEATURE_TRACE_DURATION + 400);
  }

  focusChangedLanes() {
    if (!this.transition?.before) return;
    this.setFocus(this.transition.whiteDelta, this.transition.blackDelta);
  }

  clearFocus() {
    this.featureTrace = null;
    this.canvas.dataset.trace = "idle";
    this.setFocus(null, null);
  }

  selectLane(target) {
    if (!target || !["white", "black"].includes(target.perspective)) return;
    if (!Number.isInteger(target.index) || target.index < 0 || target.index >= 384) return;
    this.locked = { perspective: target.perspective, index: target.index };
    this.hovered = this.locked;
    this.onInspect?.(this.laneDetails(this.locked));
    this.wake(1600);
    this.draw(performance.now());
  }

  setAnatomyStage(stage) {
    this.anatomyStage = stage;
    this.anatomyStarted = performance.now();
    this.canvas.dataset.anatomy = stage;
    this.wake(stage === "idle" ? 800 : 2200);
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    this.width = Math.max(1, rect.width);
    this.height = Math.max(380, rect.height);
    this.canvas.width = Math.round(this.width * dpr);
    this.canvas.height = Math.round(this.height * dpr);
    this.context.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.computeLayout();
    this.draw(performance.now());
  }

  start() {
    if (this.animationFrame !== null || document.hidden || !this.inViewport) return;
    this.animationFrame = requestAnimationFrame((time) => this.frame(time));
  }

  wake(duration = 8000) {
    this.animateUntil = Math.max(this.animateUntil, performance.now() + duration);
    this.start();
  }

  frame(time) {
    this.animationFrame = null;
    // Draw at display rate while easing, then return to idle cadence.
    const gate = this.settled ? 42 : 0;
    if (time - this.lastFrame < gate && !this.reducedMotion) {
      this.start();
      return;
    }
    const delta = clamp(time - this.lastFrame, 1, 120);
    this.lastFrame = time;
    this.advance(delta);
    this.draw(time);
    if (!this.settled || (!this.reducedMotion && time < this.animateUntil)) this.start();
  }

  // Ease displayed values towards network state so every change fades.
  advance(delta) {
    const instant = this.reducedMotion || !this.motionPrimed;
    const nodeBlend = instant ? 1 : 1 - Math.exp(-delta / NODE_TAU);
    const ambientBlend = instant ? 1 : 1 - Math.exp(-delta / AMBIENT_TAU);
    const coreBlend = instant ? 1 : 1 - Math.exp(-delta / CORE_TAU);
    let moving = false;

    if (this.transition) {
      for (const perspective of ["white", "black"]) {
        const base = perspective === "white" ? 0 : 384;
        const values = this.valuesFor(perspective);
        for (let index = 0; index < 384; index += 1) {
          const slot = base + index;
          const target = this.measureNode(perspective, index, values, this.scratch);
          moving = approach(this.nodeIntensity, slot, target.intensity, nodeBlend) || moving;
          moving = approach(this.nodePolarity, slot, target.polarity, nodeBlend) || moving;
          moving = approach(this.nodeActivity, slot, target.activity, nodeBlend) || moving;
          moving = approach(this.nodeSaturation, slot, target.saturation, nodeBlend) || moving;
          const wasDead = this.nodeDead[slot] > 0.5;
          moving = approach(this.nodeDead, slot, target.dead, nodeBlend) || moving;
          if (wasDead !== (this.nodeDead[slot] > 0.5)) this.latticeCache = null;
        }
      }
      this.motionPrimed = true;
    }

    for (let slot = 0; slot < 768; slot += 1) {
      moving = approach(this.focusWeight, slot, this.focusTarget[slot], nodeBlend) || moving;
    }
    moving = approach(this, "focusFade", this.focusOn ? 1 : 0, ambientBlend) || moving;
    moving = approach(this, "coreBoost", this.anatomyStage === "output" ? 5 : 0, coreBlend) || moving;
    moving = approach(this, "corePolarity", this.evaluation() >= 0 ? 1 : -1, coreBlend) || moving;
    if (this.settled === moving) {
      this.settled = !moving;
      this.canvas.dataset.motion = this.settled ? "settled" : "settling";
    }
  }

  evaluation() {
    if (!this.transition) return 0;
    if (this.phase === "delta" && this.transition.before) {
      return this.transition.after.whiteRelative - this.transition.before.whiteRelative;
    }
    const snapshot = this.phase === "before" && this.transition.before
      ? this.transition.before
      : this.transition.after;
    return snapshot.whiteRelative;
  }

  colourRamp(palette) {
    const key = `${palette.accent}|${palette.accent2}|${palette.blue}`;
    if (this.rampKey !== key) {
      const cool = parseColour(palette.blue, [112, 215, 255]);
      const warm = warmBase(
        parseColour(palette.accent, [226, 177, 71]),
        parseColour(palette.accent2, [201, 111, 58]),
        cool,
      );
      this.rampCache = buildRamp(cool, warm);
      this.rampKey = key;
      const deck = this.canvas.closest(".cortex-deck");
      deck?.style.setProperty("--nnue-warm", this.rampCache.warm);
      deck?.style.setProperty("--nnue-cool", this.rampCache.cool);
      deck?.style.setProperty("--nnue-crest", this.rampCache.crest);
      deck?.style.setProperty("--nnue-dead", this.rampCache.dead);
    }
    return this.rampCache;
  }

  rampIndex(polarity) {
    return Math.round((clamp(polarity, -1, 1) + 1) * (RAMP_STEPS / 2));
  }

  rampColour(ramp, polarity, intensity = 1) {
    return ramp.css[this.rampIndex(polarity)][Math.round(clamp(intensity, 0, 1) * INTENSITY_STEPS)];
  }

  palette() {
    const styles = getComputedStyle(document.documentElement);
    const frost = document.documentElement.dataset.theme === "frost";
    return {
      accent: frost ? "#62d9e8" : styles.getPropertyValue("--accent").trim() || "#e2b147",
      accent2: frost ? "#ed8d70" : styles.getPropertyValue("--accent-2").trim() || "#c96f3a",
      text: "#edf6ff",
      muted: "#91a4ba",
      edge: "#536981",
      blue: "#70d7ff",
      void: "#070a11",
    };
  }

  // Each accumulator is a 16 by 24 row-major grid of square cells.
  computeLayout() {
    const header = 30;
    // Place network inputs above the accumulators with room for strands and labels.
    const inputBand = clamp(this.height * 0.15, 78, 132);
    const footer = clamp(this.height * 0.17, 86, 138);
    const usableHeight = Math.max(60, this.height - header - inputBand - footer);
    const gutter = 42;
    const gap = clamp(this.width * 0.062, 40, 78);
    const panelWidth = (this.width - gutter * 2 - gap) / 2;
    const cell = Math.max(4, Math.min(panelWidth / 15, usableHeight / 23));
    const gridWidth = cell * 15;
    const left = gutter + (this.width - gutter * 2 - (gridWidth * 2 + gap)) / 2;
    const top = header + inputBand + (usableHeight - cell * 23) / 2;
    this.grid = {
      cell,
      gridWidth,
      gutter,
      top,
      bottom: top + cell * 23,
      whiteLeft: left,
      blackLeft: left + gridWidth + gap,
      inputY: header + inputBand * 0.46,
    };
    this.meshPath = null;
    this.glowKey = "";
    this.latticeCache = null;
  }

  point(perspective, index) {
    const left = perspective === "white" ? this.grid.whiteLeft : this.grid.blackLeft;
    return {
      x: left + (index % 16) * this.grid.cell,
      y: this.grid.top + Math.floor(index / 16) * this.grid.cell,
    };
  }

  coreCentre() {
    return {
      x: this.width * 0.5,
      y: this.grid.bottom + (this.height - this.grid.bottom) * 0.46,
    };
  }

  valuesFor(perspective) {
    if (!this.transition) return null;
    const cached = this.valueCache.get(`${this.phase}:${perspective}`);
    if (cached) return cached;
    const values = this.buildValues(perspective);
    this.valueCache.set(`${this.phase}:${perspective}`, values);
    return values;
  }

  buildValues(perspective) {
    const before = this.transition.before || this.transition.after;
    const after = this.transition.after;
    const snapshot = this.phase === "before" ? before : after;
    const white = perspective === "white";
    const signed = new Float32Array(384);
    if (this.phase === "delta" && this.transition.before) {
      const beforeContribution = white ? before.whiteContribution : before.blackContribution;
      const afterContribution = white ? after.whiteContribution : after.blackContribution;
      const beforeSign = before.sideToMove === 0 ? 1 : -1;
      const afterSign = after.sideToMove === 0 ? 1 : -1;
      for (let index = 0; index < 384; index += 1) {
        signed[index] = afterContribution[index] * afterSign - beforeContribution[index] * beforeSign;
      }
    } else {
      const contribution = white ? snapshot.whiteContribution : snapshot.blackContribution;
      const sign = snapshot.sideToMove === 0 ? 1 : -1;
      for (let index = 0; index < 384; index += 1) {
        signed[index] = contribution[index] * sign;
      }
    }
    return {
      accumulator: white ? snapshot.whiteAccumulator : snapshot.blackAccumulator,
      activation: white ? snapshot.whiteActivation : snapshot.blackActivation,
      delta: white ? this.transition.whiteDelta : this.transition.blackDelta,
      signed,
    };
  }

  // Fill `out` with this lane's display values.
  // `polarity` is -1 for the cyan end of the ramp and +1 for the warm end.
  measureNode(perspective, index, values, out) {
    if (this.displayMode === "change") {
      const value = values.delta[index];
      out.value = value;
      out.intensity = clamp(Math.abs(value) / this.deltaScale, 0, 1);
      out.activity = value === 0 ? 0 : 1;
      out.polarity = value >= 0 ? 1 : -1;
      out.saturation = 0;
      out.dead = values.activation[index] === 0 ? 1 : 0;
      return out;
    }
    if (this.displayMode === "activation") {
      const value = values.activation[index];
      out.value = value;
      out.intensity = value / 255;
      out.activity = value > 0 ? 1 : 0;
      out.polarity = perspective === "white" ? 1 : -1;
      out.saturation = value >= 255 ? 1 : 0;
      out.dead = value === 0 ? 1 : 0;
      return out;
    }
    if (this.displayMode === "clipped") {
      const raw = values.accumulator[index];
      const high = raw >= 255;
      const low = raw <= 0;
      out.value = high ? 1 : low ? -1 : 0;
      out.intensity = high || low ? 1 : 0;
      out.activity = high || low ? 1 : 0;
      out.polarity = high ? 1 : -1;
      out.saturation = high ? 1 : 0;
      out.dead = low ? 1 : 0;
      return out;
    }
    const value = values.signed[index];
    const scale = this.phase === "delta" && this.transition.before
      ? this.contributionDeltaScale
      : this.contributionScale;
    out.value = value;
    out.intensity = clamp(Math.abs(value) / scale, 0, 1);
    out.activity = values.activation[index] > 0 || (this.phase === "delta" && value !== 0) ? 1 : 0;
    out.polarity = value >= 0 ? 1 : -1;
    out.saturation = values.activation[index] >= 255 ? 1 : 0;
    out.dead = values.activation[index] === 0 ? 1 : 0;
    return out;
  }

  nodeState(perspective, index) {
    const target = this.measureNode(perspective, index, this.valuesFor(perspective), this.scratch);
    return {
      value: target.value,
      intensity: target.intensity,
    };
  }

  laneDetails(target) {
    const values = this.valuesFor(target.perspective);
    if (!values) return null;
    const laneIn = (snapshot) => {
      const white = target.perspective === "white";
      const raw = white ? snapshot.whiteAccumulator[target.index] : snapshot.blackAccumulator[target.index];
      const activation = white ? snapshot.whiteActivation[target.index] : snapshot.blackActivation[target.index];
      const weight = white ? snapshot.whiteOutputWeights[target.index] : snapshot.blackOutputWeights[target.index];
      const whiteSign = snapshot.sideToMove === 0 ? 1 : -1;
      const signedWeight = weight * whiteSign;
      const product = activation * signedWeight;
      const sideToMoveHalf = white
        ? snapshot.sideToMove === 0
        : snapshot.sideToMove === 1;
      return {
        raw,
        activation,
        weight,
        signedWeight,
        product,
        outputHalf: sideToMoveHalf ? "side to move" : "other side",
      };
    };
    const snapshot = this.phase === "before" && this.transition.before
      ? this.transition.before
      : this.transition.after;
    const shown = laneIn(snapshot);
    const contribution = values.signed[target.index];
    const before = this.phase === "delta" && this.transition.before
      ? laneIn(this.transition.before)
      : null;
    const after = this.phase === "delta" ? laneIn(this.transition.after) : shown;
    return {
      ...target,
      phase: this.phase,
      raw: shown.raw,
      clipped: shown.activation,
      delta: values.delta[target.index],
      weight: shown.weight,
      signedWeight: shown.signedWeight,
      product: shown.product,
      contribution,
      outputHalf: shown.outputHalf,
      centipawns: contribution * NNUE_SCALE / NNUE_DIVISOR,
      equation: {
        kind: before ? "delta" : "lane",
        before,
        after,
        scale: NNUE_SCALE,
        divisor: NNUE_DIVISOR,
      },
    };
  }

  targetFromPointer(event) {
    if (!this.transition) return null;
    const rect = this.canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let closest = null;
    let bestDistance = 12;
    for (const perspective of ["white", "black"]) {
      for (let index = 0; index < 384; index += 1) {
        const point = this.point(perspective, index);
        const distance = Math.hypot(point.x - x, point.y - y);
        if (distance < bestDistance) {
          bestDistance = distance;
          closest = { perspective, index };
        }
      }
    }
    return closest;
  }

  handlePointer(event) {
    if (this.locked) return;
    this.hovered = this.targetFromPointer(event);
    this.onInspect?.(this.hovered ? this.laneDetails(this.hovered) : null);
    this.wake(1200);
  }

  handleKey(event) {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Escape"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Escape") {
      this.locked = null;
      this.hovered = null;
      this.onInspect?.(null);
      this.draw(performance.now());
      return;
    }
    const current = this.locked || this.hovered || { perspective: "white", index: 0 };
    const row = Math.floor(current.index / 16);
    const column = current.index % 16;
    const next = { ...current };
    if (event.key === "ArrowUp") next.index = Math.max(0, row - 1) * 16 + column;
    if (event.key === "ArrowDown") next.index = Math.min(23, row + 1) * 16 + column;
    if (event.key === "ArrowLeft") {
      if (column > 0) next.index -= 1;
      else if (current.perspective === "black") {
        next.perspective = "white";
        next.index = row * 16 + 15;
      }
    }
    if (event.key === "ArrowRight") {
      if (column < 15) next.index += 1;
      else if (current.perspective === "white") {
        next.perspective = "black";
        next.index = row * 16;
      }
    }
    this.locked = next;
    this.hovered = next;
    this.onInspect?.(this.laneDetails(next));
    this.wake(1200);
    this.draw(performance.now());
  }

  // Build each accumulator lattice once per layout.
  ensureMesh() {
    if (this.meshPath) return this.meshPath;
    const mesh = new Path2D();
    for (const perspective of ["white", "black"]) {
      for (let row = 0; row < 24; row += 1) {
        const from = this.point(perspective, row * 16);
        const to = this.point(perspective, row * 16 + 15);
        mesh.moveTo(from.x, from.y);
        mesh.lineTo(to.x, to.y);
      }
      for (let column = 0; column < 16; column += 1) {
        const from = this.point(perspective, column);
        const to = this.point(perspective, 23 * 16 + column);
        mesh.moveTo(from.x, from.y);
        mesh.lineTo(to.x, to.y);
      }
    }
    this.meshPath = mesh;
    return mesh;
  }

  drawMesh(context, palette) {
    context.save();
    context.globalAlpha = 0.09;
    context.strokeStyle = palette.edge;
    context.lineWidth = 0.5;
    context.stroke(this.ensureMesh());
    context.restore();
  }

  // Where every input strand gathers before entering its accumulator.
  collector(perspective) {
    const left = perspective === "white" ? this.grid.whiteLeft : this.grid.blackLeft;
    return { x: left + this.grid.gridWidth / 2, y: mix(this.grid.inputY, this.grid.top, 0.48) };
  }

  // Two gradients that change with the layout, not with every frame.
  collectorGlows(context, palette) {
    const key = `${palette.blue}|${Math.round(this.grid.top)}|${Math.round(this.grid.whiteLeft)}`;
    if (this.glowKey === key && this.glowCache) return this.glowCache;
    this.glowCache = ["white", "black"].map((perspective) => {
      const target = this.collector(perspective);
      const glow = context.createRadialGradient(target.x, target.y, 0, target.x, target.y, 11);
      glow.addColorStop(0, `${palette.blue}55`);
      glow.addColorStop(1, `${palette.blue}00`);
      return glow;
    });
    this.glowKey = key;
    return this.glowCache;
  }

  // Each piece selects one row in both accumulators.
  drawInputs(context, palette, time) {
    if (!this.transition) return;
    const snapshot = this.phase === "before" && this.transition.before
      ? this.transition.before
      : this.transition.after;
    const features = snapshot.activeFeatures;
    if (!features || !features.length) return;
    const span = this.width - this.grid.gutter * 2;
    const step = span / Math.max(1, features.length - 1);
    const y = this.grid.inputY;
    const white = this.collector("white");
    const black = this.collector("black");

    context.save();
    context.lineWidth = 0.6;
    for (let index = 0; index < features.length; index += 1) {
      const x = this.grid.gutter + index * step;
      const light = features[index].colour === 0;
      context.globalAlpha = 0.15;
      context.strokeStyle = light ? palette.accent : palette.blue;
      for (const target of [white, black]) {
        context.beginPath();
        context.moveTo(x, y + 4);
        context.bezierCurveTo(x, y + (target.y - y) * 0.7, target.x, y + (target.y - y) * 0.5, target.x, target.y);
        context.stroke();
      }
    }

    const glows = this.collectorGlows(context, palette);
    context.globalAlpha = 1;
    for (let side = 0; side < 2; side += 1) {
      const target = side === 0 ? white : black;
      context.fillStyle = glows[side];
      context.beginPath();
      context.arc(target.x, target.y, 11, 0, Math.PI * 2);
      context.fill();
    }

    context.lineWidth = 1;
    for (let index = 0; index < features.length; index += 1) {
      const x = this.grid.gutter + index * step;
      const light = features[index].colour === 0;
      const breathe = this.reducedMotion ? 0 : Math.sin(time / 1100 + index * 0.5) * 0.4;
      context.globalAlpha = 0.9;
      context.fillStyle = light ? palette.text : palette.void;
      context.strokeStyle = light ? palette.accent : palette.blue;
      context.beginPath();
      context.arc(x, y, 3 + breathe, 0, Math.PI * 2);
      context.fill();
      context.stroke();
    }
    context.restore();
  }

  drawSignalTrace(context, palette, time) {
    if (!this.featureTrace || !this.transition) return;
    const snapshot = this.phase === "before" && this.transition.before
      ? this.transition.before
      : this.transition.after;
    const featureSlot = snapshot.activeFeatures.findIndex((feature) => (
      feature.squareName === this.featureTrace.piece.squareName
      && feature.piece === this.featureTrace.piece.piece
    ));
    if (featureSlot < 0) return;

    const features = snapshot.activeFeatures;
    const span = this.width - this.grid.gutter * 2;
    const step = span / Math.max(1, features.length - 1);
    const source = {
      x: this.grid.gutter + featureSlot * step,
      y: this.grid.inputY,
    };
    const elapsed = this.reducedMotion
      ? FEATURE_TRACE_DURATION
      : Math.max(0, time - this.featureTrace.started);
    const inputProgress = clamp(elapsed / 650, 0, 1);
    const laneProgress = clamp((elapsed - 420) / 980, 0, 1);
    const outputProgress = clamp((elapsed - 1250) / 650, 0, 1);
    const outputFade = 1 - clamp((elapsed - 1850) / 350, 0, 1);
    const ramp = this.colourRamp(palette);

    if (elapsed >= FEATURE_TRACE_DURATION && this.canvas.dataset.trace === "playing") {
      this.canvas.dataset.trace = "ready";
    }

    context.save();
    context.lineCap = "round";
    context.shadowBlur = 8;
    context.strokeStyle = palette.text;
    context.shadowColor = palette.text;
    context.globalAlpha = 0.72;
    context.lineWidth = 1.2;
    context.beginPath();
    context.arc(source.x, source.y, 7.5, 0, Math.PI * 2);
    context.stroke();

    for (const perspective of ["white", "black"]) {
      const collector = this.collector(perspective);
      const bendA = { x: source.x, y: mix(source.y, collector.y, 0.68) };
      const bendB = { x: collector.x, y: mix(source.y, collector.y, 0.5) };
      const sideColour = perspective === "white" ? ramp.warm : ramp.cool;
      context.shadowColor = sideColour;
      context.strokeStyle = sideColour;
      context.globalAlpha = 0.38;
      context.lineWidth = 1.25;
      context.beginPath();
      context.moveTo(source.x, source.y + 5);
      context.bezierCurveTo(bendA.x, bendA.y, bendB.x, bendB.y, collector.x, collector.y);
      context.stroke();

      if (elapsed < FEATURE_TRACE_DURATION) {
        const pulse = cubicPoint(source, bendA, bendB, collector, inputProgress);
        context.globalAlpha = 0.95;
        context.fillStyle = sideColour;
        context.shadowBlur = 14;
        context.beginPath();
        context.arc(pulse.x, pulse.y, 2.7, 0, Math.PI * 2);
        context.fill();
      }

      for (const lane of this.featureTrace.lanes[perspective]) {
        const target = this.point(perspective, lane.index);
        const control = {
          x: collector.x,
          y: mix(collector.y, target.y, 0.58),
        };
        const colour = lane.value >= 0 ? ramp.warm : ramp.cool;
        context.strokeStyle = colour;
        context.shadowColor = colour;
        context.shadowBlur = 5;
        context.globalAlpha = 0.09 + lane.strength * 0.25;
        context.lineWidth = 0.65 + lane.strength * 0.55;
        context.beginPath();
        context.moveTo(collector.x, collector.y);
        context.quadraticCurveTo(control.x, control.y, target.x, target.y);
        context.stroke();

        if (elapsed >= 420 && elapsed < FEATURE_TRACE_DURATION) {
          const pulse = quadraticPoint(collector, control, target, laneProgress);
          context.globalAlpha = 0.5 + lane.strength * 0.45;
          context.fillStyle = colour;
          context.shadowBlur = 10;
          context.beginPath();
          context.arc(pulse.x, pulse.y, 1.6 + lane.strength, 0, Math.PI * 2);
          context.fill();
        }
      }
    }

    if (outputProgress > 0 && outputFade > 0) {
      const core = this.coreCentre();
      context.strokeStyle = ramp.warm;
      context.shadowColor = ramp.cool;
      context.shadowBlur = 18;
      context.globalAlpha = outputFade * 0.72;
      context.lineWidth = 1.1;
      context.beginPath();
      context.arc(core.x, core.y, 34 + outputProgress * 18, 0, Math.PI * 2);
      context.stroke();
    }
    context.restore();
  }

  drawOutputConnections(context, palette) {
    if (!this.transition || this.displayMode !== "contribution") return;
    this.connectionCache ||= this.rankConnections();
    const ramp = this.colourRamp(palette);
    const core = this.coreCentre();
    const anatomyBoost = this.anatomyStage === "output" ? 0.3 : 0.18;
    context.save();
    context.lineWidth = 0.75;
    for (const item of this.connectionCache) {
      const point = this.point(item.perspective, item.index);
      // Gather each accumulator's links before they enter the core.
      const waist = {
        x: mix(this.collector(item.perspective).x, core.x, 0.45),
        y: mix(this.grid.bottom, core.y, 0.55),
      };
      context.globalAlpha = clamp(item.strength, 0.04, 1) * anatomyBoost;
      context.strokeStyle = item.positive ? ramp.warm : ramp.cool;
      context.beginPath();
      context.moveTo(point.x, point.y);
      context.bezierCurveTo(point.x, mix(point.y, waist.y, 0.6), waist.x, waist.y, core.x, core.y);
      context.stroke();
    }
    context.restore();
  }

  drawCore(context, palette, time) {
    const evaluation = this.evaluation();
    const colour = this.rampColour(this.colourRamp(palette), this.corePolarity);
    const { x, y } = this.coreCentre();
    const pulse = this.reducedMotion ? 0 : Math.sin(time / 940) * 1.6;
    const radius = clamp(this.width * 0.032, 20, 34) + pulse + this.coreBoost;
    const glow = context.createRadialGradient(x, y, 2, x, y, radius * 2.7);
    glow.addColorStop(0, colour);
    glow.addColorStop(0.23, palette.accent2);
    glow.addColorStop(0.52, "rgba(82, 50, 120, 0.32)");
    glow.addColorStop(1, "rgba(5, 8, 15, 0)");
    context.fillStyle = glow;
    context.beginPath();
    context.arc(x, y, radius * 2.7, 0, Math.PI * 2);
    context.fill();
    context.save();
    context.strokeStyle = colour;
    context.globalAlpha = 0.62;
    context.lineWidth = 1.2;
    for (let ring = 0; ring < 3; ring += 1) {
      context.beginPath();
      context.ellipse(x, y, radius * (0.68 + ring * 0.34), radius * (0.56 + ring * 0.3), time / 2200 + ring, 0, Math.PI * 2);
      context.stroke();
    }
    context.restore();
    // Show only scores produced by the network, without interpolation.
    let scoreText = formatEval(evaluation);
    if (this.transition?.before && ["board", "lanes"].includes(this.anatomyStage)) {
      scoreText = `${formatEval(this.transition.before.whiteRelative)} →`;
    } else if (this.transition?.before && this.anatomyStage === "output") {
      scoreText = `${formatEval(this.transition.before.whiteRelative)} → ${formatEval(this.transition.after.whiteRelative)}`;
    }
    context.save();
    context.fillStyle = palette.text;
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.font = `750 ${scoreText.length > 8 ? 9 : 12}px "Cascadia Mono", Consolas, monospace`;
    context.shadowColor = "rgba(0, 0, 0, 0.85)";
    context.shadowBlur = 5;
    context.fillText(scoreText, x, y);
    context.restore();
  }

  // Track the move's light wave by row. Null means no active wave.
  igniteFront(time) {
    if (this.anatomyStage !== "lanes" || this.reducedMotion) return null;
    const progress = (time - this.anatomyStarted) / 780;
    return progress < 0 || progress > 1.3 ? null : progress * 30 - 3;
  }

  drawPanels(context, palette) {
    context.save();
    for (const perspective of ["white", "black"]) {
      const first = this.point(perspective, 0);
      const last = this.point(perspective, 383);
      context.textAlign = "left";
      context.font = '700 9px "Cascadia Mono", Consolas, monospace';
      context.fillStyle = palette.muted;
      context.globalAlpha = 0.7;
      const compact = this.width < 560;
      context.fillText(
        perspective === "white"
          ? compact ? "WHITE VIEW" : "WHITE VIEW · BOARD AS ENTERED"
          : compact ? "BLACK VIEW" : "BLACK VIEW · RANKS MIRRORED",
        first.x - 12,
        first.y - 13,
      );
      context.globalAlpha = 0.13;
      context.strokeStyle = palette.edge;
      context.lineWidth = 1;
      context.strokeRect(first.x - 13, first.y - 12, last.x - first.x + 26, last.y - first.y + 24);
      context.textAlign = "right";
      context.font = '700 8px "Cascadia Mono", Consolas, monospace';
      context.globalAlpha = 0.42;
      context.fillStyle = palette.muted;
      for (let row = 0; row < 24; row += 4) {
        const point = this.point(perspective, row * 16);
        context.fillText(String(row * 16).padStart(3, "0"), point.x - 13, point.y + 3);
      }
    }
    context.restore();
  }

  ensureLattice() {
    if (this.latticeCache) return this.latticeCache;
    const dead = new Path2D();
    const live = new Path2D();
    for (const perspective of ["white", "black"]) {
      const base = perspective === "white" ? 0 : 384;
      for (let index = 0; index < 384; index += 1) {
        const point = this.point(perspective, index);
        const target = this.nodeDead[base + index] > 0.5 ? dead : live;
        target.moveTo(point.x + 1.15, point.y);
        target.arc(point.x, point.y, 1.15, 0, Math.PI * 2);
      }
    }
    this.latticeCache = { dead, live };
    return this.latticeCache;
  }

  drawCells(context, palette, time) {
    if (!this.transition) return;
    const ramp = this.colourRamp(palette);
    const selected = this.locked || this.hovered;
    const front = this.igniteFront(time);
    context.save();

    // Rebuild the dormant lattice with data so zeroed lanes remain distinct.
    const lattice = this.ensureLattice();
    context.fillStyle = ramp.dead;
    context.globalAlpha = 0.5;
    context.fill(lattice.dead);
    context.fillStyle = palette.edge;
    context.globalAlpha = 0.09;
    context.fill(lattice.live);

    for (const perspective of ["white", "black"]) {
      const base = perspective === "white" ? 0 : 384;
      for (let index = 0; index < 384; index += 1) {
        const slot = base + index;
        const activity = this.nodeActivity[slot];
        if (activity <= 0.01) continue;
        const intensity = this.nodeIntensity[slot];
        const focus = this.focusWeight[slot];
        // Keep driven lanes lit and dim the rest when focused.
        const emphasis = mix(1, mix(0.07, 1.5, focus), this.focusFade);
        const wave = front === null
          ? 0
          : clamp(1 - Math.abs(front - Math.floor(index / 16)) / 3.5, 0, 1) * focus;
        const point = this.point(perspective, index);
        const ambient = this.reducedMotion ? 0 : Math.sin(time / 900 + index * 0.19) * 0.08;
        const radius = 1.15 + intensity * 2.45 * emphasis + ambient + wave * 2.4;
        const saturation = this.nodeSaturation[slot];
        const colour = this.rampColour(ramp, this.nodePolarity[slot], intensity * emphasis);
        context.globalAlpha = clamp((0.16 + intensity * 0.78) * activity * emphasis + wave * 0.5, 0, 1);
        context.fillStyle = colour;
        if (intensity * emphasis > 0.62 || wave > 0.3) {
          context.shadowColor = colour;
          context.shadowBlur = 8 + wave * 12;
        } else {
          context.shadowBlur = 0;
        }
        context.beginPath();
        context.arc(point.x, point.y, radius, 0, Math.PI * 2);
        context.fill();
        if (saturation > 0.01) {
          context.globalAlpha = 0.5 * saturation;
          context.strokeStyle = ramp.crest;
          context.lineWidth = 0.7;
          context.stroke();
        }
        // Ring the lanes this piece or move drives hardest.
        const marked = focus * this.focusFade;
        if (marked > 0.62) {
          context.globalAlpha = (marked - 0.62) * 1.6;
          context.strokeStyle = colour;
          context.lineWidth = 0.9;
          context.beginPath();
          context.arc(point.x, point.y, radius + 3.4, 0, Math.PI * 2);
          context.stroke();
        }
      }
    }
    context.restore();
    if (selected) {
      const point = this.point(selected.perspective, selected.index);
      context.save();
      context.strokeStyle = palette.text;
      context.lineWidth = 1.4;
      context.globalAlpha = 0.92;
      context.beginPath();
      context.arc(point.x, point.y, 7, 0, Math.PI * 2);
      context.stroke();
      context.restore();
    }
  }

  draw(time) {
    const context = this.context;
    if (!context || !this.width || !this.height) return;
    const palette = this.palette();
    context.clearRect(0, 0, this.width, this.height);
    const background = context.createRadialGradient(
      this.width * 0.5,
      this.height * 0.48,
      10,
      this.width * 0.5,
      this.height * 0.48,
      this.width * 0.62,
    );
    background.addColorStop(0, "#111325");
    background.addColorStop(0.52, "#090c16");
    background.addColorStop(1, palette.void);
    context.fillStyle = background;
    context.fillRect(0, 0, this.width, this.height);

    this.drawMesh(context, palette);
    this.drawPanels(context, palette);
    this.drawInputs(context, palette, time);
    this.drawOutputConnections(context, palette);
    this.drawCells(context, palette, time);
    this.drawSignalTrace(context, palette, time);
    this.drawCore(context, palette, time);
  }
}

export { CortexVisual };
