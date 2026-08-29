import { apiUrl } from "../js/config.js";

const MAX_VISIBLE_NODES_PER_ITERATION = 120;
const MAX_CAPTURED_NODES_PER_ITERATION = 1200;
const SETTLE_FADE_MS = 620;
const ITERATION_ID_STRIDE = 10_000;
const REPLAY_SPEEDS = Object.freeze({
  ultra: { delayMs: 240, batchSize: 1 },
  slow: { delayMs: 72, batchSize: 1 },
  normal: { delayMs: 20, batchSize: 1 },
  fast: { delayMs: 6, batchSize: 12 },
  "very-fast": { delayMs: 0, batchSize: 48 },
});
const DENSE_NODE_THRESHOLD = 900;
const NATIVE_DETAIL_MIN_SCALE = 1.08;
const COMPLETION_CROSSFADE_MS = 640;
const BLOOM_RESOLUTION_SCALE = 0.5;
const DEPTH_SHOCKWAVE_MS = 1050;
const COMPLETION_EMANATION_EXPAND_MS = 1050;
const COMPLETION_EMANATION_FADE_MS = 2800;
const COMPLETION_CHOREOGRAPHY_MS = 2500;
const CUTOFF_IMPLOSION_MS = 820;
const WORMHOLE_FLASH_MS = 1250;
const LEADER_GHOST_MS = 2400;
const PRINCIPAL_HIT_RADIUS_PX = 26;
const STANDARD_HIT_RADIUS_PX = 10;
const RECONSTRUCTED_TRANSIENT_AGE_MS = 1200;
const LIVE_EVENT_SLICE_MS = 3;
const NAVIGATION_RELEASE_SLICE_MS = 4;
// Pad culling bounds for the largest node and edge glows.
const NODE_CULL_PADDING = 48;
const EDGE_CULL_PADDING = 26;
// Cap rendering near 60 Hz even when callbacks run faster.
const MIN_FRAME_INTERVAL_MS = 14;

// Canvas size dominates cost, so tiers reduce resolution before effects.
// Node limits apply to the next search rather than the current tree.
// Navigation reuses the current detail image to keep gestures consistent.
const QUALITY_TIERS = Object.freeze({
  high: Object.freeze({
    label: "High detail",
    maxPixelRatio: 2,
    bloom: true,
    effects: true,
    stableDetail: true,
    nodesPerIteration: 120,
  }),
  balanced: Object.freeze({
    label: "Balanced",
    maxPixelRatio: 1.25,
    bloom: true,
    effects: true,
    stableDetail: true,
    nodesPerIteration: 90,
  }),
  low: Object.freeze({
    label: "Smooth (low detail)",
    maxPixelRatio: 1,
    bloom: false,
    effects: false,
    stableDetail: true,
    nodesPerIteration: 55,
  }),
});
const QUALITY_ORDER = Object.freeze(["high", "balanced", "low"]);

// Guard storage because some browsers block access at module load.
function readStored(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch { /* Ignore blocked storage. */ }
}

function storedQualityTier() {
  const stored = readStored("sgurrLabDetail");
  return QUALITY_ORDER.includes(stored) ? stored : "high";
}

let qualityTier = storedQualityTier();
function quality() {
  return QUALITY_TIERS[qualityTier] || QUALITY_TIERS.high;
}
// Enable with ?profile=1 or localStorage.sgurrProfile = "1".
// Profiling tracks frame cadence, long tasks, and rendering time.
const PROFILE = new URLSearchParams(window.location.search).get("profile") === "1"
  || readStored("sgurrProfile") === "1";
const LIVE_STRUCTURE_REFRESH_MS = Object.freeze({ sparse: 66, dense: 100, detail: 150 });
const EFFECT_BUDGETS = Object.freeze({
  full: Object.freeze({ pulses: 90, bursts: 50, cutoffs: 32, wormholes: 18, leaders: 4, activity: 120 }),
  balanced: Object.freeze({ pulses: 48, bursts: 28, cutoffs: 18, wormholes: 10, leaders: 3, activity: 72 }),
  protected: Object.freeze({ pulses: 24, bursts: 14, cutoffs: 10, wormholes: 6, leaders: 2, activity: 36 }),
});
const TAU = Math.PI * 2;

