const RAMP_STEPS = 64;
const SETTLE_EPSILON = 0.003;
// Time constants, in milliseconds, for the exponential easing. Roughly 3x these
// numbers is how long a change takes to read as finished.
const NODE_TAU = 88;
const AMBIENT_TAU = 150;
const CORE_TAU = 105;

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function mix(a, b, amount) {
  return a + (b - a) * amount;
}

function hash(index, salt = 0) {
  const value = Math.sin((index + 1) * 91.173 + salt * 37.719) * 43758.5453;
  return value - Math.floor(value);
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

function buildRamp(negative, positive) {
  const css = [];
  const rgb = [];
  for (let step = 0; step <= RAMP_STEPS; step += 1) {
    const channels = mixColour(negative, positive, step / RAMP_STEPS).map(Math.round);
    rgb.push(channels);
    css.push(`rgb(${channels[0]}, ${channels[1]}, ${channels[2]})`);
  }
  return { css, rgb };
}

// Frame-rate independent easing: every value walks a fixed fraction of the
// remaining distance per millisecond, so the same motion reads identically at
// 30fps and 120fps. Returns whether the value moved.
function approach(holder, key, target, blend) {
  const distance = target - holder[key];
  // Settle on an epsilon, not on equality: these live in Float32Arrays, so a
  // stored value never compares equal to the double it was assigned from.
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

class CortexVisual {
  constructor(canvas, onInspect) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.onInspect = onInspect;
    this.transition = null;
    this.phase = "after";
    this.view = "cortex";
    this.viewProgress = 0;
    this.viewTarget = 0;
    this.atlasBand = 0;
    this.displayMode = "contribution";
    this.featureFootprint = null;
    this.featureScale = 1;
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
    this.contributionScale = 1;
    this.contributionDeltaScale = 1;
    this.deltaScale = 1;
    this.valueCache = new Map();
    this.connectionCache = null;
    this.footprintCache = null;
    this.nodeIntensity = new Float32Array(768);
    this.nodePolarity = new Float32Array(768);
    this.nodeActivity = new Float32Array(768);
    this.nodeSaturation = new Float32Array(768);
    this.bandWeight = Float32Array.from([1, 0.42, 0.42, 0.42]);
    this.scratch = { value: 0, intensity: 0, activity: 0, polarity: 0, saturation: 0 };
    this.footprintFade = 0;
    this.footprintTarget = 0;
    this.violetBlend = 0;
    this.corePolarity = 1;
    this.coreBoost = 0;
    this.motionPrimed = false;
    this.settled = true;
    this.rampCache = null;
    this.rampKey = "";
    this.canvas.dataset.atlasBand = "0";
    this.canvas.dataset.displayMode = this.displayMode;
    this.canvas.dataset.anatomy = this.anatomyStage;
    this.canvas.dataset.motion = "settled";

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
    this.wake();
  }

  setPhase(phase) {
    this.phase = phase;
    this.connectionCache = null;
    this.wake(2400);
  }

  setView(view) {
    this.view = view;
    this.viewTarget = view === "circuit" ? 1 : 0;
    this.canvas.dataset.view = view;
    this.canvas.setAttribute(
      "aria-label",
      view === "circuit"
        ? "Sgurr's 768 exact NNUE accumulator activations in two 16 by 24 lane arrays. Use arrow keys to inspect lanes."
        : "Sgurr's 768 exact NNUE accumulator activations, arranged as two brain hemispheres. Use arrow keys to inspect lanes.",
    );
    this.wake(3200);
  }

  setAtlasBand(band) {
    this.atlasBand = clamp(Math.trunc(band), 0, 3);
    this.canvas.dataset.atlasBand = String(this.atlasBand);
    this.wake(2200);
  }

  setDisplayMode(mode) {
    if (!["contribution", "change", "activation", "clipped"].includes(mode)) return;
    this.displayMode = mode;
    this.connectionCache = null;
    this.canvas.dataset.displayMode = mode;
    this.wake(2400);
  }

  setFeatureFootprint(footprint) {
    this.featureFootprint = footprint;
    this.featureScale = footprint
      ? percentile([...footprint.whiteWeights, ...footprint.blackWeights], 0.9)
      : 1;
    // Keep the old ranking alive so the halos can fade out instead of vanishing.
    if (footprint) this.footprintCache = this.rankFootprint(footprint);
    this.footprintTarget = footprint ? 1 : 0;
    this.canvas.dataset.feature = footprint ? "active" : "idle";
    this.wake(2600);
  }

  rankFootprint(footprint) {
    const ranked = {};
    for (const perspective of ["white", "black"]) {
      const weights = perspective === "white" ? footprint.whiteWeights : footprint.blackWeights;
      const candidates = [];
      for (let index = 0; index < 384; index += 1) {
        candidates.push({
          index,
          positive: weights[index] >= 0,
          strength: Math.abs(weights[index]) / this.featureScale,
        });
      }
      candidates.sort((a, b) => b.strength - a.strength);
      ranked[perspective] = candidates.slice(0, 34);
    }
    return ranked;
  }

  rankConnections(palette) {
    const candidates = [];
    for (const perspective of ["white", "black"]) {
      for (let index = 0; index < 384; index += 1) {
        const state = this.nodeState(perspective, index, palette);
        candidates.push({ perspective, index, strength: state.intensity, positive: state.value >= 0 });
      }
    }
    candidates.sort((a, b) => b.strength - a.strength);
    return candidates.slice(0, 42);
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
    // Draw at the display rate while anything is still easing, and drop back to
    // an idle cadence once the picture has settled.
    const gate = this.settled && this.viewProgress === this.viewTarget ? 42 : 0;
    if (time - this.lastFrame < gate && !this.reducedMotion) {
      this.start();
      return;
    }
    const delta = clamp(time - this.lastFrame, 1, 120);
    this.lastFrame = time;
    const distance = this.viewTarget - this.viewProgress;
    if (Math.abs(distance) > 0.001) {
      this.viewProgress = this.reducedMotion
        ? this.viewTarget
        : this.viewProgress + distance * 0.13;
    } else {
      this.viewProgress = this.viewTarget;
    }
    this.advance(delta);
    this.draw(time);
    if (
      !this.settled
      || this.viewProgress !== this.viewTarget
      || (!this.reducedMotion && time < this.animateUntil)
    ) this.start();
  }

  // Walks every displayed value towards the value the network actually holds.
  // Nothing is drawn from the raw data directly, so every change fades.
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
        }
      }
      this.motionPrimed = true;
    }

    for (let band = 0; band < 4; band += 1) {
      moving = approach(this.bandWeight, band, band === this.atlasBand ? 1 : 0.42, ambientBlend) || moving;
    }
    moving = approach(this, "footprintFade", this.footprintTarget, ambientBlend) || moving;
    moving = approach(this, "violetBlend", this.displayMode === "clipped" ? 1 : 0, ambientBlend) || moving;
    moving = approach(this, "coreBoost", this.anatomyStage === "output" ? 5 : 0, coreBlend) || moving;
    moving = approach(this, "corePolarity", this.evaluation() >= 0 ? 1 : -1, coreBlend) || moving;
    if (this.footprintFade === 0 && this.footprintTarget === 0) this.footprintCache = null;

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
    const key = `${palette.accent}|${palette.blue}|${palette.violet}|${this.violetBlend.toFixed(2)}`;
    if (this.rampKey !== key) {
      this.rampCache = buildRamp(
        parseColour(palette.blue, [112, 215, 255]),
        mixColour(
          parseColour(palette.accent, [226, 177, 71]),
          parseColour(palette.violet, [169, 140, 255]),
          this.violetBlend,
        ),
      );
      this.rampKey = key;
    }
    return this.rampCache;
  }

  rampIndex(polarity) {
    return Math.round((clamp(polarity, -1, 1) + 1) * (RAMP_STEPS / 2));
  }

  rampColour(ramp, polarity) {
    return ramp.css[this.rampIndex(polarity)];
  }

  rampRgb(ramp, polarity) {
    return ramp.rgb[this.rampIndex(polarity)];
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
      violet: "#a98cff",
      void: "#070a11",
    };
  }

  brainPoint(perspective, index) {
    const row = Math.floor(index / 16);
    const column = index % 16;
    const vertical = ((row + 0.5) / 24) * 2 - 1;
    const widthAtRow = 0.2 + Math.sqrt(Math.max(0, 1 - vertical * vertical)) * 0.8;
    const depth = (column + 0.58) / 16;
    const hemisphereWidth = this.width * 0.39;
    const centre = this.width * 0.5;
    const gap = this.width * 0.021;
    const horizontal = (0.08 + depth * 0.92) * widthAtRow;
    const direction = perspective === "white" ? -1 : 1;
    const jitterX = (hash(index, perspective === "white" ? 1 : 2) - 0.5) * this.width * 0.008;
    const jitterY = (hash(index, perspective === "white" ? 3 : 4) - 0.5) * this.height * 0.012;
    return {
      x: centre + direction * (gap + horizontal * hemisphereWidth) + jitterX,
      y: this.height * 0.48 + vertical * this.height * 0.37 + jitterY + Math.abs(horizontal) * this.height * 0.018,
    };
  }

  circuitPoint(perspective, index) {
    const row = Math.floor(index / 16);
    const column = index % 16;
    const left = perspective === "white" ? this.width * 0.065 : this.width * 0.57;
    const cellWidth = this.width * 0.365 / 15;
    const cellHeight = this.height * 0.66 / 23;
    return {
      x: left + column * cellWidth,
      y: this.height * 0.16 + row * cellHeight,
    };
  }

  point(perspective, index) {
    const brain = this.brainPoint(perspective, index);
    const circuit = this.circuitPoint(perspective, index);
    const eased = this.viewProgress * this.viewProgress * (3 - 2 * this.viewProgress);
    return { x: mix(brain.x, circuit.x, eased), y: mix(brain.y, circuit.y, eased) };
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

  // Fills `out` with the values this lane should be showing, as plain numbers.
  // `polarity` is -1 for the cyan end of the ramp and +1 for the warm end.
  measureNode(perspective, index, values, out) {
    if (this.displayMode === "change") {
      const value = values.delta[index];
      out.value = value;
      out.intensity = clamp(Math.abs(value) / this.deltaScale, 0, 1);
      out.activity = value === 0 ? 0 : 1;
      out.polarity = value >= 0 ? 1 : -1;
      out.saturation = 0;
      return out;
    }
    if (this.displayMode === "activation") {
      const value = values.activation[index];
      out.value = value;
      out.intensity = value / 255;
      out.activity = value > 0 ? 1 : 0;
      out.polarity = perspective === "white" ? 1 : -1;
      out.saturation = value >= 255 ? 1 : 0;
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
    return out;
  }

  nodeState(perspective, index, palette) {
    const target = this.measureNode(perspective, index, this.valuesFor(perspective), this.scratch);
    const warm = this.displayMode === "clipped" ? palette.violet : palette.accent;
    return {
      value: target.value,
      intensity: target.intensity,
      active: target.activity > 0,
      colour: target.polarity >= 0 ? warm : palette.blue,
      saturated: target.saturation > 0,
    };
  }

  laneDetails(target) {
    const values = this.valuesFor(target.perspective);
    if (!values) return null;
    const snapshot = this.phase === "before" && this.transition.before
      ? this.transition.before
      : this.transition.after;
    const outputOffset = target.perspective === "white"
      ? snapshot.sideToMove === 0 ? 0 : 384
      : snapshot.sideToMove === 1 ? 0 : 384;
    const contribution = values.signed[target.index];
    return {
      ...target,
      phase: this.phase,
      raw: values.accumulator[target.index],
      clipped: values.activation[target.index],
      delta: values.delta[target.index],
      contribution,
      outputHalf: outputOffset === 0 ? "side to move" : "other side",
      centipawns: contribution * 400 / (255 * 64),
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

  drawOutline(context, palette) {
    const opacity = 1 - this.viewProgress;
    if (opacity <= 0.01) return;
    context.save();
    context.globalAlpha = opacity * 0.42;
    context.strokeStyle = palette.edge;
    context.lineWidth = 1.2;
    for (const direction of [-1, 1]) {
      context.beginPath();
      context.moveTo(this.width * 0.5 + direction * this.width * 0.012, this.height * 0.86);
      context.bezierCurveTo(
        this.width * (0.5 + direction * 0.23), this.height * 0.94,
        this.width * (0.5 + direction * 0.48), this.height * 0.68,
        this.width * (0.5 + direction * 0.43), this.height * 0.36,
      );
      context.bezierCurveTo(
        this.width * (0.5 + direction * 0.4), this.height * 0.08,
        this.width * (0.5 + direction * 0.12), this.height * 0.04,
        this.width * 0.5 + direction * this.width * 0.012, this.height * 0.13,
      );
      context.stroke();
    }
    context.setLineDash([4, 8]);
    context.globalAlpha = opacity * 0.19;
    for (let fold = 0; fold < 6; fold += 1) {
      const y = this.height * (0.23 + fold * 0.095);
      context.beginPath();
      context.moveTo(this.width * 0.18, y);
      context.bezierCurveTo(this.width * 0.28, y - 28, this.width * 0.38, y + 28, this.width * 0.47, y);
      context.stroke();
      context.beginPath();
      context.moveTo(this.width * 0.53, y);
      context.bezierCurveTo(this.width * 0.62, y + 28, this.width * 0.72, y - 28, this.width * 0.82, y);
      context.stroke();
    }
    context.restore();
  }

  drawOutputConnections(context, palette) {
    if (!this.transition || this.displayMode !== "contribution") return;
    this.connectionCache ||= this.rankConnections(palette);
    const core = { x: this.width * 0.5, y: this.height * 0.77 };
    const anatomyBoost = this.anatomyStage === "output" ? 0.3 : 0.18;
    context.save();
    context.lineWidth = 0.75;
    for (const item of this.connectionCache) {
      const point = this.point(item.perspective, item.index);
      context.globalAlpha = clamp(item.strength, 0.04, 1) * anatomyBoost;
      context.strokeStyle = item.positive ? palette.accent : palette.blue;
      context.beginPath();
      context.moveTo(point.x, point.y);
      context.quadraticCurveTo(
        mix(point.x, core.x, 0.56),
        point.y + (core.y - point.y) * 0.34,
        core.x,
        core.y,
      );
      context.stroke();
    }
    context.restore();
  }

  drawBandGuide(context, palette) {
    const first = this.atlasBand * 96;
    const last = first + 95;
    context.save();
    context.font = '700 8px "Cascadia Mono", Consolas, monospace';
    context.textAlign = "center";
    for (const perspective of ["white", "black"]) {
      const points = [];
      for (let index = first; index <= last; index += 1) points.push(this.point(perspective, index));
      const left = Math.min(...points.map((point) => point.x)) - 8;
      const right = Math.max(...points.map((point) => point.x)) + 8;
      const top = Math.min(...points.map((point) => point.y)) - 8;
      context.globalAlpha = 0.62;
      context.fillStyle = palette.muted;
      context.fillText(
        `${String(first).padStart(3, "0")}–${String(last).padStart(3, "0")}`,
        (left + right) / 2,
        top - 5,
      );
    }
    context.restore();
  }

  drawContours(context, palette) {
    if (!this.transition) return;
    const ramp = this.colourRamp(palette);
    context.save();
    context.globalCompositeOperation = "screen";
    for (const perspective of ["white", "black"]) {
      const base = perspective === "white" ? 0 : 384;
      for (let rowGroup = 0; rowGroup < 6; rowGroup += 1) {
        for (let columnGroup = 0; columnGroup < 4; columnGroup += 1) {
          let intensity = 0;
          let polarity = 0;
          let x = 0;
          let y = 0;
          let count = 0;
          for (let row = rowGroup * 4; row < rowGroup * 4 + 4; row += 1) {
            for (let column = columnGroup * 4; column < columnGroup * 4 + 4; column += 1) {
              const index = row * 16 + column;
              const slot = base + index;
              const weight = this.nodeIntensity[slot] * this.nodeActivity[slot];
              const point = this.point(perspective, index);
              intensity += weight;
              polarity += this.nodePolarity[slot] * weight;
              x += point.x;
              y += point.y;
              count += 1;
            }
          }
          const strength = intensity / count;
          if (strength < 0.08) continue;
          x /= count;
          y /= count;
          // Lean hard towards whichever way the group tilts, so a patch keeps a
          // definite hue instead of averaging out to grey; it still crossfades.
          const tilt = clamp((polarity / Math.max(intensity, 0.0001)) * 2.6, -1, 1);
          const colour = this.rampColour(ramp, tilt);
          const [red, green, blue] = this.rampRgb(ramp, tilt);
          const radius = 18 + strength * 34;
          context.save();
          context.translate(x, y);
          context.scale(1.65, 0.78);
          const glow = context.createRadialGradient(0, 0, 1, 0, 0, radius);
          glow.addColorStop(0, `rgba(${red}, ${green}, ${blue}, 0.141)`);
          glow.addColorStop(0.46, `rgba(${red}, ${green}, ${blue}, 0.063)`);
          glow.addColorStop(1, `rgba(${red}, ${green}, ${blue}, 0)`);
          context.fillStyle = glow;
          context.beginPath();
          context.arc(0, 0, radius, 0, Math.PI * 2);
          context.fill();
          if (strength > 0.46) {
            context.globalAlpha = 0.08 + strength * 0.08;
            context.strokeStyle = colour;
            context.lineWidth = 0.65;
            context.beginPath();
            context.ellipse(0, 0, radius * 0.72, radius * 0.72, 0, 0, Math.PI * 2);
            context.stroke();
          }
          context.restore();
        }
      }
    }
    context.restore();
  }

  drawFeatureFootprint(context, palette) {
    if (!this.footprintCache || this.footprintFade <= 0.01) return;
    for (const perspective of ["white", "black"]) {
      context.save();
      context.globalCompositeOperation = "screen";
      context.globalAlpha = this.footprintFade;
      for (const item of this.footprintCache[perspective]) {
        const point = this.point(perspective, item.index);
        const colour = item.positive ? palette.accent2 : palette.violet;
        const radius = 5 + clamp(item.strength, 0, 1) * 9 * this.footprintFade;
        const glow = context.createRadialGradient(point.x, point.y, 1, point.x, point.y, radius);
        glow.addColorStop(0, `${colour}78`);
        glow.addColorStop(0.32, `${colour}28`);
        glow.addColorStop(1, `${colour}00`);
        context.fillStyle = glow;
        context.beginPath();
        context.arc(point.x, point.y, radius, 0, Math.PI * 2);
        context.fill();
      }
      context.restore();
    }
  }

  strongestChangedLane(perspective) {
    if (!this.transition?.before) return 192;
    const values = perspective === "white" ? this.transition.whiteDelta : this.transition.blackDelta;
    let target = 0;
    for (let index = 1; index < values.length; index += 1) {
      if (Math.abs(values[index]) > Math.abs(values[target])) target = index;
    }
    return target;
  }

  drawAnatomyPulses(context, palette, time) {
    if (!["input", "accumulators"].includes(this.anatomyStage)) return;
    const elapsed = time - this.anatomyStarted;
    const progress = this.reducedMotion ? 1 : clamp(elapsed / 950, 0, 1);
    const eased = progress * progress * (3 - 2 * progress);
    const start = { x: this.width * 0.5, y: this.height * 0.02 };
    context.save();
    for (const perspective of ["white", "black"]) {
      const target = this.point(perspective, this.strongestChangedLane(perspective));
      const control = {
        x: mix(start.x, target.x, 0.52),
        y: this.height * 0.11,
      };
      context.globalAlpha = 0.22;
      context.strokeStyle = perspective === "white" ? palette.accent : palette.blue;
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(start.x, start.y);
      context.quadraticCurveTo(control.x, control.y, target.x, target.y);
      context.stroke();
      const oneMinus = 1 - eased;
      const x = oneMinus * oneMinus * start.x + 2 * oneMinus * eased * control.x + eased * eased * target.x;
      const y = oneMinus * oneMinus * start.y + 2 * oneMinus * eased * control.y + eased * eased * target.y;
      const colour = perspective === "white" ? palette.accent : palette.blue;
      context.globalAlpha = 0.9;
      context.fillStyle = colour;
      context.shadowColor = colour;
      context.shadowBlur = 12;
      context.beginPath();
      context.arc(x, y, 3.2, 0, Math.PI * 2);
      context.fill();
      if (this.anatomyStage === "accumulators") {
        context.globalAlpha = 0.35;
        context.strokeStyle = colour;
        context.lineWidth = 1;
        context.beginPath();
        context.arc(target.x, target.y, 8 + Math.sin(time / 180) * 2, 0, Math.PI * 2);
        context.stroke();
      }
    }
    context.restore();
  }

  drawCore(context, palette, time) {
    const evaluation = this.evaluation();
    const colour = this.rampColour(this.colourRamp(palette), this.corePolarity);
    const x = this.width * 0.5;
    const y = this.height * 0.77;
    const pulse = this.reducedMotion ? 0 : Math.sin(time / 940) * 1.6;
    const radius = clamp(this.width * 0.034, 22, 38) + pulse + this.coreBoost;
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
    // The number itself never interpolates: a score shown here is one the
    // network actually produced.
    let scoreText = formatEval(evaluation);
    if (this.transition?.before && ["input", "accumulators", "clamp"].includes(this.anatomyStage)) {
      scoreText = `${formatEval(this.transition.before.whiteRelative)} \→`;
    } else if (this.transition?.before && this.anatomyStage === "output") {
      scoreText = `${formatEval(this.transition.before.whiteRelative)} \→ ${formatEval(this.transition.after.whiteRelative)}`;
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

  drawLabels(context, palette) {
    context.save();
    context.textAlign = "center";
    context.fillStyle = palette.muted;
    context.globalAlpha = 0.58;
    context.font = '700 10px "Cascadia Mono", Consolas, monospace';
    const labels = {
      contribution: this.phase === "delta" ? "WHITE-RELATIVE OUTPUT CHANGE" : "WHITE-RELATIVE OUTPUT CONTRIBUTION",
      change: "RAW ACCUMULATOR MOVE DELTA",
      activation: "CLIPPED ACTIVATION [0, 255]",
      clipped: "CLIPPED LOW [0] / HIGH [255]",
    };
    context.fillText(labels[this.displayMode], this.width * 0.5, this.height * 0.94);
    context.restore();
  }

  drawCells(context, palette, time) {
    if (!this.transition) return;
    const ramp = this.colourRamp(palette);
    const selected = this.locked || this.hovered;
    context.save();

    // The dormant lattice: every lane, one fill per address band.
    context.fillStyle = palette.edge;
    for (let band = 0; band < 4; band += 1) {
      context.globalAlpha = 0.08 * this.bandWeight[band];
      context.beginPath();
      for (const perspective of ["white", "black"]) {
        for (let index = band * 96; index < band * 96 + 96; index += 1) {
          const point = this.point(perspective, index);
          context.moveTo(point.x + 1.15, point.y);
          context.arc(point.x, point.y, 1.15, 0, Math.PI * 2);
        }
      }
      context.fill();
    }

    // The lanes that are carrying something, drawn over the lattice.
    for (const perspective of ["white", "black"]) {
      const base = perspective === "white" ? 0 : 384;
      for (let index = 0; index < 384; index += 1) {
        const slot = base + index;
        const activity = this.nodeActivity[slot];
        if (activity <= 0.01) continue;
        const intensity = this.nodeIntensity[slot];
        const bandWeight = this.bandWeight[Math.floor(index / 96)];
        const point = this.point(perspective, index);
        const ambient = this.reducedMotion ? 0 : Math.sin(time / 900 + index * 0.19) * 0.08;
        const radius = 1.15 + intensity * 2.45 + ambient + (bandWeight - 0.42) * 0.34;
        const colour = this.rampColour(ramp, this.nodePolarity[slot]);
        context.globalAlpha = (0.16 + intensity * 0.78) * activity * bandWeight;
        context.fillStyle = colour;
        if (intensity > 0.62 && bandWeight > 0.9) {
          context.shadowColor = colour;
          context.shadowBlur = 8;
        } else {
          context.shadowBlur = 0;
        }
        context.beginPath();
        context.arc(point.x, point.y, radius, 0, Math.PI * 2);
        context.fill();
        const saturation = this.nodeSaturation[slot];
        if (saturation > 0.01) {
          context.globalAlpha = 0.52 * saturation;
          context.strokeStyle = palette.violet;
          context.lineWidth = 0.7;
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
      context.arc(point.x, point.y, 8, 0, Math.PI * 2);
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

    this.drawOutline(context, palette);
    this.drawBandGuide(context, palette);
    this.drawContours(context, palette);
    this.drawOutputConnections(context, palette);
    this.drawFeatureFootprint(context, palette);
    this.drawCells(context, palette, time);
    this.drawAnatomyPulses(context, palette, time);
    this.drawCore(context, palette, time);
    this.drawLabels(context, palette);
  }
}

export { CortexVisual };
