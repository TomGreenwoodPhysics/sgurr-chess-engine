import { CORE_DIALOGUE_COOLDOWN_PLIES, CORE_DIALOGUE_LINES, CORE_LINE_FADE_MS, CORE_THINKING_LINES, CORE_THINKING_LINE_MS } from "./config.js";
import { maybeOpeningReaction } from "./openings.js";
import { app, refs } from "./state.js";
import { renderPlayerCards, renderStatus } from "./ui.js";
import { formatNodesShort } from "./utils.js";

function coreThinkingLine() {
  return CORE_THINKING_LINES[app.coreThinkingIndex % CORE_THINKING_LINES.length];
}

function engineEvalPerspective(cp) {
  if (app.humanSide === "white") {
    return -cp;
  }
  if (app.humanSide === "black") {
    return cp;
  }
  return cp;
}

function latestEvalDeltaCp() {
  if (app.evalHistory.length < 2) {
    return 0;
  }
  const current = app.evalHistory[app.evalHistory.length - 1];
  const previous = app.evalHistory[app.evalHistory.length - 2];
  return (Number(current?.cp) || 0) - (Number(previous?.cp) || 0);
}

const CORE_MOOD_CLASSES = [
  "mood-balanced",
  "mood-dominant",
  "mood-predatory",
  "mood-strained",
  "core-checking",
  "core-pressuring",
  "core-fed",
  "core-wounded",
  "core-endgame",
  "core-surging",
  "core-staggered",
];

function evalForColour(colour, cp) {
  return colour === "white" ? cp : -cp;
}

function applyCoreMood(core, colour) {
  if (!core) {
    return;
  }
  core.classList.remove(...CORE_MOOD_CLASSES);
  if (app.mode !== "game" || !colour || app.gameOver) {
    return;
  }

  const cp = Number(app.latestEval?.value) || 0;
  const perspective = evalForColour(colour, cp);
  const mate = app.latestEval?.kind === "mate" || Math.abs(cp) >= 90000;
  if (mate) {
    core.classList.add(perspective > 0 ? "mood-predatory" : "mood-strained");
  } else if (perspective >= 550) {
    core.classList.add("mood-predatory");
  } else if (perspective >= 180) {
    core.classList.add("mood-dominant");
  } else if (perspective <= -180) {
    core.classList.add("mood-strained");
  } else {
    core.classList.add("mood-balanced");
  }

  if (app.inCheck) {
    core.classList.add(app.turn === colour ? "core-checking" : "core-pressuring");
  }

  const lastMover = app.turn === "white" ? "black" : "white";
  if (app.lastMoveInfo?.san?.includes("x")) {
    core.classList.add(lastMover === colour ? "core-fed" : "core-wounded");
  }

  const totalMaterial = (Number(app.material?.white) || 0) + (Number(app.material?.black) || 0);
  if (totalMaterial > 0 && totalMaterial <= 34) {
    core.classList.add("core-endgame");
  }

  const swing = evalForColour(colour, latestEvalDeltaCp());
  if (swing >= 220) {
    core.classList.add("core-surging");
  } else if (swing <= -220) {
    core.classList.add("core-staggered");
  }
}

function seededDialogueIndex(key, moveInfo, lineCount) {
  const text = `${key}:${moveInfo?.uci || ""}:${moveInfo?.san || ""}:${app.moves.length}`;
  let seed = 0;
  for (let index = 0; index < text.length; index += 1) {
    seed = (seed + text.charCodeAt(index) * (index + 3)) % 9973;
  }
  if (key === app.coreDialogueLastKey) {
    seed += 1;
  }
  return seed % lineCount;
}

function pickCoreDialogueLine(key, moveInfo) {
  const lines = CORE_DIALOGUE_LINES[key] || [];
  if (!lines.length) {
    return null;
  }
  return lines[seededDialogueIndex(key, moveInfo, lines.length)];
}

function maybeCoreDialogue(moveInfo, { byHuman = false } = {}) {
  const move = moveInfo?.san || moveInfo?.uci || "";
  const ply = app.moves.length;
  const winner =
    app.winner ||
    (app.result === "1-0" ? "white" : app.result === "0-1" ? "black" : null);
  const evalInfo = app.latestEval;
  const deltaForEngine = engineEvalPerspective(latestEvalDeltaCp());
  let key = null;
  let forced = false;

  if (app.gameOver) {
    forced = true;
    if (app.result === "1/2-1/2") {
      key = "draw";
    } else if (app.humanSide !== null && winner === app.humanSide) {
      key = "humanWin";
    } else {
      key = "sgurrWin";
    }
  } else if (move.includes("#")) {
    key = byHuman ? "humanWin" : "sgurrWin";
    forced = true;
  } else if (evalInfo?.kind === "mate") {
    key = "mateThreat";
    forced = true;
  } else if (move.includes("+")) {
    key = byHuman ? "humanCheck" : "engineCheck";
    forced = true;
  } else if (Math.abs(deltaForEngine) >= 260) {
    key = deltaForEngine > 0 ? "engineSwing" : "humanSwing";
    forced = Math.abs(deltaForEngine) >= 450;
  } else if (move.includes("x")) {
    key = byHuman ? "humanCapture" : "engineCapture";
  } else if (!byHuman) {
    key = "engineMove";
  }

  if (!key) {
    return null;
  }

  const cooledDown = ply - app.coreDialogueLastPly >= CORE_DIALOGUE_COOLDOWN_PLIES;
  if (!forced && !cooledDown) {
    return null;
  }
  if (!forced && key === "engineMove" && ply % 3 !== 0) {
    return null;
  }

  const line = pickCoreDialogueLine(key, moveInfo);
  if (!line) {
    return null;
  }
  app.coreDialogueLastPly = ply;
  app.coreDialogueLastKey = key;
  return line;
}