function cssColour(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Cache parsed palette colours because this runs for every node and edge.
const colourChannels = new Map();
const alphaStrings = new Map();

function parseColourChannels(value) {
  const shortHex = /^#([\da-f])([\da-f])([\da-f])$/i.exec(value);
  if (shortHex) {
    const [, r, g, b] = shortHex;
    return `${parseInt(r + r, 16)}, ${parseInt(g + g, 16)}, ${parseInt(b + b, 16)}`;
  }
  const hex = /^#([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(value);
  if (hex) {
    return `${parseInt(hex[1], 16)}, ${parseInt(hex[2], 16)}, ${parseInt(hex[3], 16)}`;
  }
  const rgb = /^rgba?\((\d+)[, ]+(\d+)[, ]+(\d+)/i.exec(value);
  if (rgb) return `${rgb[1]}, ${rgb[2]}, ${rgb[3]}`;
  return null;
}

function withAlpha(colour, alpha) {
  let channels = colourChannels.get(colour);
  if (channels === undefined) {
    channels = parseColourChannels(colour.trim());
    colourChannels.set(colour, channels);
  }
  // Preserve unparseable colours.
  if (channels === null) return colour.trim();
  // Bypass the cache for non-finite alpha values.
  if (!Number.isFinite(alpha)) return `rgba(${channels}, ${alpha})`;
  // Round beyond visible alpha precision to keep the cache bounded.
  const step = Math.round(alpha * 1000);
  let byAlpha = alphaStrings.get(colour);
  if (byAlpha === undefined) {
    byAlpha = new Map();
    alphaStrings.set(colour, byAlpha);
  }
  let text = byAlpha.get(step);
  if (text === undefined) {
    text = `rgba(${channels}, ${step / 1000})`;
    byAlpha.set(step, text);
  }
  return text;
}

function clamp(value, minimum = 0, maximum = 1) {
  return Math.max(minimum, Math.min(maximum, value));
}

function easeOutCubic(value) {
  return 1 - ((1 - clamp(value)) ** 3);
}

function smoothstep(value) {
  const progress = clamp(value);
  return progress * progress * (3 - 2 * progress);
}

function quadraticPoint(edge, progress) {
  const t = clamp(progress);
  const inverse = 1 - t;
  return {
    x: inverse * inverse * edge.from.x + 2 * inverse * t * edge.control.x + t * t * edge.to.x,
    y: inverse * inverse * edge.from.y + 2 * inverse * t * edge.control.y + t * t * edge.to.y,
  };
}

function deterministicUnit(index, salt) {
  const value = Math.sin((index + 1) * (12.9898 + salt * 7.233)) * 43758.5453;
  return value - Math.floor(value);
}

export function initSearchNetwork() {
  const refs = {
    panel: document.querySelector("#networkPanel"),
    canvasWrap: document.querySelector("#networkCanvasWrap"),
    canvas: document.querySelector("#networkCanvas"),
    empty: document.querySelector("#networkEmpty"),
    tooltip: document.querySelector("#networkTooltip"),
    nodeCount: document.querySelector("#networkNodeCount"),
    searchedNodeCount: document.querySelector("#networkSearchedNodeCount"),
    cutoffCount: document.querySelector("#networkCutoffCount"),
    ply: document.querySelector("#networkPly"),
    eventTag: document.querySelector("#networkEventTag"),
    eventText: document.querySelector("#networkEventText"),
    restart: document.querySelector("#networkRestart"),
    play: document.querySelector("#networkPlay"),
    speed: document.querySelector("#networkSpeed"),
    scrubber: document.querySelector("#networkScrubber"),
    progress: document.querySelector("#networkProgressText"),
    engineTime: document.querySelector("#networkEngineTime"),
    engineTimeMode: document.querySelector("#networkEngineTimeMode"),
    zoomOut: document.querySelector("#networkZoomOut"),
    zoomLevel: document.querySelector("#networkZoomLevel"),
    zoomIn: document.querySelector("#networkZoomIn"),
    fitView: document.querySelector("#networkFitView"),
    best: document.querySelector("#networkBest"),
    bestMove: document.querySelector("#networkBestMove"),
    bestScore: document.querySelector("#networkBestScore"),
    streamState: document.querySelector("#networkStreamState"),
  };

  const screenContext = refs.canvas.getContext("2d");
  const backgroundCanvas = document.createElement("canvas");
  const backgroundContext = backgroundCanvas.getContext("2d");
  const depthAtmosphereCanvas = document.createElement("canvas");
  const depthAtmosphereContext = depthAtmosphereCanvas.getContext("2d");
  const staticCanvas = document.createElement("canvas");
  const staticContext = staticCanvas.getContext("2d");
  // Build refinements in a back buffer and swap only when complete.
  let detailCanvas = document.createElement("canvas");
  let detailContext = detailCanvas.getContext("2d");
  let detailBackCanvas = document.createElement("canvas");
  let detailBackContext = detailBackCanvas.getContext("2d");
  const settledCanvas = document.createElement("canvas");
  const settledContext = settledCanvas.getContext("2d");
  const settledDetailCanvas = document.createElement("canvas");
  const settledDetailContext = settledDetailCanvas.getContext("2d");
  const liveStructureCanvas = document.createElement("canvas");
  const liveStructureContext = liveStructureCanvas.getContext("2d");
  const completionSnapshot = document.createElement("canvas");
  const completionSnapshotContext = completionSnapshot.getContext("2d");
  const bloomCanvas = document.createElement("canvas");
  const bloomContext = bloomCanvas.getContext("2d");
  let context = screenContext;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let controller = null;
  let events = [];
  let layoutNodes = new Map();
  let visibleNodes = new Map();
  let cursor = 0;
  let timer = null;
  let animationFrame = null;
  let animationWakeTimer = null;
  let interactionTimer = null;
  let interactionMode = false;
  let navigationReleaseFrame = null;
  let navigationReleaseGeneration = 0;
  let navigationReleaseJob = null;
  let navigationReleaseBuildCount = 0;
  let staticSceneDirty = true;
  let staticSceneBuiltAt = -Infinity;
  let staticSceneReady = false;
  let staticSceneWidth = 0;
  let staticSceneHeight = 0;
  let staticSceneBuildCount = 0;
  let liveStructureDirty = true;
  let liveStructureReady = false;
  let liveStructureBuiltAt = -Infinity;
  let liveStructureWidth = 0;
  let liveStructureHeight = 0;
  let liveStructureBuildCount = 0;
  let detailSceneDirty = true;
  let detailSceneReady = false;
  let detailSceneBuiltAt = -Infinity;
  let detailSceneWidth = 0;
  let detailSceneHeight = 0;
  let detailSceneBuildCount = 0;
  let detailSceneViewport = { scale: 1, x: 0, y: 0 };
  let staticSceneAnimateUntil = 0;
  let settledCachePendingUntil = 0;
  let settledSceneWidth = 0;
  let settledSceneHeight = 0;
  let settledSceneRatio = 0;
  let settledDetailWidth = 0;
  let settledDetailHeight = 0;
  let settledDetailRatio = 0;
  let settledDetailViewportKey = "";
  let settledPasses = new Set();
  let settledDetailPasses = new Set();
  let passFinishedAt = new Map();
  let completionTransitionStartedAt = null;
  let completionChoreographyStartedAt = null;
  let depthShockwaves = [];
  let depthShockwaveCount = 0;
  let bloomBuildCount = 0;
  let bloomDirty = true;
  let backgroundBuildCount = 0;
  let backgroundDirty = true;
  let depthAtmosphereBuildCount = 0;
  let depthAtmosphereDirty = true;
  let depthAtmosphereDepth = 0;
  let paletteCache = null;
  let activeId = null;
  let hoveredTarget = null;
  let finished = false;
  let limitReached = false;
  let rootRemainingDepth = 0;
  let maxDepthRing = 1;
  let pulses = [];
  let bursts = [];
  let cutoffImplosions = [];
  let wormholeFlashes = [];
  let leaderGhosts = [];
  let completedDepths = new Set();
  let cutoffImplosionCount = 0;
  let wormholeFlashCount = 0;
  let leaderChangeCount = 0;
  let rootBest = null;
  let authoritativePv = null;
  const viewport = { scale: 1, x: 0, y: 0 };
  const pointers = new Map();
  let dragState = null;
  let pinchState = null;
  let realReplayClock = null;
  let liveStreaming = false;
  let activeSearchDepth = 0;
  let searchHorizon = 0;
  let tracePass = 0;
  let traceIterationDepth = 0;
  let liveRingCounts = new Map();
  let liveHashes = new Map();
  let activityPoints = [];
  let liveUiFrame = null;
  let pendingLiveAnnouncement = null;
  let engineTimeUs = 0;
  let engineTimerMode = "ready";
  let engineNodesSearched = 0;
  let engineTimerFrame = null;
  let pendingEngineTimer = null;
  let pendingLiveEvents = [];
  let pendingLiveEventCursor = 0;
  let liveEventDrainTask = null;
  let liveEventDrainTaskKind = null;
  let liveEventDrainResolvers = [];
  let liveEventHighWater = 0;
  let evaluationRevision = 0;
  let evaluationProfileCache = new Map();
  let pvPointsCache = new Map();
  let pvPointsRevision = -1;
  let pvNodeIndex = null;
  const glowSpriteCache = new Map();
  let effectBudgetLevel = "full";
  let framePressure = 0.72;
  let lastFrameTimestamp = null;
  let lastDrawnAt = null;
  let countersDirty = true;
  let countersUpdatedAt = -Infinity;

  function palette() {
    if (!paletteCache) {
      paletteCache = {
        blue: cssColour("--network-blue"),
        white: cssColour("--network-white"),
        violet: cssColour("--network-violet"),
        gold: cssColour("--network-gold"),
        amber: cssColour("--network-amber"),
        red: cssColour("--network-red"),
        surface: cssColour("--network-void"),
      };
    }
    return paletteCache;
  }

  function effectBudget() {
    return EFFECT_BUDGETS[effectBudgetLevel] || EFFECT_BUDGETS.full;
  }

  function trimEffects(list, limit) {
    if (list.length > limit) list.splice(0, list.length - limit);
  }

  function glowSprite(colour, requestedRadius) {
    const radius = Math.max(2, Math.round(requestedRadius));
    const key = `${colour}:${radius}`;
    if (glowSpriteCache.has(key)) return glowSpriteCache.get(key);
    const padding = 2;
    const size = (radius + padding) * 2;
    const sprite = document.createElement("canvas");
    sprite.width = size;
    sprite.height = size;
    const spriteContext = sprite.getContext("2d");
    const center = size / 2;
    const gradient = spriteContext.createRadialGradient(center, center, 0, center, center, radius);
    gradient.addColorStop(0, withAlpha(colour, 1));
    gradient.addColorStop(0.18, withAlpha(colour, 0.72));
    gradient.addColorStop(0.52, withAlpha(colour, 0.2));
    gradient.addColorStop(1, withAlpha(colour, 0));
    spriteContext.fillStyle = gradient;
    spriteContext.fillRect(0, 0, size, size);
    const value = { canvas: sprite, radius: radius + padding };
    glowSpriteCache.set(key, value);
    return value;
  }

  function drawCachedGlow(x, y, colour, radius, opacity = 1) {
    if (opacity <= 0 || radius <= 0) return;
    const sprite = glowSprite(colour, radius);
    context.save();
    context.globalCompositeOperation = "lighter";
    context.globalAlpha = clamp(opacity);
    context.drawImage(
      sprite.canvas,
      x - sprite.radius,
      y - sprite.radius,
      sprite.radius * 2,
      sprite.radius * 2,
    );
    context.restore();
  }

  function invalidateEvaluationProfiles() {
    evaluationRevision += 1;
    evaluationProfileCache.clear();
  }

  function markCountersDirty() {
    countersDirty = true;
  }

  function formatEngineTime(timeUs) {
    const microseconds = Math.max(0, Number(timeUs) || 0);
    if (microseconds < 1_000) return { text: `${Math.round(microseconds)} \u00B5s`, unit: "microseconds" };
    const milliseconds = microseconds / 1_000;
    if (milliseconds < 10) return { text: `${milliseconds.toFixed(2)} ms`, unit: "milliseconds" };
    if (milliseconds < 100) return { text: `${milliseconds.toFixed(1)} ms`, unit: "milliseconds" };
    if (milliseconds < 1_000) return { text: `${Math.round(milliseconds)} ms`, unit: "milliseconds" };
    const seconds = milliseconds / 1_000;
    if (seconds < 10) return { text: `${seconds.toFixed(3)} s`, unit: "seconds" };
    if (seconds < 60) return { text: `${seconds.toFixed(2)} s`, unit: "seconds" };
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = (seconds % 60).toFixed(1).padStart(4, "0");
    return { text: `${minutes}m ${remainingSeconds}s`, unit: "minutes" };
  }

  function updateEngineNodesSearched(nodes = engineNodesSearched, mode = engineTimerMode) {
    const numeric = Number(nodes);
    if (!Number.isFinite(numeric)) return;
    engineNodesSearched = Math.max(0, Math.floor(numeric));
    const formatted = engineNodesSearched.toLocaleString("en-GB");
    refs.searchedNodeCount.textContent = formatted;
    refs.searchedNodeCount.title = `${formatted} engine nodes searched`;
    refs.canvas.dataset.engineNodes = String(engineNodesSearched);
    refs.canvas.dataset.engineNodesMode = mode;
  }

  function engineTimerCaption(mode) {
    const captions = {
      ready: "awaiting trace",
      live: "live engine clock",
      recording: "recording engine clock",
      replay: "recorded engine clock",
      complete: "final engine time",
    };
    return captions[mode] || captions.ready;
  }

  function updateEngineTimer(timeUs = engineTimeUs, mode = engineTimerMode) {
    engineTimeUs = Math.max(0, Number(timeUs) || 0);
    engineTimerMode = mode;
    const formatted = formatEngineTime(engineTimeUs);
    refs.engineTime.textContent = formatted.text;
    refs.engineTimeMode.textContent = engineTimerCaption(mode);
    refs.engineTime.title = mode === "replay"
      ? "Original engine search time from the recorded trace; replay speed does not alter this clock."
      : "Elapsed engine search time from the trace.";
    refs.canvas.dataset.engineTimeUs = String(Math.round(engineTimeUs));
    refs.canvas.dataset.engineTimeUnit = formatted.unit;
    refs.canvas.dataset.engineTimeMode = mode;
  }

  function flushQueuedEngineTimer(mode = null) {
    if (engineTimerFrame !== null) window.cancelAnimationFrame(engineTimerFrame);
    engineTimerFrame = null;
    if (pendingEngineTimer) {
      updateEngineTimer(pendingEngineTimer.timeUs, mode || pendingEngineTimer.mode);
      pendingEngineTimer = null;
    } else if (mode) {
      updateEngineTimer(engineTimeUs, mode);
    }
  }

  function queueEngineTimer(timeUs, mode) {
    if (!Number.isFinite(Number(timeUs))) return;
    pendingEngineTimer = { timeUs: Number(timeUs), mode };
    if (engineTimerFrame !== null) return;
    engineTimerFrame = window.requestAnimationFrame(() => flushQueuedEngineTimer());
  }

  function setStreamState(state, label) {
    refs.streamState.dataset.state = state;
    refs.streamState.querySelector("span").textContent = label;
  }

  function stop() {
    if (timer !== null) window.clearTimeout(timer);
    timer = null;
    realReplayClock = null;
    refs.play.textContent = finished && cursor >= events.length ? "Replay" : "Play";
    if (!finished && visibleNodes.size) refs.canvas.dataset.state = "paused";
  }

  function cancelDrawing() {
    if (animationFrame !== null) window.cancelAnimationFrame(animationFrame);
    if (animationWakeTimer !== null) window.clearTimeout(animationWakeTimer);
    animationFrame = null;
    animationWakeTimer = null;
  }

  function cancelLiveEventDrain() {
    if (liveEventDrainTask !== null) {
      if (liveEventDrainTaskKind === "frame") window.cancelAnimationFrame(liveEventDrainTask);
      else window.clearTimeout(liveEventDrainTask);
    }
    liveEventDrainTask = null;
    liveEventDrainTaskKind = null;
    pendingLiveEvents = [];
    pendingLiveEventCursor = 0;
    liveEventDrainResolvers.splice(0).forEach((resolve) => resolve());
  }

  function invalidateStaticScene() {
    staticSceneDirty = true;
    liveStructureDirty = true;
    detailSceneDirty = true;
    invalidateEvaluationProfiles();
    markCountersDirty();
  }

  function invalidateLiveStructure() {
    liveStructureDirty = true;
    detailSceneDirty = true;
    invalidateEvaluationProfiles();
    markCountersDirty();
  }

  function invalidateBloomScene() {
    bloomDirty = true;
  }

  function invalidateDetailScene() {
    detailSceneDirty = true;
  }

  function invalidateBackgroundScene() {
    backgroundDirty = true;
  }

  function invalidateDepthAtmosphereScene() {
    depthAtmosphereDirty = true;
  }

  function invalidateSettledScenes() {
    settledPasses = new Set();
    settledDetailPasses = new Set();
    settledSceneWidth = 0;
    settledSceneHeight = 0;
    settledSceneRatio = 0;
    settledDetailWidth = 0;
    settledDetailHeight = 0;
    settledDetailRatio = 0;
    settledDetailViewportKey = "";
    invalidateStaticScene();
  }

  function cancelNavigationReleaseRefinement() {
    if (navigationReleaseFrame !== null) window.cancelAnimationFrame(navigationReleaseFrame);
    navigationReleaseFrame = null;
    navigationReleaseGeneration += 1;
    navigationReleaseJob = null;
  }

  function finishInteractionImmediately() {
    cancelNavigationReleaseRefinement();
    interactionMode = false;
    refs.canvas.dataset.quality = "full";
    refs.canvas.dataset.navigationRelease = "native-ready";
    requestDraw();
  }

  function finishProgressiveDetailRelease(job) {
    if (navigationReleaseJob !== job || job.generation !== navigationReleaseGeneration) return;
    const finishStartedAt = PROFILE ? performance.now() : 0;
    const previousContext = context;
    context = detailBackContext;
    try {
      context.save();
      applyViewportTransform(job.width, job.height);
      const principal = principalIds();
      const includeLiveStructure = (node) => node.id === 0 || !job.settledPasses.has(Number(node.pass));
      const evaluations = evaluationProfile(includeLiveStructure, `release-live:${tracePass}`);
      drawConnections(job.now, job.width, job.height, job.palette, principal, evaluations, includeLiveStructure);
      drawNodes(job.now, job.width, job.height, job.palette, principal, evaluations, includeLiveStructure);
      drawAuthoritativePv(job.now, job.width, job.height, job.palette);
      context.restore();
      refs.canvas.dataset.evaluatedNodes = String(evaluations.evaluatedCount);
    } finally {
      context = previousContext;
    }

    // Swap the finished image without exposing a partial frame.
    const swappedCanvas = detailCanvas;
    const swappedContext = detailContext;
    detailCanvas = detailBackCanvas;
    detailContext = detailBackContext;
    detailBackCanvas = swappedCanvas;
    detailBackContext = swappedContext;

    detailSceneReady = true;
    detailSceneWidth = job.width;
    detailSceneHeight = job.height;
    detailSceneBuiltAt = performance.now();
    detailSceneViewport = { ...viewport };
    detailSceneDirty = false;
    detailSceneBuildCount += 1;
    navigationReleaseBuildCount += 1;
    refs.canvas.dataset.detailBuilds = String(detailSceneBuildCount);
    refs.canvas.dataset.navigationReleaseBuilds = String(navigationReleaseBuildCount);
    refs.canvas.dataset.navigationReleaseProgress = "1.000";
    navigationReleaseJob = null;
    navigationReleaseFrame = null;
    interactionMode = false;
    refs.canvas.dataset.quality = "full";
    refs.canvas.dataset.navigationRelease = "native-ready";
    refs.canvas.dataset.navigationReleaseStrategy = "staged-pass-slices";
    refs.canvas.dataset.navigationReleaseFallback = "previous-detail-until-ready";
    refs.canvas.dataset.navigationReleaseSwap = "atomic";
    if (PROFILE) recordPhase("release-finish (off-frame)", performance.now() - finishStartedAt);
    requestDraw();
  }

  function runNavigationReleaseSlice(job) {
    navigationReleaseFrame = null;
    if (navigationReleaseJob !== job || job.generation !== navigationReleaseGeneration) return;
    const currentSize = canvasSize();
    if (
      currentSize.width !== job.width
      || currentSize.height !== job.height
      || detailViewportKey(job.width, job.height, job.ratio) !== job.viewportKey
    ) {
      cancelNavigationReleaseRefinement();
      settleInteraction(0);
      return;
    }

    const sliceStartedAt = performance.now();
    let rendered = 0;
    while (
      job.passIndex < job.passes.length
      && rendered < 2
      && (rendered === 0 || performance.now() - sliceStartedAt < NAVIGATION_RELEASE_SLICE_MS)
    ) {
      const pass = job.passes[job.passIndex];
      const includePass = (node) => node.id !== 0 && Number(node.pass) === Number(pass);
      const passNodes = job.index.get(Number(pass));
      const evaluations = evaluationProfile(includePass, `release-pass:${pass}`, passNodes);
      renderPassToContext(
        detailBackContext,
        pass,
        job.now,
        job.width,
        job.height,
        job.palette,
        job.principal,
        evaluations,
        true,
        passNodes,
      );
      job.settledPasses.add(Number(pass));
      job.passIndex += 1;
      rendered += 1;
    }
    const sliceDuration = performance.now() - sliceStartedAt;
    if (PROFILE) recordPhase("release-slice (off-frame)", sliceDuration);
    job.maxSliceDuration = Math.max(job.maxSliceDuration, sliceDuration);
    refs.canvas.dataset.navigationReleaseMaxSliceMs = job.maxSliceDuration.toFixed(2);
    refs.canvas.dataset.navigationReleaseProgress = (
      job.passes.length ? job.passIndex / job.passes.length : 1
    ).toFixed(3);
    refs.canvas.dataset.navigationReleasePassesPerSlice = String(rendered);

    if (job.passIndex < job.passes.length) {
      navigationReleaseFrame = window.requestAnimationFrame(() => runNavigationReleaseSlice(job));
      return;
    }
    finishProgressiveDetailRelease(job);
  }

  function beginNavigationRelease() {
    interactionTimer = null;
    if (!interactionMode) return;
    if (viewport.scale <= NATIVE_DETAIL_MIN_SCALE || !visibleNodes.size || reducedMotion.matches) {
      finishInteractionImmediately();
      return;
    }

    const beginStartedAt = PROFILE ? performance.now() : 0;
    cancelNavigationReleaseRefinement();
    const generation = navigationReleaseGeneration;
    const { width, height, ratio } = canvasSize();
    // Keep the front buffer visible while rebuilding the back buffer.
    // Clearing it would expose the upscaled world bitmap.
    resetLayer(detailBackCanvas, detailBackContext, width, height, ratio);
    const now = performance.now();
    const previousContext = context;
    context = detailBackContext;
    try {
      context.save();
      applyViewportTransform(width, height);
      drawRings(width, height, palette());
      context.restore();
    } finally {
      context = previousContext;
    }

    const index = passIndex();
    const job = {
      generation,
      width,
      height,
      ratio,
      viewportKey: detailViewportKey(width, height, ratio),
      now,
      palette: palette(),
      principal: principalIds(),
      index,
      passes: eligibleSettledPasses(now, index),
      settledPasses: new Set(),
      passIndex: 0,
      maxSliceDuration: 0,
    };
    navigationReleaseJob = job;
    // The front buffer remains valid until the next swap.
    refs.canvas.dataset.quality = "refining";
    refs.canvas.dataset.navigationRelease = "refining";
    refs.canvas.dataset.navigationReleaseStrategy = "staged-pass-slices";
    refs.canvas.dataset.navigationReleaseFallback = "previous-detail-until-ready";
    refs.canvas.dataset.navigationReleaseSwap = "atomic";
    refs.canvas.dataset.navigationReleaseSliceMs = String(NAVIGATION_RELEASE_SLICE_MS);
    refs.canvas.dataset.navigationReleasePasses = String(job.passes.length);
    refs.canvas.dataset.navigationReleaseProgress = "0.000";
    if (PROFILE) recordPhase("release-begin (off-frame)", performance.now() - beginStartedAt);
    navigationReleaseFrame = window.requestAnimationFrame(() => runNavigationReleaseSlice(job));
    requestDraw();
  }

  function setInteractionMode(active) {
    if (interactionTimer !== null) window.clearTimeout(interactionTimer);
    interactionTimer = null;
    // Repeated drag samples need no reset once navigation is active.
    // This also avoids repeated selector checks.
    if (active && interactionMode && navigationReleaseJob === null) {
      requestDraw();
      return;
    }
    cancelNavigationReleaseRefinement();
    interactionMode = active;
    refs.canvas.dataset.quality = active ? "navigation" : "full";
    refs.canvas.dataset.navigationRelease = active ? "navigating" : "native-ready";
    requestDraw();
  }

  // Debounce wheel and keyboard streams to avoid rebuilding mid-gesture.
  // Pointer release ends the gesture immediately.
  function settleInteraction(delay = 140) {
    if (interactionTimer !== null) window.clearTimeout(interactionTimer);
    interactionTimer = window.setTimeout(beginNavigationRelease, delay);
  }

  function pulseInteraction() {
    setInteractionMode(true);
    settleInteraction();
  }

  function clearState() {
    if (timer !== null) window.clearTimeout(timer);
    timer = null;
    if (liveUiFrame !== null) window.cancelAnimationFrame(liveUiFrame);
    liveUiFrame = null;
    pendingLiveAnnouncement = null;
    if (engineTimerFrame !== null) window.cancelAnimationFrame(engineTimerFrame);
    engineTimerFrame = null;
    pendingEngineTimer = null;
    cancelNavigationReleaseRefinement();
    interactionMode = false;
    navigationReleaseBuildCount = 0;
    cancelLiveEventDrain();
    cancelDrawing();
    visibleNodes = new Map();
    cursor = 0;
    activeId = null;
    hoveredTarget = null;
    delete refs.canvas.dataset.hovered;
    delete refs.canvas.dataset.searchLimited;
    finished = false;
    limitReached = false;
    pulses = [];
    bursts = [];
    cutoffImplosions = [];
    wormholeFlashes = [];
    leaderGhosts = [];
    completedDepths = new Set();
    cutoffImplosionCount = 0;
    wormholeFlashCount = 0;
    leaderChangeCount = 0;
    activityPoints = [];
    staticSceneAnimateUntil = 0;
    settledCachePendingUntil = 0;
    passFinishedAt = new Map();
    completionTransitionStartedAt = null;
    completionChoreographyStartedAt = null;
    depthShockwaves = [];
    depthShockwaveCount = 0;
    bloomBuildCount = 0;
    bloomDirty = true;
    backgroundBuildCount = 0;
    backgroundDirty = true;
    depthAtmosphereBuildCount = 0;
    depthAtmosphereDirty = true;
    depthAtmosphereDepth = 0;
    liveStructureDirty = true;
    liveStructureReady = false;
    liveStructureBuiltAt = -Infinity;
    liveStructureWidth = 0;
    liveStructureHeight = 0;
    liveStructureBuildCount = 0;
    evaluationRevision = 0;
    evaluationProfileCache = new Map();
    pvPointsCache = new Map();
    pvPointsRevision = -1;
    pvNodeIndex = null;
    glowSpriteCache.clear();
    effectBudgetLevel = "full";
    framePressure = 0.72;
    lastFrameTimestamp = null;
    countersDirty = true;
    countersUpdatedAt = -Infinity;
    liveEventHighWater = 0;
    invalidateSettledScenes();
    delete refs.canvas.dataset.completionTransition;
    delete refs.canvas.dataset.completionChoreography;
    delete refs.canvas.dataset.completionEmanation;
    delete refs.canvas.dataset.completionEmanationDurationMs;
    refs.canvas.dataset.cutoffImplosions = "0";
    refs.canvas.dataset.wormholeFlashes = "0";
    refs.canvas.dataset.leaderChanges = "0";
    refs.canvas.dataset.leaderGhosts = "0";
    refs.canvas.dataset.leaderStability = "settled";
    refs.canvas.dataset.depthEchoes = "0";
    refs.canvas.dataset.depthEchoDesign = "orbital-memory";
    refs.canvas.dataset.cutoffEffect = "implosion";
    refs.canvas.dataset.transpositionEffect = "wormhole-flash";
    refs.canvas.dataset.leaderEffect = "instability-ghosts";
    refs.canvas.dataset.depthWaves = "0";
    refs.canvas.dataset.bloomBuilds = "0";
    refs.canvas.dataset.backgroundBuilds = "0";
    refs.canvas.dataset.depthAtmosphereBuilds = "0";
    refs.canvas.dataset.liveStructureBuilds = "0";
    refs.canvas.dataset.liveEventQueue = "0";
    refs.canvas.dataset.liveEventQueuePeak = "0";
    refs.canvas.dataset.liveEventSliceMs = String(LIVE_EVENT_SLICE_MS);
    refs.canvas.dataset.eventIngestion = "frame-sliced-queue";
    refs.canvas.dataset.liveCache = "incremental-depth-layer";
    refs.canvas.dataset.liveBloom = "cached-sprites";
    refs.canvas.dataset.glowRenderer = "cached-sprites";
    refs.canvas.dataset.evaluationProfile = "linear-cached";
    refs.canvas.dataset.effectBudget = effectBudgetLevel;
    refs.canvas.dataset.effectBudgetPolicy = "adaptive-transients-only";
    refs.canvas.dataset.liveAnimationPolicy = "continuous-60fps-overlay";
    refs.canvas.dataset.navigationRelease = "native-ready";
    refs.canvas.dataset.navigationReleaseStrategy = "staged-pass-slices";
    refs.canvas.dataset.navigationReleaseSliceMs = String(NAVIGATION_RELEASE_SLICE_MS);
    refs.canvas.dataset.navigationReleaseProgress = "1.000";
    refs.canvas.dataset.navigationReleaseBuilds = "0";
    refs.canvas.dataset.frozenDepths = "0";
    activeSearchDepth = 0;
    searchHorizon = 0;
    liveStreaming = false;
    refs.canvas.dataset.state = "empty";
    refs.play.textContent = "Play";
    refs.scrubber.value = "0";
    refs.nodeCount.textContent = "0";
    refs.cutoffCount.textContent = "0";
    refs.ply.textContent = String(searchHorizon);
    refs.progress.textContent = `0 / ${events.length}`;
    updateEngineTimer(0, events.length ? "replay" : "ready");
    updateEngineNodesSearched(0, events.length ? "replay" : "ready");
    refs.tooltip.hidden = true;
    refs.play.disabled = false;
    refs.speed.disabled = false;
    refs.scrubber.disabled = false;
    rootBest = null;
    authoritativePv = null;
    delete refs.canvas.dataset.pvDepth;
    delete refs.canvas.dataset.pvPlies;
    delete refs.canvas.dataset.pvMoves;
    delete refs.canvas.dataset.pvReveal;
    delete refs.canvas.dataset.survivorGlow;
    delete refs.canvas.dataset.principalHitTargets;
    delete refs.canvas.dataset.selectionStrategy;
    delete refs.canvas.dataset.curatedNodes;
    delete refs.canvas.dataset.curatedPromoted;
    updateBestMove();
    setStreamState("ready", "Ready");
    draw(performance.now());
  }

  function reset(message = "Choose a position, depth, and live or replay mode.") {
    if (controller) controller.abort();
    controller = null;
    events = [];
    layoutNodes = new Map();
    rootRemainingDepth = 0;
    maxDepthRing = 1;
    searchHorizon = 0;
    tracePass = 0;
    traceIterationDepth = 0;
    liveRingCounts = new Map();
    liveHashes = new Map();
    setInteractionMode(false);
    resetViewport();
    refs.scrubber.max = "0";
    refs.canvas.dataset.principalHitRadius = String(PRINCIPAL_HIT_RADIUS_PX);
    refs.canvas.dataset.standardHitRadius = String(STANDARD_HIT_RADIUS_PX);
    refs.empty.hidden = false;
    refs.empty.querySelector("strong").textContent = "Run a search to draw the network";
    refs.empty.querySelector("span").textContent = "The display retains a representative sample of nodes from each completed depth.";
    refs.eventTag.textContent = "READY";
    refs.eventText.textContent = message;
    clearState();
  }

  function keepEvent(event) {
    if (["start", "finish", "limit", "activity", "pv"].includes(event.e)) return true;
    if (event.e === "node" || event.e === "end") {
      return Number(event.localId ?? event.id) < MAX_CAPTURED_NODES_PER_ITERATION;
    }
    if (event.e === "best" || event.e === "cutoff") {
      return Number(event.localId ?? event.id) < MAX_CAPTURED_NODES_PER_ITERATION
        || Number(event.localChild ?? event.child) < MAX_CAPTURED_NODES_PER_ITERATION;
    }
    return false;
  }

  function globalTraceId(localId, pass = tracePass) {
    const id = Number(localId);
    if (!Number.isFinite(id) || id <= 0) return id;
    return pass * ITERATION_ID_STRIDE + id;
  }

  function normalizeTraceEvent(rawEvent) {
    const event = { ...rawEvent };
    if (event.e === "start") {
      tracePass = Number(event.pass) || tracePass + 1;
      traceIterationDepth = Number(event.depth) || tracePass;
    }
    event.pass = Number(event.pass) || tracePass;
    event.iterationDepth = Number(event.iterationDepth) || traceIterationDepth || Number(event.depth) || 0;

    if (event.e === "node") {
      event.localId = Number(event.id);
      event.localParent = Number(event.parent);
      event.id = globalTraceId(event.localId, event.pass);
      event.parent = event.localParent < 0 ? -1 : globalTraceId(event.localParent, event.pass);
    } else if (event.e === "end") {
      event.localId = Number(event.id);
      event.id = globalTraceId(event.localId, event.pass);
    } else if (event.e === "best" || event.e === "cutoff") {
      event.localId = Number(event.id);
      event.localChild = Number(event.child);
      event.id = globalTraceId(event.localId, event.pass);
      event.child = globalTraceId(event.localChild, event.pass);
    }

    if (event.e === "node" || event.e === "activity") {
      event.searchDepth = Math.max(0, event.iterationDepth - Number(event.depth || 0));
    }
    return event;
  }

  function prepareLayout() {
    layoutNodes = new Map();
    events.forEach((event, index) => {
      if (event.e !== "node") return;
      layoutNodes.set(event.id, {
        ...event,
        eventIndex: index,
        children: [],
        angle: -Math.PI / 2,
        pathKey: "",
      });
    });

    layoutNodes.forEach((node) => {
      const parent = layoutNodes.get(node.parent);
      if (parent) parent.children.push(node.id);
    });
    layoutNodes.forEach((node) => node.children.sort((a, b) => a - b));

    const root = layoutNodes.get(0);
    if (root) {
      const assignPath = (node, path) => {
        node.pathKey = path;
        node.children.forEach((childId, index) => {
          const child = layoutNodes.get(childId);
          if (child) assignPath(child, `${path}.${String(index).padStart(3, "0")}`);
        });
      };
      assignPath(root, "000");
    }

    rootRemainingDepth = Number(root?.depth) || 0;
    maxDepthRing = Math.max(1, rootRemainingDepth);
    layoutNodes.forEach((node) => {
      node.searchDepth = Number.isFinite(Number(node.searchDepth))
        ? Number(node.searchDepth)
        : Math.max(0, Number(node.iterationDepth || rootRemainingDepth) - Number(node.depth || 0));
      node.ringIndex = Math.min(maxDepthRing, node.searchDepth);
    });

    for (let ringIndex = 1; ringIndex <= maxDepthRing; ringIndex += 1) {
      const ring = [...layoutNodes.values()]
        .filter((node) => node.ringIndex === ringIndex)
        .sort((a, b) => a.pathKey.localeCompare(b.pathKey) || a.id - b.id);
      ring.forEach((node, index) => {
        // Keep siblings together while spreading each depth evenly.
        node.angle = -Math.PI / 2 + (TAU * index) / Math.max(1, ring.length);
      });
    }

    // Link repeated Zobrist keys back as transpositions or re-searches.
    const firstByHash = new Map();
    [...layoutNodes.values()].sort((a, b) => a.id - b.id).forEach((node) => {
      if (!node.hash) return;
      if (firstByHash.has(node.hash)) node.transpositionSource = firstByHash.get(node.hash);
      else firstByHash.set(node.hash, node.id);
    });
  }

  function hashAngle(hash, fallback) {
    const text = String(hash || fallback || "0");
    let value = 2166136261;
    for (let index = 0; index < text.length; index += 1) {
      value ^= text.charCodeAt(index);
      value = Math.imul(value, 16777619);
    }
    return -Math.PI / 2 + ((value >>> 0) / 4294967296) * TAU;
  }

  function addLiveLayoutNode(event, eventIndex) {
    if (event.e !== "node") return;
    if (layoutNodes.has(event.id)) {
      if (event.id === 0) {
        const root = layoutNodes.get(0);
        Object.assign(root, event, { children: root.children, angle: root.angle, pathKey: root.pathKey });
      }
      return;
    }
    const searchDepth = Number.isFinite(Number(event.searchDepth))
      ? Number(event.searchDepth)
      : Math.max(0, Number(event.iterationDepth || rootRemainingDepth) - Number(event.depth || 0));
    const ringIndex = Math.min(maxDepthRing, searchDepth);
    const slot = liveRingCounts.get(ringIndex) || 0;
    liveRingCounts.set(ringIndex, slot + 1);
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    const node = {
      ...event,
      eventIndex,
      children: [],
      pathKey: String(event.id).padStart(6, "0"),
      searchDepth,
      ringIndex,
      // Golden-angle placement fills an orbit without moving existing nodes.
      angle: event.id === 0 ? -Math.PI / 2 : -Math.PI / 2 + slot * goldenAngle,
    };
    if (node.hash && liveHashes.has(node.hash)) node.transpositionSource = liveHashes.get(node.hash);
    else if (node.hash) liveHashes.set(node.hash, node.id);
    layoutNodes.set(node.id, node);
    const parent = layoutNodes.get(node.parent);
    if (parent) parent.children.push(node.id);
  }

  function updateNodeCopies(id, update) {
    const layout = layoutNodes.get(id);
    const visible = visibleNodes.get(id);
    if (layout) update(layout);
    if (visible && visible !== layout) update(visible);
  }

  function settleConsequentialNodes(pass, now, animate) {
    const pool = [...layoutNodes.values()].filter((node) => node.id !== 0 && Number(node.pass) === pass);
    if (!pool.length) return;

    const byId = new Map(pool.map((node) => [node.id, node]));
    const children = new Map();
    const bestSiblingScore = new Map();
    pool.forEach((node) => {
      if (!children.has(node.parent)) children.set(node.parent, []);
      children.get(node.parent).push(node.id);
      if (Number.isFinite(Number(node.parentScore))) {
        bestSiblingScore.set(
          node.parent,
          Math.max(bestSiblingScore.get(node.parent) ?? -Infinity, Number(node.parentScore)),
        );
      }
    });

    const importance = new Map();
    pool.forEach((node) => {
      const score = Number(node.parentScore);
      const siblingBest = bestSiblingScore.get(node.parent);
      const delta = Number.isFinite(score) && Number.isFinite(siblingBest)
        ? Math.max(0, siblingBest - score)
        : null;
      let value = 8 + Number(node.ringIndex || 0) * 1.8;
      if (delta !== null) value += 42 * Math.exp(-delta / 115);
      if (node.wasLeader) value += 58;
      if (node.bestChild != null) value += 24;
      if (node.cutoff) value += 48;
      if (["tt-hit", "tt-cutoff"].includes(node.reason) || node.transpositionSource != null) value += 34;
      if (["mate", "draw", "stalemate"].includes(node.reason)) value += 72;
      else if (node.reason === "complete") value += 16;
      else if (node.reason === "quiescence") value += 7;
      importance.set(node.id, value + deterministicUnit(node.id, pass) * 0.01);
    });

    // Propagate descendant value so the picker keeps useful bridge nodes.
    [...pool].sort((a, b) => b.id - a.id).forEach((node) => {
      if (!byId.has(node.parent)) return;
      importance.set(
        node.parent,
        Math.max(importance.get(node.parent) || 0, (importance.get(node.id) || 0) * 0.965),
      );
    });

    const rootBranchCache = new Map();
    const rootBranch = (node) => {
      if (rootBranchCache.has(node.id)) return rootBranchCache.get(node.id);
      let cursorNode = node;
      const guard = new Set();
      while (cursorNode && cursorNode.parent !== 0 && byId.has(cursorNode.parent) && !guard.has(cursorNode.id)) {
        guard.add(cursorNode.id);
        cursorNode = byId.get(cursorNode.parent);
      }
      const branch = cursorNode?.id ?? node.id;
      rootBranchCache.set(node.id, branch);
      return branch;
    };

    const selected = new Set();
    const frontier = [...(children.get(0) || [])];
    const branchCounts = new Map();
    const ringCounts = new Map();
    // Fewer nodes per depth reduces every downstream rendering cost.
    const target = Math.min(quality().nodesPerIteration - 1, pool.length);
    while (selected.size < target && frontier.length) {
      let bestIndex = 0;
      let bestValue = -Infinity;
      frontier.forEach((id, index) => {
        const node = byId.get(id);
        if (!node) return;
        const branch = rootBranch(node);
        const branchUse = branchCounts.get(branch) || 0;
        const ringUse = ringCounts.get(node.ringIndex) || 0;
        const value = (importance.get(id) || 0)
          + Number(node.ringIndex || 0) * 1.2
          - branchUse * 2.8
          - ringUse * 0.38;
        if (value > bestValue) {
          bestValue = value;
          bestIndex = index;
        }
      });
      const [id] = frontier.splice(bestIndex, 1);
      const node = byId.get(id);
      if (!node || selected.has(id)) continue;
      selected.add(id);
      const branch = rootBranch(node);
      branchCounts.set(branch, (branchCounts.get(branch) || 0) + 1);
      ringCounts.set(node.ringIndex, (ringCounts.get(node.ringIndex) || 0) + 1);
      frontier.push(...(children.get(id) || []));
    }

    visibleNodes.forEach((node, id) => {
      if (id === 0 || Number(node.pass) !== pass || selected.has(id)) return;
      if (animate) node.retiringAt = now;
      else visibleNodes.delete(id);
    });
    selected.forEach((id) => {
      const source = byId.get(id);
      const existing = visibleNodes.get(id);
      if (existing) {
        const revealedAt = existing.revealedAt;
        const activatedAt = existing.activatedAt;
        Object.assign(existing, source, { revealedAt, activatedAt, settled: true });
        delete existing.retiringAt;
      } else {
        visibleNodes.set(id, {
          ...source,
          revealedAt: animate ? now : now - 1000,
          activatedAt: animate ? now : now - RECONSTRUCTED_TRANSIENT_AGE_MS,
          settled: true,
        });
      }
    });

    refs.canvas.dataset.selectionStrategy = "consequential";
    refs.canvas.dataset.curatedNodes = String(selected.size + 1);
    refs.canvas.dataset.curatedPromoted = String(
      [...selected].filter((id) => Number(byId.get(id)?.localId) >= MAX_VISIBLE_NODES_PER_ITERATION).length,
    );
    staticSceneAnimateUntil = Math.max(staticSceneAnimateUntil, now + (animate ? SETTLE_FADE_MS : 0));
    settledCachePendingUntil = Math.max(settledCachePendingUntil, now + (animate ? SETTLE_FADE_MS : 0));
    invalidateStaticScene();
  }

  function describe(event) {
    if (event.e === "stats") {
      const nodes = Math.max(0, Number(event.nodes) || 0).toLocaleString("en-GB");
      return ["ENGINE WORK", `${nodes} nodes have been searched through depth ${event.iterationDepth || event.depth || 0}.`];
    }
    if (event.e === "node") {
      if (event.kind === "pruned") return ["PRUNED", `${event.move} is rejected before a recursive search.`];
      const searchDepth = Number.isFinite(Number(event.searchDepth))
        ? Number(event.searchDepth)
        : Math.max(0, Number(event.iterationDepth || rootRemainingDepth) - Number(event.depth || 0));
      if (event.move === "null") return ["NULL MOVE", `At search depth ${searchDepth}, Sgurr gives up its turn to test whether the position still clears beta.`];
      return ["EXPLORE", `${event.move || "Root"} enters search depth ${searchDepth}.`];
    }
    if (event.e === "best") return ["NEW BEST", `${event.move} raises this node's best score to ${event.score} centipawns.`];
    if (event.e === "pv") {
      const depth = Number(event.iterationDepth || event.depth || 0);
      const moves = Array.isArray(event.moves) ? event.moves.length : 0;
      return ["PRINCIPAL VARIATION", `Depth ${depth}'s current principal variation contains ${moves} searched plies.`];
    }
    if (event.e === "cutoff") return ["BETA CUTOFF", `${event.move} proves enough. The remaining siblings do not need to be searched.`];
    if (event.e === "activity") {
      const searchDepth = Number.isFinite(Number(event.searchDepth))
        ? Number(event.searchDepth)
        : Math.max(0, Number(event.iterationDepth || rootRemainingDepth) - Number(event.depth || 0));
      return ["LIVE SEARCH", `Sgurr is still exploring at search depth ${searchDepth}; the visible node sample is already full.`];
    }
    if (event.e === "end") {
      const labels = {
        "tt-hit": "TRANSPOSITION",
        "tt-cutoff": "TT CUTOFF",
        "reverse-futility": "REVERSE FUTILITY",
        "null-move": "NULL-MOVE CUTOFF",
        "late-move": "LATE MOVE PRUNED",
        quiescence: "QUIESCENCE",
        complete: "NODE COMPLETE",
        draw: "DRAW",
        mate: "CHECKMATE",
        stalemate: "STALEMATE",
      };
      return [labels[event.reason] || String(event.reason).toUpperCase(), `The node returns ${event.score} centipawns via ${event.reason}.`];
    }
    if (event.e === "finish") {
      const depth = Number(event.iterationDepth || event.depth || 0);
      if (depth < maxDepthRing) {
        return [`DEPTH ${depth} COMPLETE`, `${event.best || "No move"} leads at ${event.score} centipawns. The display retains up to 120 representative nodes for this depth.`];
      }
      return ["SEARCH COMPLETE", `${event.best || "No move"} is best at ${event.score} centipawns. Each depth now shows its retained connected subtree.`];
    }
    if (event.e === "search-limit") {
      return [
        event.reason === "time" ? "SEARCH TIME LIMIT" : "NODE LIMIT REACHED",
        `The demo stopped after depth ${event.depth} completed. The final iteration may be partial.`,
      ];
    }
    if (event.e === "limit") return ["SAMPLE FULL", `This iteration's ${event.count}-node structural sample is full; live activity continues while Sgurr searches.`];
    return ["SEARCH", "Sgurr is adding positions to the network."];
  }

  function displayMove(move) {
    if (!move || move === "0000") return "-";
    if (!/^[a-h][1-8][a-h][1-8][qrbn]?$/i.test(move)) return move;
    const promotion = move[4] ? ` = ${move[4].toUpperCase()}` : "";
    return `${move.slice(0, 2)} → ${move.slice(2, 4)}${promotion}`;
  }

  function displayScore(score) {
    const value = Number(score);
    if (!Number.isFinite(value)) return "Evaluation pending";
    const sign = value > 0 ? "+" : value < 0 ? "−" : "";
    return `${sign}${Math.abs(value / 100).toFixed(2)} · engine evaluation`;
  }

  function updateBestMove(changed = false) {
    if (!rootBest) {
      refs.best.dataset.state = "waiting";
      refs.bestMove.textContent = "-";
      refs.bestScore.textContent = "Waiting for a root move";
      return;
    }
    refs.best.dataset.state = "leader";
    refs.bestMove.textContent = displayMove(rootBest.move);
    refs.bestScore.textContent = `${displayScore(rootBest.score)}${rootBest.final ? " · final" : ""}`;
    if (changed && !reducedMotion.matches) {
      refs.best.classList.remove("best-changed");
      void refs.best.offsetWidth;
      refs.best.classList.add("best-changed");
    }
  }

  function pushPulse(fromId, toId, colour, now, duration = 720) {
    if (reducedMotion.matches || !visibleNodes.has(fromId) || !visibleNodes.has(toId)) return;
    pulses.push({ fromId, toId, colour, startedAt: now, duration });
    trimEffects(pulses, effectBudget().pulses);
  }

  function pushBurst(nodeId, colour, now, size = 34, duration = 900, options = {}) {
    if (reducedMotion.matches || !visibleNodes.has(nodeId)) return;
    bursts.push({ nodeId, colour, startedAt: now, duration, size, ...options });
    trimEffects(bursts, effectBudget().bursts);
  }

  function pushCutoffImplosion(nodeId, now) {
    if (reducedMotion.matches || !visibleNodes.has(nodeId)) return;
    cutoffImplosions.push({ nodeId, startedAt: now, duration: CUTOFF_IMPLOSION_MS });
    const limit = Math.min(effectBudget().cutoffs, visibleNodes.size >= DENSE_NODE_THRESHOLD ? 18 : 32);
    trimEffects(cutoffImplosions, limit);
    cutoffImplosionCount += 1;
    refs.canvas.dataset.cutoffImplosions = String(cutoffImplosionCount);
  }

  function pushWormholeFlash(node, now) {
    if (
      reducedMotion.matches
      || node?.transpositionSource == null
      || !visibleNodes.has(node.id)
      || !visibleNodes.has(node.transpositionSource)
    ) return;
    wormholeFlashes.push({
      fromId: node.transpositionSource,
      toId: node.id,
      startedAt: now,
      duration: WORMHOLE_FLASH_MS,
    });
    trimEffects(wormholeFlashes, effectBudget().wormholes);
    wormholeFlashCount += 1;
    refs.canvas.dataset.wormholeFlashes = String(wormholeFlashCount);
  }

  function pushLeaderGhost(previousBest, nextMove, now) {
    if (reducedMotion.matches || !previousBest?.move || previousBest.move === nextMove) return;
    const nodeIds = [0];
    let node = visibleNodes.get(previousBest.child) || layoutNodes.get(previousBest.child);
    const visited = new Set();
    while (node && !visited.has(node.id) && nodeIds.length <= maxDepthRing) {
      visited.add(node.id);
      nodeIds.push(node.id);
      node = visibleNodes.get(node.bestChild) || layoutNodes.get(node.bestChild);
    }
    if (nodeIds.length < 2) return;
    leaderGhosts.push({
      nodeIds,
      move: previousBest.move,
      startedAt: now,
      duration: LEADER_GHOST_MS,
    });
    trimEffects(leaderGhosts, effectBudget().leaders);
    leaderChangeCount += 1;
    refs.canvas.dataset.leaderChanges = String(leaderChangeCount);
    refs.canvas.dataset.leaderGhosts = String(leaderGhosts.length);
    refs.canvas.dataset.leaderStability = "unstable";
  }

  function pushActivityPoint(activity) {
    activityPoints.push(activity);
    trimEffects(activityPoints, effectBudget().activity);
  }

  function beginCompletionTransition(now) {
    if (reducedMotion.matches || !refs.canvas.width || !refs.canvas.height) {
      completionTransitionStartedAt = null;
      return;
    }
    completionSnapshot.width = refs.canvas.width;
    completionSnapshot.height = refs.canvas.height;
    completionSnapshotContext.setTransform(1, 0, 0, 1, 0, 0);
    completionSnapshotContext.clearRect(0, 0, completionSnapshot.width, completionSnapshot.height);
    completionSnapshotContext.drawImage(refs.canvas, 0, 0);
    completionTransitionStartedAt = now;
  }

  function apply(event, announce = true, animate = true) {
    const now = performance.now();
    // Treat rebuilt history as settled so seeking adds no activation halos.
    const transientAt = animate ? now : now - RECONSTRUCTED_TRANSIENT_AGE_MS;
    const colours = palette();
    const { blue, gold, red } = colours;
    let completedFinalIteration = false;
    let structureChanged = false;

    if (event.e === "stats") {
      updateEngineNodesSearched(event.nodes, engineTimerMode);
    } else if (event.e === "start") {
      structureChanged = true;
      if (animate && !reducedMotion.matches) {
        depthShockwaves.push({
          depth: Number(event.iterationDepth || event.depth || 1),
          startedAt: now,
          duration: DEPTH_SHOCKWAVE_MS,
        });
        if (depthShockwaves.length > 5) depthShockwaves.splice(0, depthShockwaves.length - 5);
        depthShockwaveCount += 1;
        refs.canvas.dataset.depthWaves = String(depthShockwaveCount);
      }
      activeId = 0;
      finished = false;
      searchHorizon = Number(event.iterationDepth || event.depth || 0);
      refs.canvas.dataset.state = "searching";
    } else if (event.e === "node") {
      const layout = layoutNodes.get(event.id);
      if (layout) {
        const existing = visibleNodes.get(event.id);
        if (existing) {
          structureChanged = true;
          existing.activatedAt = transientAt;
          existing.iterationDepth = event.iterationDepth;
          activeId = existing.id;
          activeSearchDepth = existing.searchDepth;
        } else if (Number(event.localId ?? event.id) < MAX_VISIBLE_NODES_PER_ITERATION) {
          structureChanged = true;
          const node = {
            ...layout,
            reason: null,
            bestChild: null,
            cutoff: false,
            parentScore: null,
            evaluatedAt: null,
            wasLeader: false,
            revealedAt: animate ? now : now - RECONSTRUCTED_TRANSIENT_AGE_MS,
            activatedAt: transientAt,
          };
          visibleNodes.set(node.id, node);
          if (node.id === 0) invalidateBloomScene();
          if (animate && node.parent >= 0) pushPulse(node.parent, node.id, blue, now);
          activeId = node.id;
          activeSearchDepth = node.searchDepth;
        } else {
          activeSearchDepth = layout.searchDepth;
          const localId = Number(event.localId ?? event.id);
          const activityStride = visibleNodes.size >= DENSE_NODE_THRESHOLD ? 4 : 2;
          if (animate && localId % activityStride === 0) {
            pushActivityPoint({
              angle: layout.angle,
              ringIndex: layout.ringIndex,
              startedAt: now,
              colour: blue,
            });
          }
        }
      }
    } else if (event.e === "end") {
      updateNodeCopies(event.id, (node) => {
        node.reason = event.reason;
        node.score = event.score;
        const score = Number(event.score);
        node.parentScore = Number.isFinite(score) ? -score : null;
        node.evaluatedAt = transientAt;
        node.completedAt = transientAt;
        node.activatedAt = transientAt;
      });
      const node = visibleNodes.get(event.id);
      if (node) {
        structureChanged = true;
        activeId = node.id;
        if (animate && ["reverse-futility", "null-move", "late-move", "tt-cutoff"].includes(event.reason)) pushBurst(node.id, red, now, 24, 680);
        if (animate && ["tt-hit", "tt-cutoff"].includes(event.reason)) pushWormholeFlash(node, now);
      }
    } else if (event.e === "best") {
      updateNodeCopies(event.id, (node) => {
        if (node.bestChild != null && node.bestChild !== event.child) {
          updateNodeCopies(node.bestChild, (previousLeader) => { previousLeader.wasLeader = true; });
        }
        node.bestChild = event.child;
        node.activatedAt = transientAt;
      });
      updateNodeCopies(event.child, (child) => {
        child.activatedAt = transientAt;
        child.evaluatedAt = transientAt;
        child.parentScore = Number(event.score);
        child.wasLeader = true;
      });
      const child = visibleNodes.get(event.child);
      structureChanged = visibleNodes.has(event.id) || Boolean(child);
      activeId = child?.id ?? event.id;
      activeSearchDepth = (visibleNodes.get(activeId) || layoutNodes.get(event.child) || layoutNodes.get(event.id))?.searchDepth ?? activeSearchDepth;
      if (animate && visibleNodes.has(event.id) && visibleNodes.has(event.child)) {
        pushPulse(event.id, event.child, gold, now, 900);
        pushBurst(event.child, gold, now, 19, 650);
      }
      if (Number(event.id) === 0) {
        const changed = rootBest?.move !== event.move;
        if (animate && changed) pushLeaderGhost(rootBest, event.move, now);
        rootBest = { move: event.move, score: event.score, child: event.child, final: false };
        updateBestMove(animate && changed);
      }
    } else if (event.e === "pv") {
      const moves = Array.isArray(event.moves)
        ? event.moves.filter((move) => /^[a-h][1-8][a-h][1-8][qrbn]?$/i.test(move))
        : [];
      if (moves.length) {
        structureChanged = true;
        const changed = rootBest?.move !== moves[0];
        if (animate && changed) pushLeaderGhost(rootBest, moves[0], now);
        authoritativePv = {
          moves,
          pass: Number(event.pass) || tracePass,
          depth: Number(event.iterationDepth || event.depth) || moves.length,
          score: event.score,
          revealedAt: animate ? now : now - RECONSTRUCTED_TRANSIENT_AGE_MS,
        };
        rootBest = { move: moves[0], score: event.score, child: null, final: false };
        refs.canvas.dataset.pvDepth = String(authoritativePv.depth);
        refs.canvas.dataset.pvPlies = String(moves.length);
        refs.canvas.dataset.pvMoves = moves.join(" ");
        updateBestMove(animate && changed);
        invalidateBloomScene();
        if (animate) pushBurst(0, gold, now, 24, 720);
      }
    } else if (event.e === "cutoff") {
      updateNodeCopies(event.child, (child) => {
        child.cutoff = true;
        child.cutoffAt = transientAt;
        child.activatedAt = transientAt;
        child.evaluatedAt = transientAt;
        child.parentScore = Number(event.score);
      });
      updateNodeCopies(event.id, (node) => { node.cutoffs = (node.cutoffs || 0) + 1; });
      const child = visibleNodes.get(event.child);
      structureChanged = visibleNodes.has(event.id) || Boolean(child);
      activeId = child?.id ?? event.id;
      activeSearchDepth = (visibleNodes.get(activeId) || layoutNodes.get(event.child) || layoutNodes.get(event.id))?.searchDepth ?? activeSearchDepth;
      if (animate) {
        if (child) pushCutoffImplosion(child.id, now);
        pushBurst(activeId, red, now, 42, 1050);
      }
    } else if (event.e === "search-limit") {
      finished = true;
      activeId = 0;
      refs.canvas.dataset.state = "complete";
      refs.canvas.dataset.searchLimited = "true";
      setStreamState("ready", `Capped · depth ${event.depth}/${event.targetDepth}`);
      if (rootBest) rootBest.final = true;
      updateBestMove();
    } else if (event.e === "limit") {
      limitReached = true;
    } else if (event.e === "activity") {
      activeSearchDepth = Number.isFinite(Number(event.searchDepth))
        ? Number(event.searchDepth)
        : Math.max(0, Number(event.iterationDepth || rootRemainingDepth) - Number(event.depth || 0));
      const ringIndex = Math.min(maxDepthRing, activeSearchDepth);
      if (animate) {
        pushActivityPoint({
          angle: hashAngle(event.hash, event.t_us),
          ringIndex,
          startedAt: now,
          colour: blue,
        });
      }
    } else if (event.e === "finish") {
      structureChanged = true;
      const iterationDepth = Number(event.iterationDepth || event.depth || 0);
      const finalIteration = iterationDepth >= maxDepthRing;
      const completedPass = Number(event.pass) || tracePass;
      completedDepths.add(iterationDepth);
      refs.canvas.dataset.depthEchoes = String(completedDepths.size);
      refs.canvas.dataset.depthEchoDesign = "orbital-memory";
      if (finalIteration && animate) beginCompletionTransition(now);
      if (finalIteration && animate && !reducedMotion.matches) {
        completionChoreographyStartedAt = now;
        refs.canvas.dataset.completionChoreography = "active";
      } else if (finalIteration) {
        completionChoreographyStartedAt = null;
        refs.canvas.dataset.completionChoreography = "settled";
      }
      // Bake the final tree once while intermediate depths keep their animation.
      settleConsequentialNodes(completedPass, now, animate && !finalIteration);
        passFinishedAt.set(
        completedPass,
        animate && !finalIteration ? now : now - SETTLE_FADE_MS,
      );
      completedFinalIteration = finalIteration;
      invalidateBloomScene();
      if (finalIteration) staticSceneAnimateUntil = now;
      finished = finalIteration;
      if (finalIteration) refs.canvas.dataset.leaderStability = "locked";
      if (finalIteration && authoritativePv) authoritativePv.revealedAt = now - 760;
      activeId = 0;
      refs.canvas.dataset.state = finalIteration ? "complete" : "searching";
      searchHorizon = Math.max(searchHorizon, iterationDepth);
      activeSearchDepth = 0;
      if (!liveStreaming && finalIteration) setStreamState("complete", "Complete · replay ready");
      else if (liveStreaming && !finalIteration) setStreamState("live", `Depth ${iterationDepth} complete · deepening`);
      rootBest = {
        move: event.best || rootBest?.move,
        score: event.score ?? rootBest?.score,
        child: rootBest?.child,
        final: finalIteration,
      };
      const root = visibleNodes.get(0);
      if (root) {
        root.score = event.score;
        root.evaluatedAt = transientAt;
      }
      updateBestMove(animate && rootBest.move !== "0000");
      if (animate) {
        if (finalIteration) {
          const emanationDuration = COMPLETION_EMANATION_EXPAND_MS + COMPLETION_EMANATION_FADE_MS;
          pushBurst(0, gold, now, 86, emanationDuration, {
            completionEmanation: true,
            expansionDuration: COMPLETION_EMANATION_EXPAND_MS,
          });
          refs.canvas.dataset.completionEmanation = "active";
          refs.canvas.dataset.completionEmanationDurationMs = String(emanationDuration);
        } else {
          pushBurst(0, gold, now, 32, 760);
        }
        if (finalIteration) pushBurst(0, blue, now + 220, 126, 2200);
      }
    }

    if (structureChanged) {
      if (animate && !reducedMotion.matches) {
        const settleDuration = event.e === "finish"
          ? (completedFinalIteration ? 0 : SETTLE_FADE_MS)
          : 820;
        staticSceneAnimateUntil = Math.max(staticSceneAnimateUntil, now + settleDuration);
      }
      invalidateLiveStructure();
    }

    if (announce && event.e !== "stats") {
      const [tag, text] = describe(event);
      refs.eventTag.textContent = tag;
      refs.eventText.textContent = text;
    }
  }

  function principalIds() {
    if (authoritativePv?.moves.length) return new Set([0]);
    const ids = new Set([0]);
    let node = visibleNodes.get(0);
    const guard = new Set();
    while (node?.bestChild != null && !guard.has(node.id)) {
      guard.add(node.id);
      ids.add(node.bestChild);
      node = visibleNodes.get(node.bestChild);
    }
    return ids;
  }

  function canvasSize() {
    // Measure on resize to avoid a layout flush on every frame.
    if (canvasBoxDirty || canvasBox === null) {
      const rect = refs.canvasWrap.getBoundingClientRect();
      canvasBox = { width: rect.width, height: rect.height };
      canvasBoxDirty = false;
    }
    const width = Math.max(320, Math.round(canvasBox.width));
    const height = Math.max(430, Math.round(canvasBox.height));
    // Offscreen layers share this scale, which controls their raster cost.
    const ratio = Math.min(quality().maxPixelRatio, window.devicePixelRatio || 1);
    if (refs.canvas.width !== Math.round(width * ratio) || refs.canvas.height !== Math.round(height * ratio)) {
      refs.canvas.width = Math.round(width * ratio);
      refs.canvas.height = Math.round(height * ratio);
      refs.canvas.style.width = `${width}px`;
      refs.canvas.style.height = `${height}px`;
    }
    screenContext.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { width, height, ratio };
  }

  function updateZoomLevel() {
    refs.zoomLevel.value = `${Math.round(viewport.scale * 100)}%`;
    refs.zoomLevel.textContent = refs.zoomLevel.value;
  }

  function resetViewport() {
    const changed = Math.abs(viewport.scale - 1) > 0.001
      || Math.abs(viewport.x) > 0.5
      || Math.abs(viewport.y) > 0.5;
    if (!changed) {
      recordViewportPosition();
      return false;
    }
    viewport.scale = 1;
    viewport.x = 0;
    viewport.y = 0;
    refs.canvas.dataset.panConstraint = "bounded-overscroll";
    refs.canvas.dataset.panX = "0";
    refs.canvas.dataset.panY = "0";
    invalidateDetailScene();
    updateZoomLevel();
    if (context) requestDraw();
    return true;
  }

  function canvasLocalPoint(clientX, clientY) {
    const rect = refs.canvas.getBoundingClientRect();
    return { x: clientX - rect.left, y: clientY - rect.top };
  }

  function canvasToWorld(local, width, height) {
    const center = { x: width / 2, y: height / 2 };
    return {
      x: center.x + (local.x - center.x - viewport.x) / viewport.scale,
      y: center.y + (local.y - center.y - viewport.y) / viewport.scale,
    };
  }

  function boundedViewportOffset(x, y, scale, width, height) {
    const scaledRadius = geometry(width, height).radius * scale;
    // Keep most of the network visible normally and a useful slice at deep zoom.
    const minimumVisible = Math.min(
      scaledRadius * 1.5,
      Math.min(width, height) * 0.64,
    );
    const limitX = Math.max(0, width / 2 + scaledRadius - minimumVisible);
    const limitY = Math.max(0, height / 2 + scaledRadius - minimumVisible);
    return {
      x: clamp(x, -limitX, limitX),
      y: clamp(y, -limitY, limitY),
    };
  }

  function recordViewportPosition() {
    refs.canvas.dataset.panConstraint = "bounded-overscroll";
    refs.canvas.dataset.panX = viewport.x.toFixed(1);
    refs.canvas.dataset.panY = viewport.y.toFixed(1);
  }

  function setViewportFromAnchor(nextScale, focal, anchorWorld) {
    const { width, height } = canvasSize();
    const center = { x: width / 2, y: height / 2 };
    const scale = clamp(nextScale, 0.55, 4.5);
    const rawX = focal.x - center.x - (anchorWorld.x - center.x) * scale;
    const rawY = focal.y - center.y - (anchorWorld.y - center.y) * scale;
    const { x, y } = boundedViewportOffset(rawX, rawY, scale, width, height);
    const changed = Math.abs(scale - viewport.scale) > 0.0001
      || Math.abs(x - viewport.x) > 0.01
      || Math.abs(y - viewport.y) > 0.01;
    if (!changed) return false;
    viewport.scale = scale;
    viewport.x = x;
    viewport.y = y;
    recordViewportPosition();
    invalidateDetailScene();
    updateZoomLevel();
    requestDraw();
    return true;
  }

  function zoomAt(nextScale, focal = null) {
    const { width, height } = canvasSize();
    const target = focal || { x: width / 2, y: height / 2 };
    const anchor = canvasToWorld(target, width, height);
    return setViewportFromAnchor(nextScale, target, anchor);
  }

  function applyViewportTransform(width, height) {
    context.translate(width / 2 + viewport.x, height / 2 + viewport.y);
    context.scale(viewport.scale, viewport.scale);
    context.translate(-width / 2, -height / 2);
  }

  // Reuse immutable geometry for each canvas size to avoid per-frame garbage.
  let geometryCache = { width: -1, height: -1, value: null };
  let canvasBox = null;
  let canvasBoxDirty = true;

  const phaseTotals = new Map();
  const frameGaps = [];
  const longTasks = [];
  let profileDraws = 0;
  let profileReportedAt = 0;

  function recordPhase(name, ms) {
    const entry = phaseTotals.get(name);
    if (entry) {
      entry.ms += ms;
      entry.calls += 1;
      if (ms > entry.worst) entry.worst = ms;
    } else {
      phaseTotals.set(name, { ms, worst: ms, calls: 1 });
    }
  }

  // Sample cadence independently because settled scenes throttle drawing.
  // This also catches long tasks outside draw().
  function recordFrame() {
    profileDraws += 1;
  }

  function percentile(sorted, fraction) {
    if (!sorted.length) return 0;
    return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * fraction))];
  }

  function reportProfile() {
    const now = performance.now();
    const span = now - profileReportedAt;
    if (span < 500) return;
    const gaps = frameGaps.slice().sort((a, b) => a - b);
    const rows = [...phaseTotals.entries()]
      .map(([name, entry]) => ({
        phase: name,
        "total ms": Number(entry.ms.toFixed(1)),
        "worst ms": Number(entry.worst.toFixed(1)),
        calls: entry.calls,
        "% of wall": Number((100 * entry.ms / span).toFixed(1)),
      }))
      .filter((row) => row["total ms"] > 0)
      .sort((a, b) => b["total ms"] - a["total ms"]);
    const janky = gaps.filter((gap) => gap > 32).length;
    const worstTasks = longTasks.slice().sort((a, b) => b - a).slice(0, 5);
    // eslint-disable-next-line no-console
    console.log(
      `[sgurr] ${span.toFixed(0)}ms | browser ${(1000 * gaps.length / span).toFixed(0)} fps `
      + `(p50 ${percentile(gaps, 0.5).toFixed(1)}ms, p95 ${percentile(gaps, 0.95).toFixed(1)}ms, `
      + `worst ${(gaps.at(-1) || 0).toFixed(0)}ms, ${janky} frames >32ms) `
      + `| app drew ${profileDraws}x `
      + `| long tasks: ${longTasks.length}${worstTasks.length ? ` [${worstTasks.join(", ")}ms]` : ""} `
      + `| ${visibleNodes.size} nodes, zoom ${Math.round(viewport.scale * 100)}%, `
      + `${interactionMode ? "navigating" : "settled"}`,
    );
    if (rows.length) console.table(rows); // eslint-disable-line no-console
    phaseTotals.clear();
    frameGaps.length = 0;
    longTasks.length = 0;
    profileDraws = 0;
    profileReportedAt = now;
  }

  function startProfiling() {
    profileReportedAt = performance.now();
    let previousTick = profileReportedAt;
    const tick = (stamp) => {
      frameGaps.push(stamp - previousTick);
      previousTick = stamp;
      window.requestAnimationFrame(tick);
    };
    window.requestAnimationFrame(tick);
    try {
      new PerformanceObserver((list) => {
        list.getEntries().forEach((entry) => longTasks.push(Math.round(entry.duration)));
      }).observe({ entryTypes: ["longtask"] });
    } catch { /* Long task timing is not available everywhere. */ }
    window.setInterval(reportProfile, 2000);
  }

  function geometry(width, height) {
    if (geometryCache.width !== width || geometryCache.height !== height) {
      geometryCache = {
        width,
        height,
        value: {
          center: { x: width / 2, y: height / 2 },
          radius: Math.max(110, Math.min(width, height) * 0.435),
        },
      };
    }
    return geometryCache.value;
  }

  function point(node, width, height) {
    const { center, radius } = geometry(width, height);
    // Copy the root point so callers cannot alter cached geometry.
    if (!node || node.id === 0) return { x: center.x, y: center.y };
    // Cache trigonometry until the layout changes a node's angle.
    if (node.angleTrigFor !== node.angle || node.angleCos === undefined) {
      node.angleTrigFor = node.angle;
      node.angleCos = Math.cos(node.angle);
      node.angleSin = Math.sin(node.angle);
    }
    const orbit = radius * (Number(node.ringIndex || 0) / maxDepthRing);
    return {
      x: center.x + node.angleCos * orbit,
      y: center.y + node.angleSin * orbit,
    };
  }

  // Derive culling from the current transform so every render pass shares one rule.
  function visibleWorldBounds(padding) {
    const target = context.canvas;
    if (!target || !context.getTransform) return null;
    const matrix = context.getTransform();
    const determinant = matrix.a * matrix.d - matrix.b * matrix.c;
    if (!determinant || !Number.isFinite(determinant)) return null;
    const inverse = matrix.inverse();
    let left = Infinity;
    let right = -Infinity;
    let top = Infinity;
    let bottom = -Infinity;
    for (let corner = 0; corner < 4; corner += 1) {
      const x = corner & 1 ? target.width : 0;
      const y = corner & 2 ? target.height : 0;
      const worldX = inverse.a * x + inverse.c * y + inverse.e;
      const worldY = inverse.b * x + inverse.d * y + inverse.f;
      if (worldX < left) left = worldX;
      if (worldX > right) right = worldX;
      if (worldY < top) top = worldY;
      if (worldY > bottom) bottom = worldY;
    }
    if (!Number.isFinite(left) || !Number.isFinite(top)) return null;
    return {
      left: left - padding,
      right: right + padding,
      top: top - padding,
      bottom: bottom + padding,
    };
  }

  function pointOutsideBounds(position, bounds) {
    return position.x < bounds.left
      || position.x > bounds.right
      || position.y < bounds.top
      || position.y > bounds.bottom;
  }

  // A quadratic curve stays inside its control-point bounding box.
  function edgeOutsideBounds(edge, bounds) {
    const { from, to, control } = edge;
    if (Math.min(from.x, to.x, control.x) > bounds.right) return true;
    if (Math.max(from.x, to.x, control.x) < bounds.left) return true;
    if (Math.min(from.y, to.y, control.y) > bounds.bottom) return true;
    if (Math.max(from.y, to.y, control.y) < bounds.top) return true;
    return false;
  }

  function edgeGeometry(parent, node, width, height) {
    const from = point(parent, width, height);
    const to = point(node, width, height);
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const distance = Math.max(1, Math.hypot(dx, dy));
    const angleDifference = Math.sin((node.angle || 0) - (parent.angle || 0));
    const bend = parent.id === 0 ? 0 : angleDifference * Math.min(26, distance * 0.17);
    return {
      from,
      to,
      control: {
        x: (from.x + to.x) / 2 - (dy / distance) * bend,
        y: (from.y + to.y) / 2 + (dx / distance) * bend,
      },
    };
  }

  // Index PV nodes and cache completed lines to avoid repeated tree scans.
  function pvNodeLookup() {
    if (pvNodeIndex) return pvNodeIndex;
    pvNodeIndex = new Map();
    visibleNodes.forEach((node) => {
      const key = `${Number(node.pass)}:${node.parent}:${node.move}:${Number(node.ringIndex)}`;
      // Keep the first insertion-order match for duplicate keys.
      if (!pvNodeIndex.has(key)) pvNodeIndex.set(key, node);
    });
    return pvNodeIndex;
  }

  function authoritativePvPoints(width, height, pv = authoritativePv) {
    if (!pv?.moves.length) return [];
    if (pvPointsRevision !== evaluationRevision) {
      pvPointsRevision = evaluationRevision;
      pvPointsCache = new Map();
      pvNodeIndex = null;
    }
    const cacheKey = `${width}x${height}:${maxDepthRing}:${pv.pass}:${pv.depth}:${pv.moves.join(",")}`;
    const memoised = pvPointsCache.get(cacheKey);
    if (memoised) return memoised;
    const { center, radius } = geometry(width, height);
    const points = [{ ...center, move: "root", traced: true, ringIndex: 0, pvIndex: 0 }];
    const targetRing = Math.min(maxDepthRing, Math.max(1, pv.depth));
    const moves = pv.moves.slice(0, targetRing);
    const fallbackAngle = hashAngle(moves.join("."), pv.pass);
    let parentId = 0;
    let anchorAngle = fallbackAngle;

    moves.forEach((move, index) => {
      // Selective depth can differ from literal ply after search adjustments.
      // Spread legal PV moves across the horizon to keep the endpoint accurate.
      const ringIndex = Math.max(1, Math.round(((index + 1) / moves.length) * targetRing));
      let tracedNode = null;
      if (parentId !== null) {
        const candidate = pvNodeLookup()
          .get(`${Number(pv.pass)}:${parentId}:${move}:${ringIndex}`);
        // Preserve strict handling of non-numeric pass values.
        if (
          candidate
          && Number(candidate.pass) === pv.pass
          && candidate.parent === parentId
          && candidate.move === move
          && Number(candidate.ringIndex) === ringIndex
        ) {
          tracedNode = candidate;
        }
      }

      if (tracedNode) {
        const tracedPoint = point(tracedNode, width, height);
        points.push({
          ...tracedPoint,
          move,
          traced: true,
          node: tracedNode,
          ringIndex,
          pvIndex: index + 1,
        });
        parentId = tracedNode.id;
        anchorAngle = tracedNode.angle;
        return;
      }

      parentId = null;
      const angle = anchorAngle + Math.sin((index + 1) * 1.17 + pv.pass * 0.43) * 0.075;
      const orbit = radius * (ringIndex / maxDepthRing);
      points.push({
        x: center.x + Math.cos(angle) * orbit,
        y: center.y + Math.sin(angle) * orbit,
        move,
        traced: false,
        ringIndex,
        pvIndex: index + 1,
      });
    });
    pvPointsCache.set(cacheKey, points);
    return points;
  }

  function tracePvPath(points, reveal) {
    if (points.length < 2 || reveal <= 0) return;
    const segmentProgress = reveal * (points.length - 1);
    context.beginPath();
    context.moveTo(points[0].x, points[0].y);
    for (let index = 1; index < points.length; index += 1) {
      const progress = clamp(segmentProgress - (index - 1));
      if (progress <= 0) break;
      const from = points[index - 1];
      const to = points[index];
      context.lineTo(
        from.x + (to.x - from.x) * progress,
        from.y + (to.y - from.y) * progress,
      );
      if (progress < 1) break;
    }
  }

  function drawAuthoritativePv(now, width, height, palette, pv = authoritativePv) {
    const points = authoritativePvPoints(width, height, pv);
    if (points.length < 2) return;
    refs.canvas.dataset.survivorGlow = "persistent";
    refs.canvas.dataset.survivorDesign = "celestial-filament";
    refs.canvas.dataset.survivorEnvelope = "amber-white-core";
    refs.canvas.dataset.principalHitTargets = String(points.length - 1);
    // Bake completion only after the PV reveal reaches full brightness.
    const reveal = finished ? 1 : easeOutCubic((now - pv.revealedAt) / 760);
    refs.canvas.dataset.pvReveal = reveal.toFixed(3);

    context.save();
    context.globalCompositeOperation = "lighter";
    context.lineCap = "round";
    context.lineJoin = "round";
    tracePvPath(points, reveal);
    context.strokeStyle = withAlpha(palette.amber, 0.13);
    context.lineWidth = 10;
    context.shadowColor = palette.amber;
    context.shadowBlur = 28;
    context.stroke();
    context.shadowBlur = 0;

    tracePvPath(points, reveal);
    context.strokeStyle = withAlpha(palette.gold, 0.8);
    context.lineWidth = 3.35;
    context.stroke();

    tracePvPath(points, reveal);
    context.strokeStyle = withAlpha(palette.white, 0.94);
    context.lineWidth = 0.82;
    context.stroke();

    const visibleProgress = reveal * (points.length - 1);
    points.slice(1).forEach((position, index) => {
      if (index + 1 > visibleProgress + 0.001) return;
      const outerRadius = 3;
      context.beginPath();
      context.arc(position.x, position.y, outerRadius, 0, TAU);
      context.fillStyle = withAlpha(palette.gold, 0.88);
      context.shadowColor = palette.gold;
      context.shadowBlur = 15;
      context.fill();
      context.shadowBlur = 0;
      context.beginPath();
      context.arc(position.x, position.y, 0.86, 0, TAU);
      context.fillStyle = withAlpha(palette.white, 0.96);
      context.fill();
    });

    const terminal = points.at(-1);
    if (terminal && reveal >= 0.999) {
      const star = context.createRadialGradient(terminal.x, terminal.y, 0, terminal.x, terminal.y, 11);
      star.addColorStop(0, withAlpha(palette.white, 0.96));
      star.addColorStop(0.18, withAlpha(palette.gold, 0.62));
      star.addColorStop(0.52, withAlpha(palette.amber, 0.2));
      star.addColorStop(1, withAlpha(palette.amber, 0));
      context.fillStyle = star;
      context.fillRect(terminal.x - 11, terminal.y - 11, 22, 22);
      context.beginPath();
      context.moveTo(terminal.x - 8, terminal.y);
      context.lineTo(terminal.x + 8, terminal.y);
      context.moveTo(terminal.x, terminal.y - 8);
      context.lineTo(terminal.x, terminal.y + 8);
      context.strokeStyle = withAlpha(palette.gold, 0.34);
      context.lineWidth = 0.55;
      context.stroke();
      refs.canvas.dataset.terminalStar = finished ? "stable" : "forming";
    } else refs.canvas.dataset.terminalStar = "forming";
    context.restore();
  }

  function drawAuthoritativePvLight(now, width, height, palette) {
    if (!authoritativePv?.moves.length || reducedMotion.matches) return;
    const points = authoritativePvPoints(width, height);
    if (points.length < 2) return;
    const particleCount = finished ? 2 : 1;
    refs.canvas.dataset.survivorParticles = String(particleCount);
    for (let particle = 0; particle < particleCount; particle += 1) {
      const travel = (((now / 2300) + particle / particleCount) % 1) * (points.length - 1);
      const index = Math.min(points.length - 2, Math.floor(travel));
      const from = points[index];
      const to = points[index + 1];
      drawPulse(
        {
          from,
          to,
          control: { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 },
        },
        travel - index,
        particle === 0 ? palette.white : palette.gold,
        particle === 0 ? 0.76 : 0.6,
      );
    }

    if (!finished) return;
    const terminal = points.at(-1);
    const breath = 0.5 + Math.sin(now / 780) * 0.5;
    const radius = 5.5 + breath * 2.3;
    context.save();
    context.globalCompositeOperation = "lighter";
    drawCachedGlow(terminal.x, terminal.y, palette.gold, radius * 2.4, 0.3 + breath * 0.2);
    context.beginPath();
    context.arc(terminal.x, terminal.y, radius, 0, TAU);
    context.strokeStyle = withAlpha(palette.gold, 0.11 + breath * 0.13);
    context.lineWidth = 0.7;
    context.shadowColor = palette.gold;
    context.shadowBlur = navigationReduced() ? 8 : 15;
    context.stroke();
    context.restore();
  }

  function traceEdge(edge) {
    context.beginPath();
    context.moveTo(edge.from.x, edge.from.y);
    context.quadraticCurveTo(edge.control.x, edge.control.y, edge.to.x, edge.to.y);
  }

  function rebuildBackgroundScene(width, height, ratio, palette) {
    const pixelWidth = Math.round(width * ratio);
    const pixelHeight = Math.round(height * ratio);
    if (backgroundCanvas.width !== pixelWidth || backgroundCanvas.height !== pixelHeight) {
      backgroundCanvas.width = pixelWidth;
      backgroundCanvas.height = pixelHeight;
    }
    backgroundContext.setTransform(1, 0, 0, 1, 0, 0);
    backgroundContext.clearRect(0, 0, pixelWidth, pixelHeight);
    backgroundContext.setTransform(ratio, 0, 0, ratio, 0, 0);
    const { center, radius } = geometry(width, height);

    backgroundContext.fillStyle = "#020309";
    backgroundContext.fillRect(0, 0, width, height);

    const midnight = backgroundContext.createLinearGradient(0, 0, width, height);
    midnight.addColorStop(0, withAlpha(palette.violet, 0.14));
    midnight.addColorStop(0.34, withAlpha(palette.surface, 0.06));
    midnight.addColorStop(0.7, withAlpha(palette.surface, 0.18));
    midnight.addColorStop(1, withAlpha(palette.blue, 0.12));
    backgroundContext.fillStyle = midnight;
    backgroundContext.fillRect(0, 0, width, height);

    const paintNebula = (x, y, nebulaRadius, colour, opacity) => {
      const nebula = backgroundContext.createRadialGradient(x, y, 0, x, y, nebulaRadius);
      nebula.addColorStop(0, withAlpha(colour, opacity));
      nebula.addColorStop(0.38, withAlpha(colour, opacity * 0.42));
      nebula.addColorStop(1, withAlpha(colour, 0));
      backgroundContext.fillStyle = nebula;
      backgroundContext.fillRect(x - nebulaRadius, y - nebulaRadius, nebulaRadius * 2, nebulaRadius * 2);
    };
    paintNebula(width * 0.08, height * 0.12, radius * 1.3, palette.violet, 0.17);
    paintNebula(width * 0.94, height * 0.2, radius * 0.88, palette.red, 0.105);
    paintNebula(width * 0.92, height * 0.82, radius * 1.2, palette.blue, 0.155);
    paintNebula(width * 0.28, height * 0.94, radius * 0.8, palette.violet, 0.08);
    paintNebula(center.x, center.y * 1.04, radius * 0.72, palette.gold, 0.025);

    // Add a dark dust lane so the blurred rift reads as distant space.
    const riftGradient = backgroundContext.createLinearGradient(0, height, width, 0);
    riftGradient.addColorStop(0, withAlpha(palette.blue, 0));
    riftGradient.addColorStop(0.18, withAlpha(palette.blue, 0.095));
    riftGradient.addColorStop(0.52, withAlpha(palette.violet, 0.16));
    riftGradient.addColorStop(0.78, withAlpha(palette.red, 0.085));
    riftGradient.addColorStop(1, withAlpha(palette.red, 0));
    backgroundContext.save();
    backgroundContext.globalCompositeOperation = "screen";
    backgroundContext.filter = "blur(24px)";
    backgroundContext.beginPath();
    backgroundContext.moveTo(-radius * 0.4, height * 0.86);
    backgroundContext.bezierCurveTo(
      width * 0.24,
      height * 0.92,
      width * 0.68,
      height * 0.03,
      width + radius * 0.35,
      height * 0.16,
    );
    backgroundContext.strokeStyle = riftGradient;
    backgroundContext.lineWidth = Math.max(52, radius * 0.22);
    backgroundContext.stroke();
    backgroundContext.restore();

    backgroundContext.save();
    backgroundContext.filter = "blur(10px)";
    backgroundContext.beginPath();
    backgroundContext.moveTo(-radius * 0.42, height * 0.875);
    backgroundContext.bezierCurveTo(
      width * 0.24,
      height * 0.94,
      width * 0.68,
      height * 0.055,
      width + radius * 0.36,
      height * 0.175,
    );
    backgroundContext.strokeStyle = "rgba(0, 0, 5, 0.62)";
    backgroundContext.lineWidth = Math.max(16, radius * 0.072);
    backgroundContext.stroke();
    backgroundContext.restore();

    // Layer cloud fragments along the rift's edges.
    backgroundContext.save();
    backgroundContext.globalCompositeOperation = "screen";
    backgroundContext.filter = "blur(9px)";
    for (let index = 0; index < 28; index += 1) {
      const progress = deterministicUnit(index, 37);
      const x = progress * width;
      const spine = height * (0.88 - progress * 0.74);
      const y = spine + (deterministicUnit(index, 38) - 0.5) * radius * 0.34;
      const cloudRadius = radius * (0.045 + deterministicUnit(index, 39) * 0.13);
      const cloud = backgroundContext.createRadialGradient(x, y, 0, x, y, cloudRadius);
      const colour = index % 5 === 0 ? palette.red : index % 2 ? palette.violet : palette.blue;
      cloud.addColorStop(0, withAlpha(colour, 0.045 + deterministicUnit(index, 40) * 0.055));
      cloud.addColorStop(1, withAlpha(colour, 0));
      backgroundContext.fillStyle = cloud;
      backgroundContext.fillRect(x - cloudRadius, y - cloudRadius, cloudRadius * 2, cloudRadius * 2);
    }
    backgroundContext.restore();

    // Keep background filaments faint behind the search tree.
    backgroundContext.save();
    backgroundContext.lineWidth = 0.55;
    for (let index = 0; index < 28; index += 1) {
      const fromX = deterministicUnit(index, 31) * width;
      const fromY = deterministicUnit(index, 32) * height;
      const toX = deterministicUnit(index + 17, 33) * width;
      const toY = deterministicUnit(index + 17, 34) * height;
      const bend = (deterministicUnit(index, 35) - 0.5) * Math.min(width, height) * 0.32;
      backgroundContext.beginPath();
      backgroundContext.moveTo(fromX, fromY);
      backgroundContext.bezierCurveTo(
        center.x + bend,
        fromY * 0.58 + center.y * 0.42,
        center.x - bend,
        toY * 0.58 + center.y * 0.42,
        toX,
        toY,
      );
      const filamentColour = index % 8 === 0 ? palette.red : index % 3 === 0 ? palette.violet : palette.blue;
      backgroundContext.strokeStyle = withAlpha(filamentColour, 0.027 + deterministicUnit(index, 36) * 0.032);
      backgroundContext.stroke();
    }
    backgroundContext.restore();

    backgroundContext.save();
    for (let index = 0; index < 260; index += 1) {
      const x = deterministicUnit(index, 41) * width;
      const y = deterministicUnit(index, 42) * height;
      const distance = Math.hypot(x - center.x, y - center.y);
      const centreDamping = distance < radius * 0.88 ? 0.48 : 1;
      const opacity = (0.035 + deterministicUnit(index, 43) * 0.22) * centreDamping;
      const size = 0.18 + deterministicUnit(index, 44) * (index % 23 === 0 ? 1.45 : 0.62);
      const colour = index % 29 === 0 ? palette.gold : index % 17 === 0 ? palette.red : index % 7 === 0 ? palette.violet : palette.blue;
      backgroundContext.beginPath();
      backgroundContext.arc(x, y, size, 0, TAU);
      backgroundContext.fillStyle = withAlpha(colour, opacity);
      backgroundContext.fill();
      if (index % 47 === 0) {
        backgroundContext.strokeStyle = withAlpha(colour, opacity * 0.72);
        backgroundContext.lineWidth = 0.45;
        backgroundContext.beginPath();
        backgroundContext.moveTo(x - size * 3.4, y);
        backgroundContext.lineTo(x + size * 3.4, y);
        backgroundContext.moveTo(x, y - size * 3.4);
        backgroundContext.lineTo(x, y + size * 3.4);
        backgroundContext.stroke();
      }
    }
    backgroundContext.restore();

    // Bake slow currents here and animate their highlights separately.
    backgroundContext.save();
    backgroundContext.translate(center.x, center.y);
    for (let index = 0; index < 7; index += 1) {
      backgroundContext.save();
      backgroundContext.rotate(index * 0.71);
      backgroundContext.scale(1, 0.58 + index * 0.025);
      backgroundContext.beginPath();
      backgroundContext.arc(0, 0, radius * (0.46 + index * 0.12), -0.58, 0.78);
      backgroundContext.strokeStyle = withAlpha(index % 2 ? palette.violet : palette.blue, 0.027 + index * 0.004);
      backgroundContext.lineWidth = 0.62;
      backgroundContext.stroke();
      backgroundContext.restore();
    }
    backgroundContext.restore();

    // Darken the centre to add depth behind the network.
    const abyss = backgroundContext.createRadialGradient(center.x, center.y, 0, center.x, center.y, radius * 0.94);
    abyss.addColorStop(0, "rgba(0, 0, 4, 0.34)");
    abyss.addColorStop(0.45, "rgba(0, 0, 5, 0.17)");
    abyss.addColorStop(1, "rgba(0, 0, 5, 0)");
    backgroundContext.fillStyle = abyss;
    backgroundContext.fillRect(center.x - radius, center.y - radius, radius * 2, radius * 2);

    const vignetteRadius = Math.max(width, height) * 0.7;
    const vignette = backgroundContext.createRadialGradient(center.x, center.y, radius * 0.3, center.x, center.y, vignetteRadius);
    vignette.addColorStop(0, withAlpha(palette.surface, 0));
    vignette.addColorStop(0.58, "rgba(0, 0, 5, 0.06)");
    vignette.addColorStop(0.82, "rgba(0, 0, 5, 0.43)");
    vignette.addColorStop(1, "rgba(0, 0, 4, 0.92)");
    backgroundContext.fillStyle = vignette;
    backgroundContext.fillRect(0, 0, width, height);

    backgroundDirty = false;
    backgroundBuildCount += 1;
    refs.canvas.dataset.backgroundBuilds = String(backgroundBuildCount);
    refs.canvas.dataset.backgroundDesign = "deep-neural-space";
    refs.canvas.dataset.backgroundMood = "galactic-ominous";
  }

  function drawBackground(now, width, height, ratio, palette) {
    const dimensionsChanged = backgroundCanvas.width !== Math.round(width * ratio)
      || backgroundCanvas.height !== Math.round(height * ratio);
    if (backgroundDirty || dimensionsChanged) rebuildBackgroundScene(width, height, ratio, palette);

    const driftX = Math.sin(now / 17000) * 2.1;
    const driftY = Math.cos(now / 21000) * 1.6;
    const parallaxX = clamp(viewport.x * 0.018, -10, 10) + driftX;
    const parallaxY = clamp(viewport.y * 0.018, -10, 10) + driftY;
    const overscan = 18;
    context.drawImage(
      backgroundCanvas,
      -overscan + parallaxX,
      -overscan + parallaxY,
      width + overscan * 2,
      height + overscan * 2,
    );
    refs.canvas.dataset.backgroundEffects = interactionMode ? "preserved-navigation" : "ambient";

    const { center, radius } = geometry(width, height);
    context.save();
    context.globalCompositeOperation = "screen";
    for (let index = 0; index < 14; index += 1) {
      const x = deterministicUnit(index, 51) * width;
      const y = deterministicUnit(index, 52) * height;
      const twinkle = 0.5 + Math.sin(now / (900 + index * 47) + deterministicUnit(index, 53) * TAU) * 0.5;
      const size = 0.45 + deterministicUnit(index, 54) * 0.75;
      context.beginPath();
      context.arc(x, y, size + twinkle * 0.45, 0, TAU);
      const twinkleColour = index % 9 === 0 ? palette.red : index % 6 === 0 ? palette.gold : palette.white;
      context.fillStyle = withAlpha(twinkleColour, 0.035 + twinkle * 0.17);
      context.fill();
    }

    const currentRotation = now / 42000;
    context.translate(center.x, center.y);
    context.rotate(currentRotation);
    context.scale(1, 0.66);
    context.beginPath();
    context.arc(0, 0, radius * 0.92, -0.34, 0.24);
    context.strokeStyle = withAlpha(palette.red, 0.07);
    context.shadowColor = palette.red;
    context.shadowBlur = 8;
    context.lineWidth = 0.78;
    context.stroke();
    context.shadowBlur = 0;
    context.rotate(Math.PI);
    context.beginPath();
    context.arc(0, 0, radius * 1.04, -0.28, 0.2);
    context.strokeStyle = withAlpha(palette.violet, 0.08);
    context.stroke();
    context.restore();

    if (visibleNodes.size && !reducedMotion.matches) {
      const breath = 0.5 + Math.sin(now / 1700) * 0.5;
      const core = context.createRadialGradient(center.x, center.y, 0, center.x, center.y, 54 + breath * 10);
      core.addColorStop(0, withAlpha(palette.gold, 0.085 + breath * 0.04));
      core.addColorStop(0.28, withAlpha(palette.red, 0.048 + breath * 0.018));
      core.addColorStop(0.58, withAlpha(palette.violet, 0.035));
      core.addColorStop(1, withAlpha(palette.violet, 0));
      context.fillStyle = core;
      context.fillRect(center.x - 68, center.y - 68, 136, 136);
    }
  }

  function rebuildDepthAtmosphereScene(width, height, ratio, palette) {
    const pixelWidth = Math.round(width * ratio);
    const pixelHeight = Math.round(height * ratio);
    depthAtmosphereCanvas.width = pixelWidth;
    depthAtmosphereCanvas.height = pixelHeight;
    depthAtmosphereContext.setTransform(ratio, 0, 0, ratio, 0, 0);
    depthAtmosphereContext.clearRect(0, 0, width, height);
    const { center, radius } = geometry(width, height);
    const shellCount = Math.min(9, Math.max(4, maxDepthRing));

    depthAtmosphereContext.save();
    depthAtmosphereContext.globalCompositeOperation = "screen";
    const volume = depthAtmosphereContext.createRadialGradient(
      center.x,
      center.y,
      radius * 0.08,
      center.x,
      center.y,
      radius * 1.04,
    );
    volume.addColorStop(0, withAlpha(palette.violet, 0.012));
    volume.addColorStop(0.28, withAlpha(palette.blue, 0.018));
    volume.addColorStop(0.64, withAlpha(palette.violet, 0.013));
    volume.addColorStop(0.9, withAlpha(palette.blue, 0.019));
    volume.addColorStop(1, withAlpha(palette.blue, 0));
    depthAtmosphereContext.fillStyle = volume;
    depthAtmosphereContext.fillRect(
      center.x - radius * 1.08,
      center.y - radius * 1.08,
      radius * 2.16,
      radius * 2.16,
    );

    for (let shell = 1; shell <= shellCount; shell += 1) {
      const orbit = radius * (shell / shellCount);
      const thickness = Math.max(12, radius / shellCount * 0.72);
      const haze = depthAtmosphereContext.createRadialGradient(
        center.x,
        center.y,
        Math.max(0, orbit - thickness),
        center.x,
        center.y,
        orbit + thickness,
      );
      const colour = shell % 4 === 0 ? palette.violet : palette.blue;
      const opacity = 0.014 + (shell / shellCount) * 0.008;
      haze.addColorStop(0, withAlpha(colour, 0));
      haze.addColorStop(0.34, withAlpha(colour, opacity * 0.25));
      haze.addColorStop(0.5, withAlpha(colour, opacity));
      haze.addColorStop(0.66, withAlpha(colour, opacity * 0.22));
      haze.addColorStop(1, withAlpha(colour, 0));
      depthAtmosphereContext.fillStyle = haze;
      depthAtmosphereContext.fillRect(
        center.x - orbit - thickness,
        center.y - orbit - thickness,
        (orbit + thickness) * 2,
        (orbit + thickness) * 2,
      );
    }
    depthAtmosphereContext.restore();
    depthAtmosphereDirty = false;
    depthAtmosphereDepth = maxDepthRing;
    depthAtmosphereBuildCount += 1;
    refs.canvas.dataset.depthAtmosphere = "volumetric-shells";
    refs.canvas.dataset.depthAtmosphereShells = String(shellCount);
    refs.canvas.dataset.depthAtmosphereBuilds = String(depthAtmosphereBuildCount);
  }

  function drawDepthAtmosphere(width, height, ratio, palette) {
    const dimensionsChanged = depthAtmosphereCanvas.width !== Math.round(width * ratio)
      || depthAtmosphereCanvas.height !== Math.round(height * ratio);
    if (depthAtmosphereDirty || dimensionsChanged || depthAtmosphereDepth !== maxDepthRing) {
      rebuildDepthAtmosphereScene(width, height, ratio, palette);
    }
    context.save();
    context.globalCompositeOperation = "screen";
    applyViewportTransform(width, height);
    context.drawImage(depthAtmosphereCanvas, 0, 0, width, height);
    context.restore();
  }

  function drawRings(width, height, palette) {
    if (!rootRemainingDepth) return;
    const { center, radius } = geometry(width, height);
    const ringStep = radius / maxDepthRing;
    const labelEvery = ringStep >= 9 ? 1 : ringStep >= 5 ? 2 : 4;
    context.save();
    context.font = "600 9px Bahnschrift, Segoe UI, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.setLineDash([]);
    for (let ringIndex = 1; ringIndex <= maxDepthRing; ringIndex += 1) {
      const orbit = ringStep * ringIndex;
      const showLabel = ringIndex % labelEvery === 0 || ringIndex === maxDepthRing;
      const label = String(ringIndex);
      const measured = showLabel ? context.measureText(label).width : 0;
      const gapHalfAngle = showLabel ? Math.min(0.4, (measured + 8) / (2 * orbit)) : 0;
      const reached = ringIndex <= searchHorizon;
      const frontier = ringIndex === searchHorizon && liveStreaming && !finished;
      context.beginPath();
      context.arc(
        center.x,
        center.y,
        orbit,
        showLabel ? -Math.PI / 2 + gapHalfAngle : 0,
        showLabel ? -Math.PI / 2 + TAU - gapHalfAngle : TAU,
      );
      context.strokeStyle = withAlpha(
        frontier ? palette.gold : palette.blue,
        frontier ? 0.52 : reached ? (ringIndex === maxDepthRing ? 0.28 : 0.16) : 0.065,
      );
      context.lineWidth = frontier ? 1.25 : ringIndex === maxDepthRing ? 0.9 : 0.65;
      if (frontier && !navigationReduced()) {
        context.shadowColor = palette.gold;
        context.shadowBlur = 9;
      }
      context.stroke();
      context.shadowBlur = 0;
      if (completedDepths.has(ringIndex)) {
        const echoSpan = clamp(10 / orbit, 0.11, 0.42);
        const echoOffset = ringIndex * 0.071;
        for (let echoIndex = 0; echoIndex < 3; echoIndex += 1) {
          const echoAngle = -Math.PI / 2 + echoOffset + (TAU * echoIndex) / 3;
          context.beginPath();
          context.arc(center.x, center.y, orbit, echoAngle - echoSpan, echoAngle + echoSpan);
          context.strokeStyle = withAlpha(palette.gold, ringIndex === searchHorizon ? 0.24 : 0.13);
          context.lineWidth = ringIndex === searchHorizon ? 0.85 : 0.55;
          context.stroke();
        }
      }
      if (showLabel) {
        context.fillStyle = withAlpha(frontier ? palette.gold : palette.blue, frontier ? 0.9 : reached ? 0.7 : 0.34);
        context.fillText(label, center.x, center.y - orbit + 0.5);
      }
    }
    context.fillStyle = withAlpha(palette.gold, 0.78);
    context.fillText("0", center.x, center.y + 21);
    context.restore();
  }

  function nodeColour(node, principal, palette) {
    if (principal.has(node.id)) return palette.gold;
    if (node.cutoff || ["reverse-futility", "null-move", "late-move"].includes(node.reason)) return palette.red;
    if (["tt-hit", "tt-cutoff"].includes(node.reason) || node.transpositionSource != null) return palette.violet;
    return palette.blue;
  }

  function nodeSettleOpacity(node, now) {
    if (!node?.retiringAt) return 1;
    return 1 - easeOutCubic((now - node.retiringAt) / SETTLE_FADE_MS);
  }

  function finiteScore(value) {
    if (value === null || value === undefined || value === "") return null;
    const score = Number(value);
    return Number.isFinite(score) ? score : null;
  }

  function scoreForParent(node) {
    const returnedScore = finiteScore(node.parentScore);
    if (returnedScore !== null) return returnedScore;
    const localScore = finiteScore(node.score);
    if (localScore === null) return null;
    return node.parent < 0 ? localScore : -localScore;
  }

  // A narrowed bucket is valid only with its matching inclusion predicate.
  function evaluationProfile(includeNode = () => true, cacheKey = null, nodes = null) {
    if (cacheKey) {
      const cached = evaluationProfileCache.get(cacheKey);
      if (cached?.revision === evaluationRevision) return cached.profile;
    }
    const source = nodes || visibleNodes;
    const bestByGroup = new Map();
    const profile = new Map();
    let evaluatedCount = 0;

    source.forEach((node) => {
      if (!includeNode(node)) return;
      const score = scoreForParent(node);
      if (node.parent < 0 || score === null) return;
      const groupKey = `${node.parent}:${node.pass || node.iterationDepth || 0}`;
      bestByGroup.set(groupKey, Math.max(bestByGroup.get(groupKey) ?? -Infinity, score));
    });

    source.forEach((node) => {
      if (!includeNode(node)) return;
      const score = scoreForParent(node);
      if (score === null) {
        profile.set(node.id, { known: false, energy: 0.42, score: null, delta: null });
        return;
      }
      evaluatedCount += 1;
      if (node.parent < 0) {
        profile.set(node.id, { known: true, energy: 1, score, delta: 0 });
        return;
      }
      const groupKey = `${node.parent}:${node.pass || node.iterationDepth || 0}`;
      const best = bestByGroup.get(groupKey) ?? score;
      const delta = Math.max(0, best - score);
      // Keep a 100 cp deficit visible and compress extreme or mate scores.
      const relative = Math.exp(-Math.min(delta, 1800) / 210);
      const favourability = 0.5 + 0.5 * Math.tanh(score / 260);
      let energy = clamp(0.12 + relative * 0.7 + favourability * 0.18, 0.12, 1);
      if (node.kind === "pruned" || ["reverse-futility", "late-move"].includes(node.reason)) {
        energy = Math.min(energy, 0.22);
      }
      profile.set(node.id, { known: true, energy, score, delta });
    });

    profile.evaluatedCount = evaluatedCount;
    if (cacheKey) evaluationProfileCache.set(cacheKey, { revision: evaluationRevision, profile });
    refs.canvas.dataset.evaluationProfile = "linear-cached";
    return profile;
  }

  function drawConnections(now, width, height, palette, principal, evaluations, includeNode = () => true, nodes = null) {
    const source = nodes || visibleNodes;
    const dense = visibleNodes.size >= DENSE_NODE_THRESHOLD;
    const { center, radius: networkRadius } = geometry(width, height);
    const exposureAt = (position) => {
      if (!dense) return 1;
      const radialDistance = Math.hypot(position.x - center.x, position.y - center.y);
      return 0.48 + smoothstep(radialDistance / (networkRadius * 0.62)) * 0.52;
    };
    const bounds = visibleWorldBounds(EDGE_CULL_PADDING);
    source.forEach((node) => {
      if (!includeNode(node)) return;
      if (node.parent < 0) return;
      const parent = visibleNodes.get(node.parent);
      if (!parent) return;
      const edge = edgeGeometry(parent, node, width, height);
      if (bounds && edgeOutsideBounds(edge, bounds)) return;
      const isPrincipal = principal.has(node.id) && principal.has(parent.id) && parent.bestChild === node.id;
      const reveal = easeOutCubic((now - node.revealedAt) / 620)
        * Math.min(nodeSettleOpacity(node, now), nodeSettleOpacity(parent, now));
      const cut = node.cutoff || ["reverse-futility", "null-move", "late-move"].includes(node.reason);
      const transposition = ["tt-hit", "tt-cutoff"].includes(node.reason) || node.transpositionSource != null;
      const evaluation = evaluations.get(node.id) || { known: false, energy: 0.42 };
      const energy = isPrincipal ? 1 : evaluation.energy;
      const colour = isPrincipal ? palette.gold : cut ? palette.red : transposition ? palette.violet : palette.blue;
      const opacity = isPrincipal
        ? 0.94
        : cut ? 0.28
          : clamp(0.17 + energy * 0.28 + (node.wasLeader ? 0.04 : 0), 0.19, 0.49);
      const exposure = isPrincipal ? 1 : exposureAt(quadraticPoint(edge, 0.5));
      traceEdge(edge);
      context.strokeStyle = withAlpha(colour, reveal * opacity * exposure);
      context.lineWidth = isPrincipal ? 1.95 : 0.66 + energy * 0.31 + (node.wasLeader ? 0.08 : 0);
      if (isPrincipal || (!navigationReduced() && !cut && energy > 0.9)) {
        context.shadowColor = isPrincipal ? palette.gold : colour;
        context.shadowBlur = isPrincipal ? 10 : 4;
      }
      context.stroke();
      context.shadowBlur = 0;
    });

    source.forEach((node) => {
      if (!includeNode(node)) return;
      if (node.transpositionSource == null) return;
      const source = visibleNodes.get(node.transpositionSource);
      if (!source) return;
      const settleOpacity = Math.min(nodeSettleOpacity(node, now), nodeSettleOpacity(source, now));
      if (settleOpacity <= 0) return;
      const from = point(source, width, height);
      const to = point(node, width, height);
      const edge = { from, to, control: center };
      if (bounds && edgeOutsideBounds(edge, bounds)) return;
      context.beginPath();
      context.moveTo(from.x, from.y);
      context.quadraticCurveTo(center.x, center.y, to.x, to.y);
      context.setLineDash([2, 5]);
      const exposure = exposureAt(quadraticPoint(edge, 0.5));
      context.strokeStyle = withAlpha(palette.violet, 0.42 * settleOpacity * exposure);
      context.lineWidth = 0.9;
      if (!navigationReduced()) {
        context.shadowColor = palette.violet;
        context.shadowBlur = 7;
      }
      context.stroke();
      context.setLineDash([]);
      context.shadowBlur = 0;
    });
  }

  function drawPulse(edge, progress, colour, strength = 1) {
    const dense = visibleNodes.size >= DENSE_NODE_THRESHOLD;
    const tailLength = effectBudgetLevel === "protected"
      ? 1
      : effectBudgetLevel === "balanced" || navigationReduced() || dense ? 3 : 6;
    for (let tail = tailLength; tail >= 0; tail -= 1) {
      const tailProgress = clamp(progress - tail * 0.026);
      if (tailProgress <= 0) continue;
      const position = quadraticPoint(edge, tailProgress);
      const alpha = strength * (1 - tail / 7) * (0.16 + progress * 0.72);
      if (tail === 0) drawCachedGlow(position.x, position.y, colour, navigationReduced() ? 6 : 9, alpha * 0.62);
      context.beginPath();
      context.arc(position.x, position.y, tail === 0 ? 2.5 : 1.5, 0, TAU);
      context.fillStyle = withAlpha(colour, alpha);
      context.fill();
    }
  }

  function drawEventLight(now, width, height, palette, principal) {
    pulses.slice(-effectBudget().pulses).forEach((pulse) => {
      const from = visibleNodes.get(pulse.fromId);
      const to = visibleNodes.get(pulse.toId);
      if (!from || !to) return;
      const progress = (now - pulse.startedAt) / pulse.duration;
      if (progress < 0 || progress > 1) return;
      drawPulse(edgeGeometry(from, to, width, height), easeOutCubic(progress), pulse.colour);
    });

    drawAuthoritativePvLight(now, width, height, palette);
    if (navigationReduced() || !finished || reducedMotion.matches) return;
    const ambientEdges = [];
    visibleNodes.forEach((node) => {
      if (ambientEdges.length >= 18) return;
      if (node.parent < 0) return;
      const parent = visibleNodes.get(node.parent);
      if (!parent) return;
      const isPrincipal = principal.has(node.id) && parent.bestChild === node.id;
      const quietCurrent = node.id % 31 === 0 && !node.cutoff;
      if (isPrincipal || quietCurrent) ambientEdges.push({ parent, node, isPrincipal });
    });
    ambientEdges.slice(0, 18).forEach(({ parent, node, isPrincipal }, index) => {
      const progress = ((now / (isPrincipal ? 2100 : 3200)) + index * 0.173) % 1;
      drawPulse(
        edgeGeometry(parent, node, width, height),
        progress,
        isPrincipal ? palette.gold : palette.blue,
        isPrincipal ? 0.5 : 0.19,
      );
    });
  }

  function drawBursts(now, width, height) {
    const denseLimit = visibleNodes.size >= DENSE_NODE_THRESHOLD ? 24 : effectBudget().bursts;
    const visibleBursts = bursts.slice(-Math.min(denseLimit, effectBudget().bursts));
    visibleBursts.forEach((burst) => {
      const node = visibleNodes.get(burst.nodeId);
      if (!node) return;
      const elapsed = now - burst.startedAt;
      const progress = elapsed / burst.duration;
      if (progress < 0 || progress > 1) return;
      const expansionProgress = burst.completionEmanation
        ? clamp(elapsed / burst.expansionDuration)
        : progress;
      const fadeProgress = burst.completionEmanation
        ? clamp((elapsed - burst.expansionDuration) / (burst.duration - burst.expansionDuration))
        : progress;
      const opacity = burst.completionEmanation
        ? Math.cos(fadeProgress * Math.PI / 2)
        : 1 - progress;
      const position = point(node, width, height);
      context.beginPath();
      context.arc(position.x, position.y, 4 + easeOutCubic(expansionProgress) * burst.size, 0, TAU);
      context.strokeStyle = withAlpha(burst.colour, opacity * 0.62);
      context.lineWidth = 0.7 + opacity * 0.7;
      if (!navigationReduced()) {
        context.shadowColor = burst.colour;
        context.shadowBlur = 14 * opacity;
      }
      context.stroke();
      context.shadowBlur = 0;
    });
  }

  function drawCutoffImplosions(now, width, height, palette) {
    cutoffImplosions.slice(-effectBudget().cutoffs).forEach((implosion) => {
      const node = visibleNodes.get(implosion.nodeId);
      if (!node) return;
      const progress = (now - implosion.startedAt) / implosion.duration;
      if (progress < 0 || progress > 1) return;
      const position = point(node, width, height);
      const contraction = 2.2 + (1 - easeOutCubic(progress)) * 17;
      const alpha = Math.sin(Math.PI * progress);
      context.save();
      context.beginPath();
      context.arc(position.x, position.y, contraction, 0, TAU);
      context.strokeStyle = withAlpha(palette.red, alpha * 0.74);
      context.lineWidth = 0.75 + alpha * 0.85;
      context.shadowColor = palette.red;
      context.shadowBlur = navigationReduced() ? 6 : 13;
      context.stroke();
      context.shadowBlur = 0;
      for (let ray = 0; ray < 6; ray += 1) {
        const angle = (TAU * ray) / 6 + deterministicUnit(implosion.nodeId, ray) * 0.38;
        const outer = contraction * (1.18 + deterministicUnit(ray, implosion.nodeId) * 0.34);
        const inner = Math.max(1.2, contraction * 0.44);
        context.beginPath();
        context.moveTo(position.x + Math.cos(angle) * outer, position.y + Math.sin(angle) * outer);
        context.lineTo(position.x + Math.cos(angle) * inner, position.y + Math.sin(angle) * inner);
        context.strokeStyle = withAlpha(palette.red, alpha * 0.42);
        context.lineWidth = 0.55;
        context.stroke();
      }
      context.beginPath();
      context.arc(position.x, position.y, 0.8 + alpha * 1.5, 0, TAU);
      context.fillStyle = withAlpha(palette.white, alpha * 0.72);
      context.fill();
      context.restore();
    });
  }

  function drawWormholeFlashes(now, width, height, palette) {
    const { center } = geometry(width, height);
    wormholeFlashes.slice(-effectBudget().wormholes).forEach((flash) => {
      const source = visibleNodes.get(flash.fromId);
      const destination = visibleNodes.get(flash.toId);
      if (!source || !destination) return;
      const progress = (now - flash.startedAt) / flash.duration;
      if (progress < 0 || progress > 1) return;
      const edge = {
        from: point(source, width, height),
        to: point(destination, width, height),
        control: center,
      };
      const alpha = Math.sin(Math.PI * progress);
      context.save();
      context.beginPath();
      context.moveTo(edge.from.x, edge.from.y);
      context.quadraticCurveTo(edge.control.x, edge.control.y, edge.to.x, edge.to.y);
      context.setLineDash([3, 6]);
      context.lineDashOffset = -progress * 26;
      context.strokeStyle = withAlpha(palette.violet, alpha * 0.72);
      context.lineWidth = 1.2;
      context.shadowColor = palette.violet;
      context.shadowBlur = navigationReduced() ? 7 : 16;
      context.stroke();
      context.setLineDash([]);
      drawPulse(edge, easeOutCubic(progress), palette.violet, alpha * 0.92);
      context.restore();
    });
  }

  function drawLeaderGhosts(now, width, height, palette) {
    leaderGhosts.slice(-effectBudget().leaders).forEach((ghost, ghostIndex) => {
      const progress = (now - ghost.startedAt) / ghost.duration;
      if (progress < 0 || progress > 1) return;
      const nodes = ghost.nodeIds
        .map((id) => visibleNodes.get(id) || layoutNodes.get(id))
        .filter(Boolean);
      if (nodes.length < 2) return;
      const flicker = 0.68 + Math.sin((now + ghostIndex * 113) / 92) * 0.18;
      const alpha = (1 - easeOutCubic(progress)) * flicker;
      context.save();
      context.beginPath();
      const start = point(nodes[0], width, height);
      context.moveTo(start.x, start.y);
      for (let index = 1; index < nodes.length; index += 1) {
        const edge = edgeGeometry(nodes[index - 1], nodes[index], width, height);
        context.quadraticCurveTo(edge.control.x, edge.control.y, edge.to.x, edge.to.y);
      }
      context.setLineDash([4, 6]);
      context.lineDashOffset = progress * 18;
      context.strokeStyle = withAlpha(palette.gold, alpha * 0.62);
      context.lineWidth = 1.35;
      context.shadowColor = palette.gold;
      context.shadowBlur = navigationReduced() ? 6 : 14;
      context.stroke();
      context.setLineDash([]);
      context.restore();
    });
  }

  function drawLiveActivity(now, width, height, palette) {
    if (!activityPoints.length) return;
    const { center, radius } = geometry(width, height);
    const dense = visibleNodes.size >= DENSE_NODE_THRESHOLD;
    const visibleActivity = activityPoints.slice(-Math.min(dense ? 64 : effectBudget().activity, effectBudget().activity));
    visibleActivity.forEach((activity) => {
      const age = (now - activity.startedAt) / 920;
      if (age < 0 || age > 1) return;
      const orbit = radius * (activity.ringIndex / maxDepthRing);
      const progress = easeOutCubic(Math.min(1, age * 2.4));
      const x = center.x + Math.cos(activity.angle) * orbit * progress;
      const y = center.y + Math.sin(activity.angle) * orbit * progress;
      const alpha = (1 - age) * 0.82;
      context.save();
      context.beginPath();
      context.moveTo(
        center.x + Math.cos(activity.angle) * Math.max(0, orbit * progress - 20),
        center.y + Math.sin(activity.angle) * Math.max(0, orbit * progress - 20),
      );
      context.lineTo(x, y);
      context.strokeStyle = withAlpha(activity.colour, alpha * 0.48);
      context.lineWidth = 1;
      if (!navigationReduced() && !dense) {
        context.shadowColor = activity.colour;
        context.shadowBlur = 10;
      }
      context.stroke();
      context.beginPath();
      context.arc(x, y, 1.8 + (1 - age) * 1.2, 0, TAU);
      context.fillStyle = withAlpha(palette.gold, alpha);
      if (!navigationReduced()) {
        context.shadowColor = palette.blue;
        context.shadowBlur = dense ? 7 : 15;
      }
      context.fill();
      context.restore();
    });
  }

  function drawNodes(now, width, height, palette, principal, evaluations, includeNode = () => true, nodes = null) {
    const source = nodes || visibleNodes;
    const densityRadius = visibleNodes.size > 260 ? 1.15 : visibleNodes.size > 120 ? 1.55 : 2.05;
    const dense = visibleNodes.size >= DENSE_NODE_THRESHOLD;
    const bounds = visibleWorldBounds(NODE_CULL_PADDING);
    source.forEach((node) => {
      if (!includeNode(node)) return;
      const position = point(node, width, height);
      if (bounds && pointOutsideBounds(position, bounds)) return;
      const colour = nodeColour(node, principal, palette);
      const evaluation = evaluations.get(node.id) || { known: false, energy: 0.42 };
      const reveal = easeOutCubic((now - node.revealedAt) / 520) * nodeSettleOpacity(node, now);
      const activeEnergy = clamp(1 - (now - (node.activatedAt || 0)) / 920);
      const isPrincipal = principal.has(node.id);
      const isRoot = node.id === 0;
      const isCutoff = node.cutoff || ["reverse-futility", "null-move", "late-move"].includes(node.reason);
      const isTransposition = ["tt-hit", "tt-cutoff"].includes(node.reason) || node.transpositionSource != null;
      const energy = isPrincipal ? 1 : evaluation.energy;
      const depthFraction = Number(node.ringIndex || 0) / Math.max(1, maxDepthRing);
      const exposure = dense && !isPrincipal && !isRoot
        ? 0.66 + smoothstep(depthFraction / 0.56) * 0.34
        : 1;
      const radius = (
        isRoot ? 6.2
          : isPrincipal ? densityRadius + 1.15
            : densityRadius * (0.94 + energy * 0.1)
      ) * reveal;
      let baseOpacity = evaluation.known ? 0.56 + energy * 0.35 : 0.77;
      if (node.kind === "pruned") baseOpacity = 0.42;
      else if (node.reason === "quiescence") baseOpacity = Math.min(baseOpacity, 0.62);

      if ((!navigationReduced() || isPrincipal) && (activeEnergy > 0.01 || isRoot || isPrincipal || energy > 0.84)) {
        const settledEnergy = evaluation.known ? Math.max(0, energy - 0.78) : 0;
        const haloRadius = radius + 4 + activeEnergy * 7 + settledEnergy * 5;
        drawCachedGlow(
          position.x,
          position.y,
          colour,
          haloRadius,
          (0.21 + activeEnergy * 0.23 + settledEnergy * 0.2) * reveal * exposure,
        );
      }

      context.beginPath();
      context.arc(position.x, position.y, radius, 0, TAU);
      context.fillStyle = withAlpha(colour, baseOpacity * reveal * exposure);
      context.fill();

      // Use a fine outer shell to keep dense nodes crisp.
      if (evaluation.known && !isRoot) {
        context.beginPath();
        context.arc(position.x, position.y, radius + 0.42, 0, TAU);
        context.strokeStyle = withAlpha(colour, (0.1 + energy * 0.17) * reveal);
        context.lineWidth = 0.38;
        context.stroke();
      }

      // Cut branches retain a live rim but their centre visibly extinguishes.
      if (isCutoff && !isRoot) {
        context.beginPath();
        context.arc(position.x, position.y, Math.max(0.42, radius * 0.48), 0, TAU);
        context.fillStyle = withAlpha(palette.surface, 0.78 * reveal);
        context.fill();
      }

      if (isPrincipal) {
        context.beginPath();
        context.arc(position.x, position.y, Math.max(0.72, radius * 0.3), 0, TAU);
        context.fillStyle = withAlpha(palette.white, 0.78 * reveal);
        context.shadowColor = palette.gold;
        context.shadowBlur = 11;
        context.fill();
        context.shadowBlur = 0;
        if (!isRoot) {
          context.beginPath();
          context.arc(position.x, position.y, radius + 1.15, 0, TAU);
          context.strokeStyle = withAlpha(palette.gold, 0.34 * reveal);
          context.lineWidth = 0.55;
          context.stroke();
        }
      } else if (!isCutoff && evaluation.known && energy > 0.58) {
        const glintRadius = Math.max(0.22, radius * 0.17);
        context.beginPath();
        context.arc(
          position.x - radius * 0.23,
          position.y - radius * 0.23,
          glintRadius,
          0,
          TAU,
        );
        context.fillStyle = withAlpha(
          palette.white,
          clamp(0.06 + (energy - 0.58) * 0.46, 0.06, 0.25) * reveal,
        );
        context.fill();
      }

      if (node.wasLeader && !isPrincipal && !node.cutoff) {
        context.strokeStyle = withAlpha(palette.blue, 0.18 * reveal);
        context.lineWidth = 0.55;
        context.beginPath();
        context.arc(position.x, position.y, radius + 1.8, -0.18, 1.72);
        context.stroke();
        context.beginPath();
        context.arc(position.x, position.y, radius + 1.8, Math.PI - 0.18, Math.PI + 1.72);
        context.stroke();
      }

      if (isTransposition && !isPrincipal) {
        context.strokeStyle = withAlpha(palette.violet, 0.3 * reveal);
        context.lineWidth = 0.48;
        context.beginPath();
        context.arc(position.x, position.y, radius + 1.15, 0.28, 2.28);
        context.stroke();
        context.beginPath();
        context.arc(position.x, position.y, radius + 1.15, Math.PI + 0.28, Math.PI + 2.28);
        context.stroke();
      }

      if (isRoot) {
        context.beginPath();
        context.arc(position.x, position.y, 11 + activeEnergy * 2, 0, TAU);
        context.strokeStyle = withAlpha(palette.gold, 0.48 + activeEnergy * 0.3);
        context.lineWidth = 1;
        context.stroke();
      }
    });
  }

  function drawActiveDepth(now, width, height, palette, principal) {
    const active = visibleNodes.get(activeId);
    if (!active || active.id === 0 || !active.ringIndex) return;
    const { center, radius } = geometry(width, height);
    const orbit = radius * (active.ringIndex / maxDepthRing);
    const colour = principal.has(active.id) ? palette.gold : nodeColour(active, principal, palette);
    const breath = reducedMotion.matches ? 0.5 : 0.5 + Math.sin(now / 430) * 0.5;
    const sweep = 0.22 + breath * 0.16;

    context.save();
    context.beginPath();
    context.arc(center.x, center.y, orbit, active.angle - sweep, active.angle + sweep);
    context.strokeStyle = withAlpha(colour, 0.34 + breath * 0.2);
    context.lineWidth = 1.2;
    if (!navigationReduced()) {
      context.shadowColor = colour;
      context.shadowBlur = 11 + breath * 8;
    }
    context.stroke();

    const inner = orbit - 7;
    const outer = orbit + 7;
    context.beginPath();
    context.moveTo(center.x + Math.cos(active.angle) * inner, center.y + Math.sin(active.angle) * inner);
    context.lineTo(center.x + Math.cos(active.angle) * outer, center.y + Math.sin(active.angle) * outer);
    context.strokeStyle = withAlpha(colour, 0.72);
    context.lineWidth = 1.4;
    context.stroke();
    context.restore();
  }

  function drawBestTarget(now, width, height, palette) {
    const pvPoints = authoritativePvPoints(width, height);
    const bestNode = visibleNodes.get(rootBest?.child);
    if (pvPoints.length < 2 && !bestNode) return;
    const position = pvPoints[1] || point(bestNode, width, height);
    const rotation = reducedMotion.matches ? 0 : now / 1800;
    const radius = 9 + (reducedMotion.matches ? 0 : Math.sin(now / 520) * 1.2);

    context.save();
    context.strokeStyle = withAlpha(palette.gold, 0.82);
    context.lineWidth = 1.15;
    if (!navigationReduced()) {
      context.shadowColor = palette.gold;
      context.shadowBlur = 13;
    }
    for (let index = 0; index < 3; index += 1) {
      const start = rotation + index * (TAU / 3);
      context.beginPath();
      context.arc(position.x, position.y, radius, start, start + 0.52);
      context.stroke();
    }
    context.restore();
  }

  function drawHoveredTarget(width, height, palette) {
    if (!hoveredTarget) return;
    let position = null;
    if (hoveredTarget.principal) {
      position = authoritativePvPoints(width, height)
        .find((entry) => entry.pvIndex === hoveredTarget.pvIndex) || null;
    } else {
      const node = visibleNodes.get(hoveredTarget.nodeId);
      if (node) position = point(node, width, height);
    }
    if (!position) return;

    const colour = hoveredTarget.principal ? palette.gold : palette.blue;
    const radius = (hoveredTarget.principal ? 8.5 : 6.5) / viewport.scale;
    context.save();
    context.beginPath();
    context.arc(position.x, position.y, radius, 0, TAU);
    context.strokeStyle = withAlpha(colour, 0.88);
    context.lineWidth = 1.15 / viewport.scale;
    context.shadowColor = colour;
    context.shadowBlur = hoveredTarget.principal ? 16 : 9;
    context.stroke();
    context.beginPath();
    context.arc(position.x, position.y, radius * 0.58, 0, TAU);
    context.fillStyle = withAlpha(palette.white, hoveredTarget.principal ? 0.78 : 0.45);
    context.fill();
    context.restore();
  }

  // Group once by pass instead of rescanning all nodes for every pass.
  function passIndex() {
    const index = new Map();
    visibleNodes.forEach((node, id) => {
      if (id === 0) return;
      const pass = Number(node.pass);
      let bucket = index.get(pass);
      if (!bucket) {
        bucket = new Map();
        index.set(pass, bucket);
      }
      bucket.set(id, node);
    });
    return index;
  }

  function eligibleSettledPasses(now, index = null) {
    const tally = index || passIndex();
    const eligible = [];
    passFinishedAt.forEach((finishedAt, pass) => {
      if (now - finishedAt < SETTLE_FADE_MS) return;
      const bucket = tally.get(Number(pass));
      if (!bucket || !bucket.size) return;
      let retiring = false;
      bucket.forEach((node) => { if (node.retiringAt) retiring = true; });
      if (!retiring) eligible.push(Number(pass));
    });
    return eligible.sort((a, b) => a - b);
  }

  function layerDimensionsChanged(canvas, width, height, ratio) {
    return canvas.width !== Math.round(width * ratio)
      || canvas.height !== Math.round(height * ratio);
  }

  function resetLayer(canvas, layerContext, width, height, ratio) {
    const pixelWidth = Math.round(width * ratio);
    const pixelHeight = Math.round(height * ratio);
    if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
    if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
    layerContext.setTransform(1, 0, 0, 1, 0, 0);
    layerContext.clearRect(0, 0, pixelWidth, pixelHeight);
    layerContext.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  function renderPassToContext(
    targetContext,
    pass,
    now,
    width,
    height,
    palette,
    principal,
    evaluations,
    transformed = false,
    passNodes = null,
  ) {
    const previousContext = context;
    const previousInteractionMode = interactionMode;
    context = targetContext;
    interactionMode = false;
    context.save();
    try {
      if (transformed) applyViewportTransform(width, height);
      const includePass = (node) => node.id !== 0 && Number(node.pass) === Number(pass);
      const settledNow = now + 1200;
      drawConnections(settledNow, width, height, palette, principal, evaluations, includePass, passNodes);
      drawNodes(settledNow, width, height, palette, principal, evaluations, includePass, passNodes);
    } finally {
      context.restore();
      interactionMode = previousInteractionMode;
      context = previousContext;
    }
  }

  function ensureSettledWorld(now, width, height, ratio, palette, principal) {
    const dimensionsChanged = settledSceneWidth !== width
      || settledSceneHeight !== height
      || settledSceneRatio !== ratio
      || layerDimensionsChanged(settledCanvas, width, height, ratio);
    if (dimensionsChanged) {
      resetLayer(settledCanvas, settledContext, width, height, ratio);
      settledPasses = new Set();
      liveStructureDirty = true;
      settledSceneWidth = width;
      settledSceneHeight = height;
      settledSceneRatio = ratio;
    }

    const index = passIndex();
    eligibleSettledPasses(now, index).forEach((pass) => {
      if (settledPasses.has(pass)) return;
      const includePass = (node) => node.id !== 0 && Number(node.pass) === Number(pass);
      const passNodes = index.get(Number(pass));
      const passEvaluations = evaluationProfile(includePass, `settled-world:${pass}`, passNodes);
      renderPassToContext(
        settledContext, pass, now, width, height, palette, principal, passEvaluations, false, passNodes,
      );
      settledPasses.add(pass);
      liveStructureDirty = true;
    });
    refs.canvas.dataset.frozenDepths = String(settledPasses.size);
  }

  function detailViewportKey(width, height, ratio) {
    return [
      width,
      height,
      ratio,
      viewport.scale.toFixed(4),
      viewport.x.toFixed(2),
      viewport.y.toFixed(2),
    ].join(":");
  }

  function ensureSettledDetail(now, width, height, ratio, palette, principal) {
    const viewportKey = detailViewportKey(width, height, ratio);
    const dimensionsChanged = settledDetailWidth !== width
      || settledDetailHeight !== height
      || settledDetailRatio !== ratio
      || settledDetailViewportKey !== viewportKey
      || layerDimensionsChanged(settledDetailCanvas, width, height, ratio);
    if (dimensionsChanged) {
      resetLayer(settledDetailCanvas, settledDetailContext, width, height, ratio);
      settledDetailPasses = new Set();
      settledDetailWidth = width;
      settledDetailHeight = height;
      settledDetailRatio = ratio;
      settledDetailViewportKey = viewportKey;
    }

    const settledDetailStartedAt = PROFILE ? performance.now() : 0;
    const index = passIndex();
    eligibleSettledPasses(now, index).forEach((pass) => {
      if (settledDetailPasses.has(pass)) return;
      const includePass = (node) => node.id !== 0 && Number(node.pass) === Number(pass);
      const passNodes = index.get(Number(pass));
      const passEvaluations = evaluationProfile(includePass, `settled-detail:${pass}`, passNodes);
      renderPassToContext(
        settledDetailContext,
        pass,
        now,
        width,
        height,
        palette,
        principal,
        passEvaluations,
        true,
        passNodes,
      );
      settledDetailPasses.add(pass);
    });
    if (PROFILE) recordPhase("settled-detail (in structure)", performance.now() - settledDetailStartedAt);
  }

  // Freeze detail level during zoom so the cached image remains usable.
  // Rebuild native detail after the gesture.
  // Keep effect layers stable during motion to avoid visible shifts.
  function navigationReduced() {
    return interactionMode && !quality().stableDetail;
  }

  function rebuildStaticScene(now, width, height, ratio, palette) {
    const pixelWidth = Math.round(width * ratio);
    const pixelHeight = Math.round(height * ratio);
    if (staticCanvas.width !== pixelWidth || staticCanvas.height !== pixelHeight) {
      staticCanvas.width = pixelWidth;
      staticCanvas.height = pixelHeight;
    }

    staticContext.setTransform(1, 0, 0, 1, 0, 0);
    staticContext.clearRect(0, 0, pixelWidth, pixelHeight);
    staticContext.setTransform(ratio, 0, 0, ratio, 0, 0);

    const previousContext = context;
    context = staticContext;
    try {
      drawRings(width, height, palette);
      if (visibleNodes.size) {
        const principal = principalIds();
        ensureSettledWorld(now, width, height, ratio, palette, principal);
        context.drawImage(settledCanvas, 0, 0, width, height);
      }
    } finally {
      context = previousContext;
    }

    staticSceneReady = true;
    staticSceneWidth = width;
    staticSceneHeight = height;
    staticSceneBuiltAt = now;
    staticSceneDirty = !reducedMotion.matches && now < settledCachePendingUntil;
    staticSceneBuildCount += 1;
    refs.canvas.dataset.staticBuilds = String(staticSceneBuildCount);
    refs.canvas.dataset.cachedNodes = String(settledVisibleNodeCount());
    refs.canvas.dataset.renderStrategy = "world-with-detail";
    refs.canvas.dataset.nodeDesign = "synapse-shells";
    refs.canvas.dataset.staticCache = "completed-depths";
  }

  function rebuildLiveStructureScene(now, width, height, ratio, palette) {
    resetLayer(liveStructureCanvas, liveStructureContext, width, height, ratio);
    const previousContext = context;
    context = liveStructureContext;
    try {
      if (visibleNodes.size) {
        const principal = principalIds();
        const includeLiveStructure = (node) => node.id === 0 || !settledPasses.has(Number(node.pass));
        const evaluations = evaluationProfile(includeLiveStructure, `world-live:${tracePass}`);
        drawConnections(now, width, height, palette, principal, evaluations, includeLiveStructure);
        drawNodes(now, width, height, palette, principal, evaluations, includeLiveStructure);
        drawAuthoritativePv(now, width, height, palette);
        refs.canvas.dataset.evaluatedNodes = String(evaluations.evaluatedCount);
      }
    } finally {
      context = previousContext;
    }
    liveStructureReady = true;
    liveStructureWidth = width;
    liveStructureHeight = height;
    liveStructureBuiltAt = now;
    liveStructureDirty = !reducedMotion.matches && now < staticSceneAnimateUntil;
    liveStructureBuildCount += 1;
    refs.canvas.dataset.liveStructureBuilds = String(liveStructureBuildCount);
    refs.canvas.dataset.liveCache = "incremental-depth-layer";
  }

  function rebuildDetailScene(now, width, height, ratio, palette) {
    const pixelWidth = Math.round(width * ratio);
    const pixelHeight = Math.round(height * ratio);
    if (detailCanvas.width !== pixelWidth || detailCanvas.height !== pixelHeight) {
      detailCanvas.width = pixelWidth;
      detailCanvas.height = pixelHeight;
    }

    detailContext.setTransform(1, 0, 0, 1, 0, 0);
    detailContext.clearRect(0, 0, pixelWidth, pixelHeight);
    detailContext.setTransform(ratio, 0, 0, ratio, 0, 0);

    const previousContext = context;
    context = detailContext;
    try {
      const principal = principalIds();
      ensureSettledDetail(now, width, height, ratio, palette, principal);
      context.save();
      try {
        applyViewportTransform(width, height);
        drawRings(width, height, palette);
      } finally {
        context.restore();
      }
      context.drawImage(settledDetailCanvas, 0, 0, width, height);
      context.save();
      try {
        applyViewportTransform(width, height);
        if (visibleNodes.size) {
          const includeLiveStructure = (node) => node.id === 0 || !settledDetailPasses.has(Number(node.pass));
          const evaluations = evaluationProfile(includeLiveStructure, `detail-live:${tracePass}`);
          drawConnections(now, width, height, palette, principal, evaluations, includeLiveStructure);
          drawNodes(now, width, height, palette, principal, evaluations, includeLiveStructure);
          drawAuthoritativePv(now, width, height, palette);
          refs.canvas.dataset.evaluatedNodes = String(evaluations.evaluatedCount);
        }
      } finally {
        context.restore();
      }
    } finally {
      context = previousContext;
    }

    detailSceneReady = true;
    detailSceneWidth = width;
    detailSceneHeight = height;
    detailSceneBuiltAt = now;
    detailSceneViewport = { ...viewport };
    detailSceneDirty = !reducedMotion.matches && now < staticSceneAnimateUntil;
    detailSceneBuildCount += 1;
    refs.canvas.dataset.detailBuilds = String(detailSceneBuildCount);
  }

  function structuralRefreshInterval(now, detail = false) {
    if (reducedMotion.matches) return 0;
    if (interactionMode) return Infinity;
    const dense = visibleNodes.size >= DENSE_NODE_THRESHOLD;
    if (liveStreaming || timer !== null) {
      if (detail) return LIVE_STRUCTURE_REFRESH_MS.detail;
      const interval = dense ? LIVE_STRUCTURE_REFRESH_MS.dense : LIVE_STRUCTURE_REFRESH_MS.sparse;
      refs.canvas.dataset.structuralRate = dense ? "10fps" : "15fps";
      return interval;
    }
    if (now < staticSceneAnimateUntil) return dense ? (detail ? 125 : 78) : 48;
    return 0;
  }

  function drawStaticScene(now, width, height, ratio, palette) {
    const dimensionsChanged = staticSceneWidth !== width || staticSceneHeight !== height;
    const resolutionChanged = staticCanvas.width !== Math.round(width * ratio)
      || staticCanvas.height !== Math.round(height * ratio);
    const needsNativeDetail = !interactionMode && viewport.scale > NATIVE_DETAIL_MIN_SCALE;
    // Refresh the world fallback less often than native detail while zoomed.
    const refreshInterval = needsNativeDetail ? 360 : structuralRefreshInterval(now);
    const refreshDue = now - staticSceneBuiltAt >= refreshInterval;
    let rebuiltWorldThisFrame = false;
    if (!staticSceneReady
      || dimensionsChanged
      || (!interactionMode && resolutionChanged)
      || (staticSceneDirty && refreshDue)) {
      rebuildStaticScene(now, width, height, ratio, palette);
      rebuiltWorldThisFrame = true;
    }
    if (!staticSceneReady) return;

    const liveDimensionsChanged = liveStructureWidth !== width || liveStructureHeight !== height;
    const liveResolutionChanged = liveStructureCanvas.width !== Math.round(width * ratio)
      || liveStructureCanvas.height !== Math.round(height * ratio);
    const liveRefreshInterval = structuralRefreshInterval(now);
    const liveRefreshDue = now - liveStructureBuiltAt >= liveRefreshInterval;
    if (!liveStructureReady
      || liveDimensionsChanged
      || (!interactionMode && liveResolutionChanged)
      || (liveStructureDirty && liveRefreshDue)) {
      rebuildLiveStructureScene(now, width, height, ratio, palette);
    }

    if (needsNativeDetail) {
      const detailDimensionsChanged = detailSceneWidth !== width || detailSceneHeight !== height;
      const detailResolutionChanged = detailCanvas.width !== Math.round(width * ratio)
        || detailCanvas.height !== Math.round(height * ratio);
      const detailRefreshInterval = structuralRefreshInterval(now, true);
      const detailRefreshDue = now - detailSceneBuiltAt >= detailRefreshInterval;
      if (!detailSceneReady
        || detailDimensionsChanged
        || detailResolutionChanged
        || (detailSceneDirty && detailRefreshDue && !rebuiltWorldThisFrame)) {
        rebuildDetailScene(now, width, height, ratio, palette);
      }
      if (detailSceneReady) {
        context.drawImage(detailCanvas, 0, 0, width, height);
        refs.canvas.dataset.renderLayer = "native-detail";
        return;
      }
    }

    // Keep the detail image during navigation and fill uncovered strips from
    // the world bitmap. Resampling is less distracting than replacing it.
    const stableDetail = quality().stableDetail
      && interactionMode
      && detailSceneReady
      && detailSceneWidth === width
      && detailSceneHeight === height;
    if (stableDetail) {
      const centre = { x: width / 2, y: height / 2 };
      const view = detailSceneViewport;
      const bounds = {
        left: centre.x + (-centre.x - view.x) / view.scale,
        top: centre.y + (-centre.y - view.y) / view.scale,
        width: width / view.scale,
        height: height / view.scale,
      };
      context.save();
      applyViewportTransform(width, height);
      // Fill outside the detail image without overlapping translucent layers.
      context.save();
      context.beginPath();
      context.rect(-width, -height, width * 3, height * 3);
      context.rect(bounds.left, bounds.top, bounds.width, bounds.height);
      context.clip("evenodd");
      context.drawImage(staticCanvas, 0, 0, width, height);
      if (liveStructureReady) context.drawImage(liveStructureCanvas, 0, 0, width, height);
      context.restore();
      context.drawImage(detailCanvas, bounds.left, bounds.top, bounds.width, bounds.height);
      context.restore();
      refs.canvas.dataset.structureState = "stable-detail";
      refs.canvas.dataset.renderLayer = "stable-detail";
      refs.canvas.dataset.detailDuringNavigation = "preserved";
      return;
    }

    context.save();
    applyViewportTransform(width, height);
    context.drawImage(staticCanvas, 0, 0, width, height);
    if (liveStructureReady) context.drawImage(liveStructureCanvas, 0, 0, width, height);
    context.restore();
    refs.canvas.dataset.structureState = staticSceneDirty || liveStructureDirty ? "animating" : "settled";
    refs.canvas.dataset.renderLayer = "complete-world";
  }

  function settledVisibleNodeCount() {
    let count = 0;
    visibleNodes.forEach((node) => {
      if (!node.retiringAt) count += 1;
    });
    return count;
  }

  function updateNetworkCounters(now, force = false) {
    if (!countersDirty || (!force && now - countersUpdatedAt < 100)) return;
    let nodes = 0;
    let cutoffs = 0;
    visibleNodes.forEach((node) => {
      if (node.retiringAt) return;
      nodes += 1;
      cutoffs += node.cutoffs || 0;
    });
    refs.nodeCount.textContent = String(nodes);
    refs.cutoffCount.textContent = String(cutoffs);
    countersDirty = false;
    countersUpdatedAt = now;
  }

  function drawCompletionTransition(now, width, height) {
    if (completionTransitionStartedAt === null) return;
    const progress = (now - completionTransitionStartedAt) / COMPLETION_CROSSFADE_MS;
    if (progress >= 1) {
      completionTransitionStartedAt = null;
      refs.canvas.dataset.completionTransition = "settled";
      return;
    }
    refs.canvas.dataset.completionTransition = "crossfade";
    context.save();
    context.globalAlpha = 1 - easeOutCubic(progress);
    context.drawImage(completionSnapshot, 0, 0, width, height);
    context.restore();
  }

  function choreographyProgress(now) {
    if (completionChoreographyStartedAt === null) return null;
    return clamp((now - completionChoreographyStartedAt) / COMPLETION_CHOREOGRAPHY_MS);
  }

  function survivorTravel(progress) {
    return easeOutCubic(clamp((progress - 0.08) / 0.64));
  }

  function survivorAccent(progress) {
    return 1 - easeOutCubic(clamp((progress - 0.78) / 0.22));
  }

  function pvPointAtProgress(points, progress) {
    if (!points.length) return null;
    const travel = clamp(progress) * (points.length - 1);
    const index = Math.min(points.length - 2, Math.floor(travel));
    const segment = travel - index;
    const from = points[Math.max(0, index)];
    const to = points[Math.min(points.length - 1, index + 1)];
    return {
      x: from.x + (to.x - from.x) * segment,
      y: from.y + (to.y - from.y) * segment,
    };
  }

  function drawDepthShockwaves(now, width, height, palette) {
    if (!depthShockwaves.length) return;
    const { center, radius } = geometry(width, height);
    depthShockwaves.forEach((wave) => {
      const age = (now - wave.startedAt) / wave.duration;
      if (age < 0 || age > 1) return;
      const targetRadius = radius * (Math.min(maxDepthRing, wave.depth) / maxDepthRing);
      const orbit = targetRadius * easeOutCubic(age);
      const alpha = Math.sin(Math.PI * age);
      context.beginPath();
      context.arc(center.x, center.y, orbit, 0, TAU);
      context.strokeStyle = withAlpha(palette.blue, alpha * 0.48);
      context.lineWidth = 0.75 + alpha * 0.65;
      context.stroke();
      if (age > 0.68) {
        context.beginPath();
        context.arc(center.x, center.y, targetRadius, 0, TAU);
        context.strokeStyle = withAlpha(palette.gold, (1 - age) * 0.55);
        context.lineWidth = 1.05;
        context.stroke();
      }
    });
  }

  function drawCompletionSurvivor(now, width, height, palette) {
    const progress = choreographyProgress(now);
    if (progress === null || progress >= 1) return;
    const points = authoritativePvPoints(width, height);
    if (points.length < 2) return;
    const travel = survivorTravel(progress);
    const accent = survivorAccent(progress);
    context.save();
    context.lineCap = "round";
    context.lineJoin = "round";
    tracePvPath(points, travel);
    context.strokeStyle = withAlpha(palette.gold, 0.82 * accent);
    context.lineWidth = 3.4;
    context.stroke();
    tracePvPath(points, travel);
    context.strokeStyle = withAlpha(palette.white, 0.92 * accent);
    context.lineWidth = 0.95;
    context.stroke();
    const head = pvPointAtProgress(points, travel);
    if (head) {
      context.beginPath();
      context.arc(head.x, head.y, 3.1 + accent * 1.4, 0, TAU);
      drawCachedGlow(head.x, head.y, palette.gold, 12, 0.64 * accent);
      context.fillStyle = withAlpha(palette.white, 0.96 * accent);
      context.fill();
    }
    context.restore();
  }

  function drawBloomLayer(now, width, height, ratio, palette) {
    if (!quality().bloom) {
      refs.canvas.dataset.bloomState = "disabled";
      return;
    }
    refs.canvas.dataset.bloomState = interactionMode ? "cached-navigation" : "active";
    const bloomRatio = Math.max(0.5, ratio * BLOOM_RESOLUTION_SCALE);
    const pixelWidth = Math.round(width * bloomRatio);
    const pixelHeight = Math.round(height * bloomRatio);
    const dimensionsChanged = bloomCanvas.width !== pixelWidth || bloomCanvas.height !== pixelHeight;
    if (dimensionsChanged) {
      bloomCanvas.width = pixelWidth;
      bloomCanvas.height = pixelHeight;
    }
    if (dimensionsChanged || (!interactionMode && bloomDirty)) {
      bloomContext.setTransform(1, 0, 0, 1, 0, 0);
      bloomContext.clearRect(0, 0, pixelWidth, pixelHeight);
      bloomContext.setTransform(bloomRatio, 0, 0, bloomRatio, 0, 0);

      const previousContext = context;
      context = bloomContext;
      try {
        context.save();
        context.globalCompositeOperation = "lighter";

        const root = visibleNodes.get(0);
        if (root) {
          const position = point(root, width, height);
          const radius = finished ? 25 : 18;
          drawCachedGlow(position.x, position.y, palette.gold, radius, finished ? 0.42 : 0.27);
          drawCachedGlow(position.x, position.y, palette.blue, radius * 0.72, 0.16);
        }

        const pvPoints = authoritativePvPoints(width, height);
        if (pvPoints.length > 1) {
          const reveal = 1;
          tracePvPath(pvPoints, reveal);
          context.filter = finished ? "blur(5px)" : "none";
          context.strokeStyle = withAlpha(palette.amber, finished ? 0.25 : 0.17);
          context.lineWidth = finished ? 14 : 6;
          context.stroke();
          if (finished) {
            tracePvPath(pvPoints, reveal);
            context.filter = "blur(2px)";
            context.strokeStyle = withAlpha(palette.gold, 0.2);
            context.lineWidth = 7;
            context.stroke();
          }
          context.filter = "none";

          if (finished) {
            const terminal = pvPoints.at(-1);
            const starRadius = 22;
            drawCachedGlow(terminal.x, terminal.y, palette.white, starRadius * 0.42, 0.34);
            drawCachedGlow(terminal.x, terminal.y, palette.amber, starRadius, 0.2);
          }
        }
        context.restore();
      } finally {
        context = previousContext;
      }
      bloomDirty = false;
      bloomBuildCount += 1;
      refs.canvas.dataset.bloomBuilds = String(bloomBuildCount);
    }

    context.save();
    context.globalCompositeOperation = "screen";
    context.globalAlpha = 0.94;
    applyViewportTransform(width, height);
    context.drawImage(bloomCanvas, 0, 0, width, height);
    context.restore();
    refs.canvas.dataset.bloomLayer = "half-resolution";
    refs.canvas.dataset.bloomAlignment = "world-space";
    refs.canvas.dataset.liveBloom = "cached-sprites";
  }

  function draw(now = performance.now()) {
    const { width, height, ratio } = canvasSize();
    context.clearRect(0, 0, width, height);
    const colours = palette();
    let phaseAt = PROFILE ? performance.now() : 0;
    const lap = (name) => {
      if (!PROFILE) return;
      const next = performance.now();
      recordPhase(name, next - phaseAt);
      phaseAt = next;
    };
    drawBackground(now, width, height, ratio, colours);
    lap("background");
    drawDepthAtmosphere(width, height, ratio, colours);
    lap("atmosphere");
    drawStaticScene(now, width, height, ratio, colours);
    lap("structure");
    drawCompletionTransition(now, width, height);
    lap("completion");
    drawBloomLayer(now, width, height, ratio, colours);
    lap("bloom");
    context.save();
    applyViewportTransform(width, height);
    refs.ply.textContent = String(searchHorizon);
    if (!visibleNodes.size) {
      context.restore();
      if (PROFILE) recordPhase("__frame", performance.now() - phaseAt);
      return;
    }

    const principal = principalIds();
    lap("principal");
    // Skip blur-heavy effects on tiers that disable them.
    if (quality().effects) {
      drawEventLight(now, width, height, colours, principal);
      drawLeaderGhosts(now, width, height, colours);
      drawWormholeFlashes(now, width, height, colours);
      drawCutoffImplosions(now, width, height, colours);
      drawBursts(now, width, height);
      lap("effects");
      drawLiveActivity(now, width, height, colours);
      lap("activity");
    }
    drawActiveDepth(now, width, height, colours, principal);
    drawBestTarget(now, width, height, colours);
    drawHoveredTarget(width, height, colours);
    drawDepthShockwaves(now, width, height, colours);
    drawCompletionSurvivor(now, width, height, colours);
    lap("overlays");
    context.restore();
    updateNetworkCounters(now, finished);
    if (PROFILE) recordFrame();
  }

  function updateAdaptiveEffectBudget(frameTimestamp, drawDuration) {
    const frameInterval = lastFrameTimestamp === null ? 16.7 : frameTimestamp - lastFrameTimestamp;
    lastFrameTimestamp = frameTimestamp;
    const sample = Math.max(drawDuration / 8.5, frameInterval / 19);
    framePressure = framePressure * 0.86 + sample * 0.14;
    const nextLevel = framePressure > 1.18
      ? "protected"
      : framePressure > 0.9 ? "balanced" : "full";
    if (nextLevel !== effectBudgetLevel) {
      effectBudgetLevel = nextLevel;
      const budget = effectBudget();
      trimEffects(pulses, budget.pulses);
      trimEffects(bursts, budget.bursts);
      trimEffects(cutoffImplosions, budget.cutoffs);
      trimEffects(wormholeFlashes, budget.wormholes);
      trimEffects(leaderGhosts, budget.leaders);
      trimEffects(activityPoints, budget.activity);
    }
    refs.canvas.dataset.effectBudget = effectBudgetLevel;
    refs.canvas.dataset.framePressure = framePressure.toFixed(3);
    refs.canvas.dataset.lastDrawMs = drawDuration.toFixed(2);
  }

  function shouldKeepDrawing(now) {
    if (refs.panel.hidden || !visibleNodes.size || document.hidden) return false;
    if (liveStreaming && !reducedMotion.matches) return true;
    if (finished && !reducedMotion.matches) return true;
    if (timer !== null) return true;
    if (pulses.some((pulse) => now - pulse.startedAt <= pulse.duration)) return true;
    if (bursts.some((burst) => now - burst.startedAt <= burst.duration)) return true;
    if (cutoffImplosions.some((effect) => now - effect.startedAt <= effect.duration)) return true;
    if (wormholeFlashes.some((effect) => now - effect.startedAt <= effect.duration)) return true;
    if (leaderGhosts.some((effect) => now - effect.startedAt <= effect.duration)) return true;
    if (activityPoints.some((activity) => now - activity.startedAt <= 920)) return true;
    if (depthShockwaves.some((wave) => now - wave.startedAt <= wave.duration)) return true;
    if (completionChoreographyStartedAt !== null
      && now - completionChoreographyStartedAt <= COMPLETION_CHOREOGRAPHY_MS) return true;
    const active = visibleNodes.get(activeId);
    return Boolean(active && now - (active.activatedAt || 0) < 1000);
  }

  function nextFrameDelay(now) {
    if (interactionMode || reducedMotion.matches) return 0;
    const dense = visibleNodes.size >= DENSE_NODE_THRESHOLD;
    const transitionActive = completionTransitionStartedAt !== null
      && now - completionTransitionStartedAt < COMPLETION_CROSSFADE_MS;
    const effectsActive = transitionActive
      || pulses.length > 0
      || bursts.length > 0
      || cutoffImplosions.length > 0
      || wormholeFlashes.length > 0
      || leaderGhosts.length > 0
      || activityPoints.length > 0
      || depthShockwaves.length > 0
      || (completionChoreographyStartedAt !== null
        && now - completionChoreographyStartedAt < COMPLETION_CHOREOGRAPHY_MS)
      || now < staticSceneAnimateUntil;
    if ((liveStreaming || timer !== null) && dense) {
      refs.canvas.dataset.animationRate = "60fps-overlay";
      return 0;
    }
    if (liveStreaming || timer !== null) {
      refs.canvas.dataset.animationRate = "60fps-overlay";
      return 0;
    }
    if (finished) {
      refs.canvas.dataset.animationRate = effectsActive ? "30fps-finish" : "24fps-ambient";
      return effectsActive ? 16 : 26;
    }
    refs.canvas.dataset.animationRate = "60fps";
    return 0;
  }

  function scheduleNextDraw(delay) {
    if (animationFrame !== null || animationWakeTimer !== null) return;
    if (delay <= 0) {
      animationFrame = window.requestAnimationFrame(drawFrame);
      return;
    }
    animationWakeTimer = window.setTimeout(() => {
      animationWakeTimer = null;
      animationFrame = window.requestAnimationFrame(drawFrame);
    }, delay);
  }

  function drawFrame(now) {
    animationFrame = null;
    // Cap callbacks near 60 Hz because they may outpace the display refresh.
    if (lastDrawnAt !== null && now - lastDrawnAt < MIN_FRAME_INTERVAL_MS) {
      scheduleNextDraw(MIN_FRAME_INTERVAL_MS - (now - lastDrawnAt));
      return;
    }
    lastDrawnAt = now;
    pulses = pulses.filter((pulse) => now - pulse.startedAt <= pulse.duration);
    const hadCompletionEmanation = bursts.some((burst) => burst.completionEmanation);
    bursts = bursts.filter((burst) => now - burst.startedAt <= burst.duration);
    if (hadCompletionEmanation && !bursts.some((burst) => burst.completionEmanation)) {
      refs.canvas.dataset.completionEmanation = "settled";
    }
    cutoffImplosions = cutoffImplosions.filter((effect) => now - effect.startedAt <= effect.duration);
    wormholeFlashes = wormholeFlashes.filter((effect) => now - effect.startedAt <= effect.duration);
    const hadLeaderGhosts = leaderGhosts.length > 0;
    leaderGhosts = leaderGhosts.filter((effect) => now - effect.startedAt <= effect.duration);
    refs.canvas.dataset.leaderGhosts = String(leaderGhosts.length);
    if (hadLeaderGhosts && !leaderGhosts.length && !finished) {
      refs.canvas.dataset.leaderStability = "settled";
    }
    activityPoints = activityPoints.filter((activity) => now - activity.startedAt <= 920);
    depthShockwaves = depthShockwaves.filter((wave) => now - wave.startedAt <= wave.duration);
    if (completionChoreographyStartedAt !== null
      && now - completionChoreographyStartedAt >= COMPLETION_CHOREOGRAPHY_MS) {
      completionChoreographyStartedAt = null;
      refs.canvas.dataset.completionChoreography = "settled";
    }
    let retiredNodesRemoved = false;
    visibleNodes.forEach((node, id) => {
      if (node.retiringAt && now - node.retiringAt >= SETTLE_FADE_MS) {
        visibleNodes.delete(id);
        retiredNodesRemoved = true;
      }
    });
    if (retiredNodesRemoved) invalidateStaticScene();
    const drawStartedAt = performance.now();
    draw(now);
    updateAdaptiveEffectBudget(now, performance.now() - drawStartedAt);
    if (shouldKeepDrawing(now)) scheduleNextDraw(nextFrameDelay(now));
  }

  function requestDraw() {
    if (animationFrame === null && animationWakeTimer === null) {
      animationFrame = window.requestAnimationFrame(drawFrame);
    }
  }

  function updateProgress() {
    refs.scrubber.value = String(cursor);
    refs.progress.textContent = `${cursor} / ${events.length}`;
    const currentEvent = cursor > 0 ? events[Math.min(cursor, events.length) - 1] : null;
    const currentTimeUs = traceTimeUs(currentEvent);
    updateEngineTimer(currentTimeUs ?? engineTimeUs, engineTimerMode);
  }

  function advance() {
    if (cursor >= events.length) {
      stop();
      return;
    }
    apply(events[cursor]);
    cursor += 1;
    updateProgress();
    requestDraw();
  }

  function traceTimeUs(event) {
    const value = Number(event?.t_us);
    return Number.isFinite(value) ? value : null;
  }

  function schedule() {
    if (timer === null) return;
    if (refs.speed.value === "realtime") {
      const now = performance.now();
      const currentTraceTime = traceTimeUs(events[cursor]);
      if (currentTraceTime == null) {
        advance();
        timer = cursor < events.length ? window.setTimeout(schedule, 0) : null;
      } else {
        if (!realReplayClock) realReplayClock = { wallTime: now, traceTime: currentTraceTime };
        const targetTraceTime = realReplayClock.traceTime + (now - realReplayClock.wallTime) * 1000;
        let applied = 0;
        while (cursor < events.length && applied < 1000) {
          const nextTraceTime = traceTimeUs(events[cursor]);
          if (nextTraceTime != null && nextTraceTime > targetTraceTime && applied > 0) break;
          if (nextTraceTime != null && nextTraceTime > targetTraceTime && applied === 0) break;
          advance();
          applied += 1;
        }
        if (cursor < events.length) {
          const nextTraceTime = traceTimeUs(events[cursor]) ?? targetTraceTime;
          const wait = clamp((nextTraceTime - targetTraceTime) / 1000, 0, 16);
          timer = window.setTimeout(schedule, wait);
        }
      }
    } else {
      realReplayClock = null;
      const preset = REPLAY_SPEEDS[refs.speed.value] || REPLAY_SPEEDS.normal;
      let applied = 0;
      while (cursor < events.length && applied < preset.batchSize) {
        advance();
        applied += 1;
      }
      if (cursor < events.length) timer = window.setTimeout(schedule, preset.delayMs);
    }
    if (cursor >= events.length) stop();
  }

  function play() {
    if (!events.length) return;
    if (timer !== null) {
      stop();
      return;
    }
    if (cursor >= events.length) clearState();
    engineTimerMode = "replay";
    const replayEvent = cursor > 0 ? events[Math.min(cursor, events.length) - 1] : null;
    updateEngineTimer(traceTimeUs(replayEvent) ?? 0, "replay");
    refs.canvas.dataset.state = "searching";
    refs.canvas.dataset.replayScrubState = "playing";
    delete refs.canvas.dataset.seekHotNodes;
    setStreamState("recording", "Replay");
    refs.play.textContent = "Pause";
    realReplayClock = null;
    timer = window.setTimeout(schedule, 0);
    requestDraw();
  }

  function seek(target) {
    stop();
    engineTimerMode = "replay";
    if (liveUiFrame !== null) window.cancelAnimationFrame(liveUiFrame);
    liveUiFrame = null;
    pendingLiveAnnouncement = null;
    cancelDrawing();
    visibleNodes = new Map();
    activeId = null;
    finished = false;
    limitReached = false;
    delete refs.canvas.dataset.searchLimited;
    pulses = [];
    bursts = [];
    cutoffImplosions = [];
    wormholeFlashes = [];
    leaderGhosts = [];
    completedDepths = new Set();
    cutoffImplosionCount = 0;
    wormholeFlashCount = 0;
    leaderChangeCount = 0;
    activityPoints = [];
    passFinishedAt = new Map();
    completionTransitionStartedAt = null;
    completionChoreographyStartedAt = null;
    depthShockwaves = [];
    depthShockwaveCount = 0;
    bloomBuildCount = 0;
    bloomDirty = true;
    backgroundBuildCount = 0;
    backgroundDirty = true;
    invalidateSettledScenes();
    delete refs.canvas.dataset.completionTransition;
    delete refs.canvas.dataset.completionChoreography;
    delete refs.canvas.dataset.completionEmanation;
    delete refs.canvas.dataset.completionEmanationDurationMs;
    refs.canvas.dataset.cutoffImplosions = "0";
    refs.canvas.dataset.wormholeFlashes = "0";
    refs.canvas.dataset.leaderChanges = "0";
    refs.canvas.dataset.leaderGhosts = "0";
    refs.canvas.dataset.leaderStability = "settled";
    refs.canvas.dataset.depthEchoes = "0";
    refs.canvas.dataset.depthWaves = "0";
    refs.canvas.dataset.bloomBuilds = "0";
    refs.canvas.dataset.backgroundBuilds = "0";
    refs.canvas.dataset.frozenDepths = "0";
    cursor = 0;
    activeSearchDepth = 0;
    searchHorizon = 0;
    rootBest = null;
    authoritativePv = null;
    delete refs.canvas.dataset.pvDepth;
    delete refs.canvas.dataset.pvPlies;
    delete refs.canvas.dataset.pvMoves;
    delete refs.canvas.dataset.pvReveal;
    delete refs.canvas.dataset.survivorGlow;
    delete refs.canvas.dataset.principalHitTargets;
    delete refs.canvas.dataset.selectionStrategy;
    delete refs.canvas.dataset.curatedNodes;
    delete refs.canvas.dataset.curatedPromoted;
    updateBestMove();
    while (cursor < target && cursor < events.length) {
      apply(events[cursor], false, false);
      cursor += 1;
    }
    const seekNow = performance.now();
    const hotNodes = [...visibleNodes.values()].filter((node) => (
      seekNow - (node.activatedAt || 0) < 920
    )).length;
    refs.canvas.dataset.replayScrubState = "settled";
    refs.canvas.dataset.seekHotNodes = String(hotNodes);
    if (cursor) {
      const [tag, text] = describe(events[cursor - 1]);
      refs.eventTag.textContent = tag;
      refs.eventText.textContent = text;
    }
    refs.canvas.dataset.state = finished ? "complete" : cursor ? "paused" : "empty";
    updateProgress();
    draw(performance.now());
    if (finished) requestDraw();
  }

  function nearestNode(clientX, clientY) {
    const { width, height } = canvasSize();
    const mouse = canvasToWorld(canvasLocalPoint(clientX, clientY), width, height);
    const pvPoints = authoritativePvPoints(width, height);
    let principalNearest = null;
    let principalDistance = PRINCIPAL_HIT_RADIUS_PX;
    pvPoints.slice(1).forEach((pvPoint) => {
      const nextDistance = Math.hypot(mouse.x - pvPoint.x, mouse.y - pvPoint.y) * viewport.scale;
      if (nextDistance >= principalDistance) return;
      principalDistance = nextDistance;
      const node = pvPoint.node || {
        id: `pv-${pvPoint.pvIndex}`,
        move: pvPoint.move,
        searchDepth: pvPoint.ringIndex,
        depth: Math.max(0, Number(authoritativePv?.depth || 0) - pvPoint.ringIndex),
        ply: pvPoint.pvIndex,
      };
      principalNearest = {
        node,
        position: pvPoint,
        principal: true,
        pvIndex: pvPoint.pvIndex,
        pvLength: Math.max(0, pvPoints.length - 1),
        traced: pvPoint.traced,
      };
    });
    // Give survivor nodes priority within their larger hit targets.
    if (principalNearest) return principalNearest;

    let nearest = null;
    let distance = STANDARD_HIT_RADIUS_PX / viewport.scale;
    visibleNodes.forEach((node) => {
      const position = point(node, width, height);
      const nextDistance = Math.hypot(mouse.x - position.x, mouse.y - position.y);
      if (nextDistance < distance) {
        distance = nextDistance;
        nearest = { node, position };
      }
    });
    return nearest;
  }

  function beginLiveTrace(requestedDepth) {
    events = [];
    layoutNodes = new Map();
    rootRemainingDepth = requestedDepth;
    maxDepthRing = Math.max(1, requestedDepth);
    liveRingCounts = new Map();
    liveHashes = new Map();
    clearState();
    updateEngineTimer(0, "live");
    searchHorizon = 0;
    liveStreaming = true;
    refs.empty.hidden = true;
    refs.play.disabled = true;
    refs.speed.disabled = true;
    refs.scrubber.disabled = true;
    refs.canvas.dataset.state = "searching";
    setStreamState("live", `Live · starting depth 1/${requestedDepth}`);
    refs.eventTag.textContent = "LIVE NOW";
    refs.eventText.textContent = "Each iterative-deepening pass will appear here as Sgurr completes it.";
    requestDraw();
  }

  function shouldAnnounceLiveEvent(event) {
    if (["start", "finish", "pv", "limit"].includes(event.e)) return true;
    if (event.e === "node" || event.e === "end") return visibleNodes.has(event.id);
    if (event.e === "best" || event.e === "cutoff") {
      return Number(event.id) === 0 || visibleNodes.has(event.id) || visibleNodes.has(event.child);
    }
    return false;
  }

  function flushLiveUi() {
    if (liveUiFrame !== null) window.cancelAnimationFrame(liveUiFrame);
    liveUiFrame = null;
    refs.scrubber.max = String(events.length);
    updateProgress();
    if (pendingLiveAnnouncement) {
      const [tag, text] = describe(pendingLiveAnnouncement);
      refs.eventTag.textContent = tag;
      refs.eventText.textContent = text;
      pendingLiveAnnouncement = null;
    }
    requestDraw();
  }

  function queueLiveUi(event) {
    if (shouldAnnounceLiveEvent(event)) pendingLiveAnnouncement = event;
    if (liveUiFrame === null) liveUiFrame = window.requestAnimationFrame(flushLiveUi);
  }

  function pendingLiveEventCount() {
    return Math.max(0, pendingLiveEvents.length - pendingLiveEventCursor);
  }

  function resolveLiveEventDrain() {
    if (pendingLiveEventCount()) return;
    pendingLiveEvents = [];
    pendingLiveEventCursor = 0;
    refs.canvas.dataset.liveEventQueue = "0";
    liveEventDrainResolvers.splice(0).forEach((resolve) => resolve());
  }

  function scheduleLiveEventDrain() {
    if (liveEventDrainTask !== null || !pendingLiveEventCount()) return;
    const drain = () => {
      liveEventDrainTask = null;
      liveEventDrainTaskKind = null;
      const sliceStartedAt = performance.now();
      let applied = 0;
      while (
        pendingLiveEventCursor < pendingLiveEvents.length
        && (applied === 0 || performance.now() - sliceStartedAt < LIVE_EVENT_SLICE_MS)
      ) {
        applyLiveEvent(pendingLiveEvents[pendingLiveEventCursor]);
        pendingLiveEventCursor += 1;
        applied += 1;
      }
      if (PROFILE) recordPhase("live-events (off-frame)", performance.now() - sliceStartedAt);
      refs.canvas.dataset.liveEventsPerSlice = String(applied);
      refs.canvas.dataset.liveEventQueue = String(pendingLiveEventCount());
      if (pendingLiveEventCount()) scheduleLiveEventDrain();
      else resolveLiveEventDrain();
    };
    if (document.hidden) {
      liveEventDrainTaskKind = "timer";
      liveEventDrainTask = window.setTimeout(drain, 0);
    } else {
      liveEventDrainTaskKind = "frame";
      liveEventDrainTask = window.requestAnimationFrame(drain);
    }
  }

  function enqueueLiveEvent(event) {
    pendingLiveEvents.push(event);
    const queued = pendingLiveEventCount();
    liveEventHighWater = Math.max(liveEventHighWater, queued);
    refs.canvas.dataset.liveEventQueue = String(queued);
    refs.canvas.dataset.liveEventQueuePeak = String(liveEventHighWater);
    scheduleLiveEventDrain();
  }

  function flushPendingLiveEvents() {
    if (!pendingLiveEventCount()) return Promise.resolve();
    scheduleLiveEventDrain();
    return new Promise((resolve) => liveEventDrainResolvers.push(resolve));
  }

  function applyLiveEvent(event) {
    const eventIndex = events.length;
    events.push(event);
    if (event.e === "node") addLiveLayoutNode(event, eventIndex);
    // Apply engine data immediately but update the UI once per frame.
    apply(event, false, true);
    cursor = events.length;
    queueEngineTimer(event.t_us, "live");
    queueLiveUi(event);
  }

  function captureMessage(message, requestedDepth, runMode) {
    if (message.type === "started") {
      searchHorizon = 0;
      setStreamState("preparing", `Starting · 0/${message.depth}`);
      refs.eventTag.textContent = `SEARCH TO ${message.depth}`;
      refs.eventText.textContent = "The network starts at depth 1 and updates after each completed iteration.";
      return;
    }
    if (message.type === "progress") {
      const nodes = Math.max(0, Number(message.nodes) || 0);
      const hasTime = message.time_ms !== null
        && message.time_ms !== undefined
        && Number.isFinite(Number(message.time_ms));
      const statsEvent = {
        e: "stats",
        nodes,
        depth: Number(message.depth) || 0,
        iterationDepth: Number(message.depth) || 0,
        ...(hasTime ? { t_us: Number(message.time_ms) * 1000 } : {}),
      };
      if (runMode === "live") {
        if (liveStreaming) enqueueLiveEvent(statsEvent);
        else updateEngineNodesSearched(nodes, "live");
        return;
      }
      events.push(statsEvent);
      updateEngineNodesSearched(nodes, "recording");
      searchHorizon = Math.max(searchHorizon, Number(message.depth) || 0);
      const formattedNodes = nodes.toLocaleString("en-GB");
      setStreamState("preparing", `Preparing · ${message.depth}/${requestedDepth}`);
      refs.empty.querySelector("strong").textContent = `Depth ${message.depth} complete`;
      refs.empty.querySelector("span").textContent = `${formattedNodes} nodes searched so far · preparing depth ${Math.min(requestedDepth, Number(message.depth) + 1)} of ${requestedDepth}`;
      refs.eventTag.textContent = `DEPTH ${message.depth} COMPLETE`;
      refs.eventText.textContent = `The engine is using that result to order the next, deeper iteration.`;
      requestDraw();
      return;
    }
    if (message.type === "trace") {
      if (message.event?.e === "start" && runMode === "live" && !liveStreaming) {
        beginLiveTrace(requestedDepth);
      }
      const event = normalizeTraceEvent(message.event);
      if (runMode !== "live") queueEngineTimer(event.t_us, "recording");
      if (event.e === "start") {
        if (runMode === "live") {
          setStreamState("live", `Live · depth ${event.iterationDepth}/${requestedDepth}`);
          refs.eventTag.textContent = `DEPTH ${event.iterationDepth} LIVE`;
          refs.eventText.textContent = `Sgurr is searching depth ${event.iterationDepth}; earlier positions remain in the network.`;
        }
        else {
          setStreamState("recording", `Recording · depth ${event.iterationDepth}/${requestedDepth}`);
          refs.empty.querySelector("strong").textContent = `Recording depth ${event.iterationDepth}`;
          refs.empty.querySelector("span").textContent = "Each iteration is being timestamped as one continuous search.";
          refs.eventTag.textContent = `DEPTH ${event.iterationDepth} RUNNING`;
        }
      }
      if (keepEvent(event)) {
        if (runMode === "live") enqueueLiveEvent(event);
        else events.push(event);
      }
      return;
    }
    if (message.type === "complete") {
      const achievedDepth = Number(message.depth) || requestedDepth;
      const limited = Boolean(message.limited);
      if (limited) {
        const terminal = {
          e: "search-limit",
          depth: achievedDepth,
          targetDepth: requestedDepth,
          nodes: Number(message.nodes) || 0,
          best: message.bestmove,
          reason: message.stoppedEarly ? "time" : "nodes",
        };
        if (runMode === "live") applyLiveEvent(terminal);
        else events.push(terminal);
      }
      if (runMode === "live") flushLiveUi();
      flushQueuedEngineTimer(runMode === "live" ? "complete" : "recording");
      updateEngineNodesSearched(engineNodesSearched, runMode === "live" ? "complete" : "recording");
      liveStreaming = false;
      if (runMode === "live") {
        refs.play.disabled = false;
        refs.speed.disabled = false;
        refs.scrubber.disabled = false;
        setStreamState(
          limited ? "ready" : "complete",
          limited
            ? `Capped · depth ${achievedDepth}/${requestedDepth}`
            : "Complete · replay ready",
        );
        refs.play.textContent = "Replay";
        requestDraw();
      }
      return;
    }
    if (message.type === "error") throw new Error(message.detail || "Trace failed");
  }

  // Replay depth comes from recorded events rather than applied live state.
  function depthReached(runMode) {
    if (runMode === "live") return searchHorizon;
    return events.reduce(
      (deepest, event) => (event.e === "finish"
        ? Math.max(deepest, Number(event.iterationDepth || event.depth || 0))
        : deepest),
      0,
    );
  }

  // Treat a timed stop after one iteration as a completed capped search.
  // A stop before any completed iteration remains an error.
  function completionFromStop(message, requestedDepth, runMode) {
    if (message?.type !== "error") return message;
    const depth = depthReached(runMode);
    if (depth < 1) return message;
    return {
      type: "complete",
      events: "bounded",
      target_depth: requestedDepth,
      depth,
      nodes: engineNodesSearched,
      limited: true,
      stoppedEarly: true,
    };
  }

  async function readStream(response, requestedDepth, runMode) {
    const reader = response.body?.getReader();
    if (!reader) throw new Error("This browser cannot read the trace stream");
    const decoder = new TextDecoder();
    let buffer = "";
    let completion = null;
    let processingSliceStartedAt = performance.now();

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const parsed = JSON.parse(line);
        // Drain queued depths before deciding how the search ended.
        if (runMode === "live" && (parsed.type === "complete" || parsed.type === "error")) {
          await flushPendingLiveEvents();
        }
        const message = completionFromStop(parsed, requestedDepth, runMode);
        if (message.type === "complete") completion = message;
        captureMessage(message, requestedDepth, runMode);
        if (runMode === "live" && !document.hidden && performance.now() - processingSliceStartedAt >= LIVE_EVENT_SLICE_MS) {
          await new Promise((resolve) => window.requestAnimationFrame(resolve));
          processingSliceStartedAt = performance.now();
        }
      }
      if (done) break;
    }
    if (buffer.trim()) {
      const parsed = JSON.parse(buffer);
      if (runMode === "live" && (parsed.type === "complete" || parsed.type === "error")) {
        await flushPendingLiveEvents();
      }
      const message = completionFromStop(parsed, requestedDepth, runMode);
      if (message.type === "complete") completion = message;
      captureMessage(message, requestedDepth, runMode);
    }
    if (runMode === "live") await flushPendingLiveEvents();
    return completion;
  }

  async function load(fen, depth = 6, runMode = "live") {
    if (controller) controller.abort();
    reset(`Recording Sgurr's depth-${depth} search…`);
    rootRemainingDepth = depth;
    updateEngineTimer(0, runMode === "live" ? "live" : "recording");
    maxDepthRing = Math.max(1, depth);
    searchHorizon = 0;
    controller = new AbortController();
    refs.empty.hidden = false;
    refs.empty.querySelector("strong").textContent = `Starting depth 1 of ${depth}`;
    refs.empty.querySelector("span").textContent = runMode === "live"
      ? "The network will update through each iterative-deepening pass."
      : "Every depth will be recorded as one continuous, engine-speed search.";
    refs.eventTag.textContent = "STARTING";
    requestDraw();
    setStreamState("preparing", `Starting · 0/${depth}`);

    try {
      const response = await fetch(apiUrl("/api/search-network"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fen, depth }),
        signal: controller.signal,
      });
      if (!response.ok) {
        let detail = `Trace request failed (${response.status})`;
        try { detail = (await response.json()).detail || detail; } catch { /* keep status */ }
        throw new Error(detail);
      }
      const completion = await readStream(response, depth, runMode);
      const achievedDepth = Number(completion?.depth) || depth;
      const limited = Boolean(completion?.limited);
      const limitTag = completion?.stoppedEarly ? "SEARCH TIME LIMIT" : "NODE LIMIT REACHED";
      const limitPhrase = completion?.stoppedEarly ? "the demo's time limit" : "the demo's node limit";
      const finishEvent = [...events].reverse().find((event) => event.e === "finish");
      const elapsedMs = Number(finishEvent?.t_us) / 1000;
      const timing = Number.isFinite(elapsedMs) ? ` The complete search took ${elapsedMs < 100 ? elapsedMs.toFixed(1) : Math.round(elapsedMs)} ms.` : "";
      if (runMode === "replay") {
        prepareLayout();
        refs.scrubber.max = String(events.length);
        refs.empty.hidden = true;
        clearState();
        setStreamState(
          limited ? "ready" : "complete",
          limited ? `Capped · depth ${achievedDepth}/${depth}` : "Recorded · replay ready",
        );
        refs.eventTag.textContent = limited ? limitTag : "TRACE READY";
        refs.eventText.textContent = limited
          ? `${layoutNodes.size} real positions were recorded before ${limitPhrase}. Depth ${achievedDepth} completed; the final iteration may be partial.${timing}`
          : `${layoutNodes.size} real positions across depths 1–${depth} are ready. Depth 0 begins at the root and each orbit moves outward.${timing}`;
        if (!reducedMotion.matches) play();
      } else {
        refs.eventTag.textContent = limited ? limitTag : "SEARCH COMPLETE";
        refs.eventText.textContent = limited
          ? `${layoutNodes.size} positions appeared before ${limitPhrase}. Depth ${achievedDepth} completed; the final iteration may be partial.${timing}`
          : `${layoutNodes.size} positions appeared live.${timing} The same trace is now available to replay slowly.`;
      }
      return true;
    } catch (error) {
      if (error.name === "AbortError") return false;
      refs.empty.hidden = false;
      refs.empty.querySelector("strong").textContent = "Trace unavailable";
      refs.empty.querySelector("span").textContent = error.message || String(error);
      refs.eventTag.textContent = "TRACE UNAVAILABLE";
      refs.eventText.textContent = "The guided walkthrough and completed-depth live mode still work without the diagnostic trace binary.";
      setStreamState("ready", "Unavailable");
      refs.play.disabled = false;
      refs.speed.disabled = false;
      refs.scrubber.disabled = false;
      return false;
    } finally {
      controller = null;
    }
  }

  function startPinch() {
    const active = [...pointers.values()];
    if (active.length < 2) return;
    const first = active[0];
    const second = active[1];
    const midpoint = { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 };
    const { width, height } = canvasSize();
    pinchState = {
      distance: Math.max(1, Math.hypot(second.x - first.x, second.y - first.y)),
      scale: viewport.scale,
      anchor: canvasToWorld(midpoint, width, height),
    };
    dragState = null;
  }

  function showTooltip(event) {
    const hit = nearestNode(event.clientX, event.clientY);
    if (!hit) {
      refs.tooltip.hidden = true;
      if (hoveredTarget) {
        hoveredTarget = null;
        delete refs.canvas.dataset.hovered;
        requestDraw();
      }
      return;
    }
    const { node } = hit;
    const nextHoveredTarget = hit.principal
      ? { principal: true, pvIndex: hit.pvIndex }
      : { principal: false, nodeId: node.id };
    const hoverChanged = !hoveredTarget
      || hoveredTarget.principal !== nextHoveredTarget.principal
      || hoveredTarget.pvIndex !== nextHoveredTarget.pvIndex
      || hoveredTarget.nodeId !== nextHoveredTarget.nodeId;
    hoveredTarget = nextHoveredTarget;
    refs.canvas.dataset.hovered = hit.principal ? "principal" : "node";
    refs.canvas.dataset.principalHitRadius = String(PRINCIPAL_HIT_RADIUS_PX);
    if (hoverChanged) requestDraw();
    refs.tooltip.replaceChildren();
    const title = document.createElement("strong");
    title.textContent = hit.principal ? `${node.move} · principal variation` : node.move || "Root position";
    const detail = document.createElement("span");
    if (hit.principal) {
      const source = hit.traced ? "traced search node" : "completed-depth PV continuation";
      detail.textContent = `Principal variation · move ${hit.pvIndex} of ${hit.pvLength} · depth ring ${hit.position.ringIndex} · ${source}`;
      refs.tooltip.dataset.kind = "principal";
    } else {
      const returnedScore = scoreForParent(node);
      const scoreText = returnedScore === null
        ? ""
        : Math.abs(returnedScore) >= 29000
          ? " · decisive score"
          : ` · move eval ${returnedScore > 0 ? "+" : returnedScore < 0 ? "−" : ""}${Math.abs(returnedScore / 100).toFixed(2)}`;
      detail.textContent = `Search depth ${node.searchDepth} · ${node.depth} remaining · ply ${node.ply}${scoreText}${node.reason ? ` · ${node.reason}` : ""}`;
      refs.tooltip.dataset.kind = "node";
    }
    refs.tooltip.append(title, detail);
    const wrap = refs.canvasWrap.getBoundingClientRect();
    refs.tooltip.style.left = `${Math.min(wrap.width - 190, Math.max(8, event.clientX - wrap.left + 12))}px`;
    refs.tooltip.style.top = `${Math.min(wrap.height - 54, Math.max(8, event.clientY - wrap.top + 12))}px`;
    refs.tooltip.hidden = false;
  }

  function endPointer(event) {
    pointers.delete(event.pointerId);
    if (refs.canvas.hasPointerCapture?.(event.pointerId)) refs.canvas.releasePointerCapture(event.pointerId);
    if (pointers.size >= 2) {
      startPinch();
    } else if (pointers.size === 1) {
      const [pointerId, position] = pointers.entries().next().value;
      dragState = { pointerId, start: position, x: viewport.x, y: viewport.y };
      pinchState = null;
    } else {
      dragState = null;
      pinchState = null;
      refs.canvas.dataset.dragging = "false";
      // Restore native detail immediately after pointer release.
      settleInteraction(0);
    }
  }

  // Stamp fixed renderer grading values once.
  refs.canvas.dataset.networkLuminosity = "1.08";
  refs.canvas.dataset.completionDimming = "disabled";
  refs.canvas.dataset.centerExposure = "filmic-radial-compression";
  refs.canvas.dataset.centerExposureFloor = "0.48";

  // Rebuild cached layers when the detail tier changes.
  const detailSelect = document.querySelector("#labDetailSelect");
  if (detailSelect) {
    QUALITY_ORDER.forEach((key) => {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = QUALITY_TIERS[key].label;
      detailSelect.appendChild(option);
    });
    detailSelect.value = qualityTier;
    detailSelect.addEventListener("change", () => {
      qualityTier = QUALITY_ORDER.includes(detailSelect.value) ? detailSelect.value : "high";
      writeStored("sgurrLabDetail", qualityTier);
      refs.canvas.dataset.detailTier = qualityTier;
        invalidateSettledScenes();
      invalidateStaticScene();
      invalidateBloomScene();
      invalidateBackgroundScene();
      invalidateDepthAtmosphereScene();
      invalidateDetailScene();
      detailSceneReady = false;
      requestDraw();
    });
    refs.canvas.dataset.detailTier = qualityTier;
  }

  if (PROFILE) startProfiling();

  refs.play.addEventListener("click", play);
  refs.restart.addEventListener("click", () => {
    clearState();
    if (events.length) play();
  });
  refs.scrubber.addEventListener("input", () => seek(Number(refs.scrubber.value)));
  refs.speed.addEventListener("change", () => {
    realReplayClock = null;
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = window.setTimeout(schedule, 0);
    }
  });
  refs.zoomOut.addEventListener("click", () => {
    if (zoomAt(viewport.scale / 1.28)) pulseInteraction();
  });
  refs.zoomIn.addEventListener("click", () => {
    if (zoomAt(viewport.scale * 1.28)) pulseInteraction();
  });
  refs.fitView.addEventListener("click", resetViewport);
  refs.canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const intensity = event.deltaMode === 1 ? 0.045 : 0.0015;
    const changed = zoomAt(
      viewport.scale * Math.exp(-event.deltaY * intensity),
      canvasLocalPoint(event.clientX, event.clientY),
    );
    if (changed) pulseInteraction();
  }, { passive: false });
  refs.canvas.addEventListener("dblclick", resetViewport);
  refs.canvas.addEventListener("keydown", (event) => {
    let changed = false;
    if (["+", "="].includes(event.key)) changed = zoomAt(viewport.scale * 1.28);
    else if (["-", "_"].includes(event.key)) changed = zoomAt(viewport.scale / 1.28);
    else if (["0", "Home"].includes(event.key)) changed = resetViewport();
    else if (event.key === "ArrowLeft") { viewport.x += 30; changed = true; }
    else if (event.key === "ArrowRight") { viewport.x -= 30; changed = true; }
    else if (event.key === "ArrowUp") { viewport.y += 30; changed = true; }
    else if (event.key === "ArrowDown") { viewport.y -= 30; changed = true; }
    else return;
    event.preventDefault();
    if (!changed) return;
    const { width, height } = canvasSize();
    const bounded = boundedViewportOffset(viewport.x, viewport.y, viewport.scale, width, height);
    viewport.x = bounded.x;
    viewport.y = bounded.y;
    recordViewportPosition();
    pulseInteraction();
    invalidateDetailScene();
    updateZoomLevel();
    requestDraw();
  });
  refs.canvas.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    refs.canvas.focus({ preventScroll: true });
    refs.canvas.setPointerCapture(event.pointerId);
    const position = canvasLocalPoint(event.clientX, event.clientY);
    pointers.set(event.pointerId, position);
    refs.tooltip.hidden = true;
    hoveredTarget = null;
    delete refs.canvas.dataset.hovered;
    refs.canvas.dataset.dragging = "true";
    if (pointers.size >= 2) startPinch();
    else dragState = { pointerId: event.pointerId, start: position, x: viewport.x, y: viewport.y };
  });
  refs.canvas.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) {
      showTooltip(event);
      return;
    }
    const position = canvasLocalPoint(event.clientX, event.clientY);
    pointers.set(event.pointerId, position);
    if (pointers.size >= 2 && pinchState) {
      const active = [...pointers.values()];
      const first = active[0];
      const second = active[1];
      const midpoint = { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 };
      const distance = Math.max(1, Math.hypot(second.x - first.x, second.y - first.y));
      if (setViewportFromAnchor(pinchState.scale * (distance / pinchState.distance), midpoint, pinchState.anchor)) {
        setInteractionMode(true);
      }
    } else if (dragState?.pointerId === event.pointerId) {
      const { width, height } = canvasSize();
      const proposedX = dragState.x + position.x - dragState.start.x;
      const proposedY = dragState.y + position.y - dragState.start.y;
      const { x, y } = boundedViewportOffset(proposedX, proposedY, viewport.scale, width, height);
      if (Math.abs(x - viewport.x) > 0.01 || Math.abs(y - viewport.y) > 0.01) {
        setInteractionMode(true);
        viewport.x = x;
        viewport.y = y;
        recordViewportPosition();
        invalidateDetailScene();
        requestDraw();
      }
    }
  });
  refs.canvas.addEventListener("pointerup", endPointer);
  refs.canvas.addEventListener("pointercancel", endPointer);
  refs.canvas.addEventListener("pointerleave", () => {
    if (!pointers.size) {
      refs.tooltip.hidden = true;
      hoveredTarget = null;
      delete refs.canvas.dataset.hovered;
      requestDraw();
    }
  });
  new ResizeObserver(() => {
    canvasBoxDirty = true;
    const { width, height } = canvasSize();
    const bounded = boundedViewportOffset(viewport.x, viewport.y, viewport.scale, width, height);
    const changed = Math.abs(bounded.x - viewport.x) > 0.01 || Math.abs(bounded.y - viewport.y) > 0.01;
    viewport.x = bounded.x;
    viewport.y = bounded.y;
    recordViewportPosition();
    if (changed) invalidateDetailScene();
    if (navigationReleaseJob) {
      setInteractionMode(true);
      settleInteraction(0);
    }
    requestDraw();
  }).observe(refs.canvasWrap);
  window.addEventListener("resize", () => { canvasBoxDirty = true; });
  document.addEventListener("visibilitychange", () => {
    canvasBoxDirty = true;
    if (!document.hidden) requestDraw();
  });
  document.addEventListener("sgurrthemechange", () => {
    paletteCache = null;
    glowSpriteCache.clear();
    invalidateBackgroundScene();
    invalidateDepthAtmosphereScene();
    invalidateBloomScene();
    invalidateSettledScenes();
    if (navigationReleaseJob) {
      setInteractionMode(true);
      settleInteraction(0);
    }
    requestDraw();
  });

  reset();
  return { load, reset, stop };
}
