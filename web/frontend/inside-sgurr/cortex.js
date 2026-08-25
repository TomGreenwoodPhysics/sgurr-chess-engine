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
    this.grid = { cell: 10, top: 0, bottom: 0, whiteLeft: 0, blackLeft: 0 };
    this.contributionScale = 1;
    this.contributionDeltaScale = 1;
    this.deltaScale = 1;
    this.valueCache = new Map();
    this.connectionCache = null;
    this.nodeIntensity = new Float32Array(768);
    this.nodePolarity = new Float32Array(768);
    this.nodeActivity = new Float32Array(768);
    this.nodeSaturation = new Float32Array(768);
    this.focusWeight = new Float32Array(768);
    this.focusTarget = new Float32Array(768);
    this.focusOn = false;
    this.focusFade = 0;
    this.scratch = { value: 0, intensity: 0, activity: 0, polarity: 0, saturation: 0 };
    this.violetBlend = 0;
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

  setDisplayMode(mode) {
    if (!["contribution", "change", "activation", "clipped"].includes(mode)) return;
    this.displayMode = mode;
    this.connectionCache = null;
    this.canvas.dataset.displayMode = mode;
    this.wake(2400);
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

  // Marks the lanes a piece or a move actually drives. Values are magnitudes;
  // they are normalised against the strongest lane in the pair, so the display
  // shows where the weight is, not an arbitrary cut-off.
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

  focusChangedLanes() {
    if (!this.transition?.before) return;
    this.setFocus(this.transition.whiteDelta, this.transition.blackDelta);
  }

  clearFocus() {
    this.setFocus(null, null);
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
    // Draw at the display rate while anything is still easing, and drop back to
    // an idle cadence once the picture has settled.
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

    for (let slot = 0; slot < 768; slot += 1) {
      moving = approach(this.focusWeight, slot, this.focusTarget[slot], nodeBlend) || moving;
    }
    moving = approach(this, "focusFade", this.focusOn ? 1 : 0, ambientBlend) || moving;
    moving = approach(this, "violetBlend", this.displayMode === "clipped" ? 1 : 0, ambientBlend) || moving;
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

  // Both accumulators are 16 x 24 grids of lanes. Lane 0 is top left of its
  // panel and addresses run left to right, so a row is 16 consecutive lanes.
  // Cells stay square and the pair is centred in whatever space the stage has.
  computeLayout() {
    const header = 46;
    const footer = clamp(this.height * 0.19, 92, 150);
    const usableHeight = Math.max(60, this.height - header - footer);
    const gutter = 42;
    const gap = clamp(this.width * 0.062, 40, 78);
    const panelWidth = (this.width - gutter * 2 - gap) / 2;
    const cell = Math.max(4, Math.min(panelWidth / 15, usableHeight / 23));
    const gridWidth = cell * 15;
    const left = gutter + (this.width - gutter * 2 - (gridWidth * 2 + gap)) / 2;
    this.grid = {
      cell,
      top: header + (usableHeight - cell * 23) / 2,
      bottom: header + (usableHeight - cell * 23) / 2 + cell * 23,
      whiteLeft: left,
      blackLeft: left + gridWidth + gap,
    };
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

  drawOutputConnections(context, palette) {
    if (!this.transition || this.displayMode !== "contribution") return;
    this.connectionCache ||= this.rankConnections(palette);
    const core = this.coreCentre();
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
    // The number itself never interpolates: a score shown here is one the
    // network actually produced.
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

  // How far a wave of light has travelled down the grid, in rows, while a move
  // is being pushed through the network. Null when nothing is igniting.
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
        first.y - 22,
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

  drawCells(context, palette, time) {
    if (!this.transition) return;
    const ramp = this.colourRamp(palette);
    const selected = this.locked || this.hovered;
    const front = this.igniteFront(time);
    context.save();

    // The dormant lattice, so the shape of both accumulators is always readable.
    context.fillStyle = palette.edge;
    context.globalAlpha = 0.09;
    context.beginPath();
    for (const perspective of ["white", "black"]) {
      for (let index = 0; index < 384; index += 1) {
        const point = this.point(perspective, index);
        context.moveTo(point.x + 1.15, point.y);
        context.arc(point.x, point.y, 1.15, 0, Math.PI * 2);
      }
    }
    context.fill();

    for (const perspective of ["white", "black"]) {
      const base = perspective === "white" ? 0 : 384;
      for (let index = 0; index < 384; index += 1) {
        const slot = base + index;
        const activity = this.nodeActivity[slot];
        if (activity <= 0.01) continue;
        const intensity = this.nodeIntensity[slot];
        const focus = this.focusWeight[slot];
        // With no focus every lane reads normally. With one, the lanes the piece
        // or the move actually drives stay lit and the rest step back.
        const emphasis = mix(1, mix(0.07, 1.5, focus), this.focusFade);
        const wave = front === null
          ? 0
          : clamp(1 - Math.abs(front - Math.floor(index / 16)) / 3.5, 0, 1) * focus;
        const point = this.point(perspective, index);
        const ambient = this.reducedMotion ? 0 : Math.sin(time / 900 + index * 0.19) * 0.08;
        const radius = 1.15 + intensity * 2.45 * emphasis + ambient + wave * 2.4;
        const colour = this.rampColour(ramp, this.nodePolarity[slot]);
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
        const saturation = this.nodeSaturation[slot];
        if (saturation > 0.01) {
          context.globalAlpha = 0.52 * saturation;
          context.strokeStyle = palette.violet;
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

    this.drawPanels(context, palette);
    this.drawOutputConnections(context, palette);
    this.drawCells(context, palette, time);
    this.drawCore(context, palette, time);
  }
}

export { CortexVisual };