function coreMoveLine(moveInfo, options = {}) {
  const move = moveInfo?.san || moveInfo?.uci || "move";
  const actor = options.byHuman ? "You" : "Sgurr";
  const openingReaction = maybeOpeningReaction();
  if (openingReaction) {
    app.coreLineMode = "opening";
    return openingReaction;
  }
  const dialogue = maybeCoreDialogue(moveInfo, options);
  if (dialogue) {
    app.coreLineMode = "dialogue";
    return dialogue;
  }

  app.coreLineMode = "system";
  if (app.gameOver) {
    return move.includes("#") ? `Checkmate: ${move}` : `Game complete: ${move}`;
  }
  if (move.includes("#")) {
    return `Checkmate: ${move}`;
  }
  if (move.includes("+")) {
    return `Check: ${move}`;
  }
  if (move.includes("x")) {
    return `Capture: ${move}`;
  }
  return `${actor} played ${move}`;
}

function coreIdleLine() {
  if (!app.backendOk) {
    return "Core bridge offline";
  }
  if (!app.engineExists) {
    return "Engine binary missing";
  }
  if (app.gameOver) {
    return app.coreMessage || (app.result ? `Game complete: ${app.result}` : "Game complete");
  }
  return app.coreMessage || "Engine ready";
}

function coreLineText() {
  return app.thinking ? coreThinkingLine() : coreIdleLine();
}

function startCoreThinkingLoop() {
  window.clearInterval(app.coreThinkingTimer);
  window.clearTimeout(app.coreLineFadeTimer);
  app.coreLineFading = false;
  app.coreLineMode = "system";
  app.coreThinkingIndex = app.moves.length % CORE_THINKING_LINES.length;
  app.coreMessage = coreThinkingLine();
  app.coreThinkingTimer = window.setInterval(() => {
    if (!app.thinking) {
      stopCoreThinkingLoop();
      return;
    }
    window.clearTimeout(app.coreLineFadeTimer);
    app.coreLineFading = true;
    renderStatus();
    app.coreLineFadeTimer = window.setTimeout(() => {
      if (!app.thinking) {
        app.coreLineFading = false;
        renderStatus();
        return;
      }
      app.coreThinkingIndex = (app.coreThinkingIndex + 1) % CORE_THINKING_LINES.length;
      app.coreMessage = coreThinkingLine();
      app.coreLineFading = false;
      renderStatus();
    }, CORE_LINE_FADE_MS);
  }, CORE_THINKING_LINE_MS);
}

function stopCoreThinkingLoop() {
  window.clearInterval(app.coreThinkingTimer);
  window.clearTimeout(app.coreLineFadeTimer);
  app.coreThinkingTimer = null;
  app.coreLineFadeTimer = null;
  app.coreLineFading = false;
}

function clearCoreCooling() {
  window.clearTimeout(app.coreCoolingTimer);
  app.coreCooling = false;
  app.coreCoolingTimer = null;
}

function beginCoreCooling() {
  window.clearTimeout(app.coreCoolingTimer);
  app.coreCooling = true;
  app.coreCoolingTimer = window.setTimeout(() => {
    app.coreCooling = false;
    app.coreCoolingTimer = null;
    renderStatus();
    renderPlayerCards();
  }, 420);
}

function startThinkingTicker() {
  stopThinkingTicker();
  if (app.mode !== "game" || !refs.evalMeta) {
    return;
  }
  const stats = app.lastSearchStats;
  const started = performance.now();
  refs.evalMeta.classList.add("thinking-live");
  app.thinkTicker = window.setInterval(() => {
    const elapsedMs = performance.now() - started;
    const nps = stats?.nps || 400000;
    const nodes = Math.max(1, (nps * elapsedMs) / 1000);
    let depth;
    if (stats?.depth && stats?.timeMs) {
      depth = stats.depth
        + Math.floor(Math.log(Math.max(elapsedMs, 40) / stats.timeMs) / Math.log(2.2));
    } else {
      depth = Math.floor(Math.log2(1 + (elapsedMs / 1000) * 60));
    }
    depth = Math.max(1, depth);
    refs.evalMeta.textContent =
      `thinking: depth ~${depth} / ~${formatNodesShort(nodes)} nodes / ${(elapsedMs / 1000).toFixed(1)}s`;
  }, 120);
}

function stopThinkingTicker() {
  if (app.thinkTicker) {
    window.clearInterval(app.thinkTicker);
    app.thinkTicker = null;
  }
  refs.evalMeta?.classList.remove("thinking-live");
}

function setThinkingState(thinking, { cool = true } = {}) {
  const wasThinking = app.thinking;
  app.thinking = thinking;

  if (thinking) {
    clearCoreCooling();
    startCoreThinkingLoop();
    startThinkingTicker();
    return;
  }

  stopThinkingTicker();
  stopCoreThinkingLoop();
  if (wasThinking && cool) {
    beginCoreCooling();
  } else {
    clearCoreCooling();
  }
}

export {
  coreThinkingLine,
  engineEvalPerspective,
  latestEvalDeltaCp,
  CORE_MOOD_CLASSES,
  evalForColour,
  applyCoreMood,
  seededDialogueIndex,
  pickCoreDialogueLine,
  maybeCoreDialogue,
  coreMoveLine,
  coreIdleLine,
  coreLineText,
  startCoreThinkingLoop,
  stopCoreThinkingLoop,
  clearCoreCooling,
  beginCoreCooling,
  startThinkingTicker,
  stopThinkingTicker,
  setThinkingState,
};
