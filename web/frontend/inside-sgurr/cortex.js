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
    this.canvas.dataset.atlasBand = "0";
    this.canvas.dataset.displayMode = this.displayMode;
    this.canvas.dataset.anatomy = this.anatomyStage;

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
    this.footprintCache = footprint ? this.rankFootprint(footprint) : null;
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
    if (time - this.lastFrame < 42 && !this.reducedMotion) {
      this.start();
      return;
    }
    this.lastFrame = time;
    const distance = this.viewTarget - this.viewProgress;
    if (Math.abs(distance) > 0.001) {
      this.viewProgress = this.reducedMotion
        ? this.viewTarget
        : this.viewProgress + distance * 0.13;
    } else {
      this.viewProgress = this.viewTarget;
    }
    this.draw(time);
    if (
      this.viewProgress !== this.viewTarget
      || (!this.reducedMotion && time < this.animateUntil)
    ) this.start();
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
    if (this.phase === "before") {
      return {
        accumulator: perspective === "white" ? before.whiteAccumulator : before.blackAccumulator,
        activation: perspective === "white" ? before.whiteActivation : before.blackActivation,
        contribution: perspective === "white" ? before.whiteContribution : before.blackContribution,
        delta: perspective === "white" ? this.transition.whiteDelta : this.transition.blackDelta,
      };
    }
    return {
      accumulator: perspective === "white" ? after.whiteAccumulator : after.blackAccumulator,
      activation: perspective === "white" ? after.whiteActivation : after.blackActivation,
      contribution: perspective === "white" ? after.whiteContribution : after.blackContribution,
      delta: perspective === "white" ? this.transition.whiteDelta : this.transition.blackDelta,
    };
  }

  nodeState(perspective, index, palette) {
    const values = this.valuesFor(perspective);
    const snapshot = this.phase === "before" && this.transition.before
      ? this.transition.before
      : this.transition.after;
    const whiteSign = snapshot.sideToMove === 0 ? 1 : -1;
    if (this.displayMode === "change") {
      const value = values.delta[index];
      return {
        value,
        intensity: clamp(Math.abs(value) / this.deltaScale, 0, 1),
        active: value !== 0,
        colour: value >= 0 ? palette.accent : palette.blue,
        saturated: false,
      };
    }
    if (this.displayMode === "activation") {
      const value = values.activation[index];
      return {
        value,
        intensity: value / 255,
        active: value > 0,
        colour: perspective === "white" ? palette.accent : palette.blue,
        saturated: value >= 255,
      };
    }
    if (this.displayMode === "clipped") {
      const raw = values.accumulator[index];
      const high = raw >= 255;
      const low = raw <= 0;
      return {
        value: high ? 1 : low ? -1 : 0,
        intensity: high || low ? 1 : 0,
        active: high || low,
        colour: high ? palette.violet : palette.blue,
        saturated: high,
      };
    }
    let value = values.contribution[index] * whiteSign;
    let scale = this.contributionScale;
    if (this.phase === "delta" && this.transition.before) {
      const before = this.transition.before;
      const beforeValues = perspective === "white"
        ? before.whiteContribution
        : before.blackContribution;
      const afterValues = perspective === "white"
        ? this.transition.after.whiteContribution
        : this.transition.after.blackContribution;
      const beforeSign = before.sideToMove === 0 ? 1 : -1;
      const afterSign = this.transition.after.sideToMove === 0 ? 1 : -1;
      value = afterValues[index] * afterSign - beforeValues[index] * beforeSign;
      scale = this.contributionDeltaScale;
    }
    return {
      value,
      intensity: clamp(Math.abs(value) / scale, 0, 1),
      active: values.activation[index] > 0 || (this.phase === "delta" && value !== 0),
      colour: value >= 0 ? palette.accent : palette.blue,
      saturated: values.activation[index] >= 255,
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
    const whiteSign = snapshot.sideToMove === 0 ? 1 : -1;
    let contribution = values.contribution[target.index] * whiteSign;
    if (this.phase === "delta" && this.transition.before) {
      const before = this.transition.before;
      const beforeValues = target.perspective === "white"
        ? before.whiteContribution
        : before.blackContribution;
      const afterValues = target.perspective === "white"
        ? this.transition.after.whiteContribution
        : this.transition.after.blackContribution;
      const beforeSign = before.sideToMove === 0 ? 1 : -1;
      const afterSign = this.transition.after.sideToMove === 0 ? 1 : -1;
      contribution = afterValues[target.index] * afterSign - beforeValues[target.index] * beforeSign;
    }
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
    context.save();
    context.globalCompositeOperation = "screen";
    for (const perspective of ["white", "black"]) {
      for (let rowGroup = 0; rowGroup < 6; rowGroup += 1) {
        for (let columnGroup = 0; columnGroup < 4; columnGroup += 1) {
          let intensity = 0;
          let signed = 0;
          let x = 0;
          let y = 0;
          let count = 0;
          for (let row = rowGroup * 4; row < rowGroup * 4 + 4; row += 1) {
            for (let column = columnGroup * 4; column < columnGroup * 4 + 4; column += 1) {
              const index = row * 16 + column;
              const state = this.nodeState(perspective, index, palette);
              const point = this.point(perspective, index);
              intensity += state.intensity;
              signed += state.value;
              x += point.x;
              y += point.y;
              count += 1;
            }
          }
          const strength = intensity / count;
          if (strength < 0.08) continue;
          x /= count;
          y /= count;
          const colour = this.displayMode === "activation"
            ? perspective === "white" ? palette.accent : palette.blue
            : this.displayMode === "clipped"
              ? signed >= 0 ? palette.violet : palette.blue
              : signed >= 0 ? palette.accent : palette.blue;
          const radius = 18 + strength * 34;
          context.save();
          context.translate(x, y);
          context.scale(1.65, 0.78);
          const glow = context.createRadialGradient(0, 0, 1, 0, 0, radius);
          glow.addColorStop(0, `${colour}24`);
          glow.addColorStop(0.46, `${colour}10`);
          glow.addColorStop(1, `${colour}00`);
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
    if (!this.footprintCache) return;
    for (const perspective of ["white", "black"]) {
      context.save();
      context.globalCompositeOperation = "screen";
      for (const item of this.footprintCache[perspective]) {
        const point = this.point(perspective, item.index);
        const colour = item.positive ? palette.accent2 : palette.violet;
        const radius = 5 + clamp(item.strength, 0, 1) * 9;
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
    const snapshot = this.phase === "before" && this.transition?.before
      ? this.transition.before
      : this.transition?.after;
    const evaluation = this.phase === "delta" && this.transition?.before
      ? this.transition.after.whiteRelative - this.transition.before.whiteRelative
      : snapshot?.whiteRelative || 0;
    const colour = evaluation >= 0 ? palette.accent : palette.blue;
    const x = this.width * 0.5;
    const y = this.height * 0.77;
    const pulse = this.reducedMotion ? 0 : Math.sin(time / 940) * 1.6;
    const anatomyBoost = this.anatomyStage === "output" ? 5 : 0;
    const radius = clamp(this.width * 0.034, 22, 38) + pulse + anatomyBoost;
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
    let scoreText = formatEval(evaluation);
    if (this.transition?.before && ["input", "accumulators", "clamp"].includes(this.anatomyStage)) {
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
    const selected = this.locked || this.hovered;
    context.save();
    for (const perspective of ["white", "black"]) {
      for (let index = 0; index < 384; index += 1) {
        const point = this.point(perspective, index);
        const { intensity, active, colour, saturated } = this.nodeState(perspective, index, palette);
        const inBand = Math.floor(index / 96) === this.atlasBand;
        const ambient = this.reducedMotion ? 0 : Math.sin(time / 900 + index * 0.19) * 0.08;
        const radius = 1.15 + intensity * 2.45 + ambient + (inBand ? 0.2 : 0);
        const opacity = active ? 0.16 + intensity * 0.78 : 0.08;
        context.globalAlpha = opacity * (inBand ? 1 : 0.42);
        context.fillStyle = active ? colour : palette.edge;
        if (inBand && intensity > 0.62) {
          context.shadowColor = colour;
          context.shadowBlur = 8;
        } else {
          context.shadowBlur = 0;
        }
        context.beginPath();
        context.arc(point.x, point.y, radius, 0, Math.PI * 2);
        context.fill();
        if (saturated) {
          context.globalAlpha = 0.52;
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
