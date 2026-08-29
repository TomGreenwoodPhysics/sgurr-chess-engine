import { apiUrl } from "./config.js";
import { readNdjson } from "./ndjson.js";
import { app } from "./state.js";
import { render } from "./ui.js";
import { fenTurn } from "./utils.js";

const ANALYSIS_MOVETIME_MS = 5_000;

async function postJson(path, body, signal) {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  return data;
}

function setAnalysisPosition(fen, ply = 0) {
  const iteration = selectedAnalysisIteration();
  const positions = iteration?.pv_fens || [app.analysis.sourceFen];
  const bounded = Math.max(0, Math.min(Number(ply) || 0, positions.length - 1));
  app.analysis.selectedPly = bounded;
  app.fen = positions[bounded] || fen || app.analysis.sourceFen;
  app.turn = fenTurn(app.fen);
  const move = bounded > 0 ? iteration?.pv?.[bounded - 1] : null;
  app.lastMove = move && move.length >= 4 ? move.slice(0, 4) : null;
  app.selected = null;
}

function selectedAnalysisIteration() {
  const selected = app.analysis.iterations.find(
    (iteration) => iteration.depth === app.analysis.selectedDepth,
  );
  return selected || app.analysis.iterations.at(-1) || null;
}

function resetAnalysisState(fen, orientation) {
  app.analysis.sourceFen = fen;
  app.analysis.orientation = orientation === "black" ? "black" : "white";
  app.analysis.iterations = [];
  app.analysis.selectedDepth = null;
  app.analysis.selectedPly = 0;
  app.analysis.running = true;
  app.analysis.complete = false;
  app.analysis.stopped = false;
  app.analysis.error = "";
  app.analysis.status = "Validating position";
  app.analysis.engineLabel = app.engineLabel || 'Sgurr v8.2 "Thearlaich"';
  app.analysis.movetimeMs = ANALYSIS_MOVETIME_MS;
  app.analysis.bestmove = null;
  app.analysis.bestmoveSan = null;
  app.latestEval = null;
  app.evalHistory = [];
  app.lastMove = null;
  app.lastMoveInfo = null;
  app.inCheck = false;
  app.gameOver = false;
  app.result = null;
  app.reason = null;
  app.winner = null;
  app.mode = "analysis";
  app.focusMode = false;
  app.manualFlip = false;
  app.busy = true;
  setAnalysisPosition(fen, 0);
}

function applyValidatedPosition(data) {
  app.analysis.sourceFen = data.fen;
  app.fen = data.fen;
  app.turn = data.turn;
  app.material = data.material;
  app.canMate = data.can_mate || { white: true, black: true };
  app.inCheck = Boolean(data.in_check);
  app.gameOver = Boolean(data.game_over);
  app.result = data.result || null;
  app.reason = data.reason || null;
  app.winner = data.winner || null;
}

function recordIteration(event) {
  const index = app.analysis.iterations.findIndex((item) => item.depth === event.depth);
  if (index >= 0) {
    app.analysis.iterations[index] = event;
  } else {
    app.analysis.iterations.push(event);
  }
  app.analysis.selectedDepth = event.depth;
  app.analysis.selectedPly = 0;
  app.latestEval = event;
  setAnalysisPosition(app.analysis.sourceFen, 0);
  app.analysis.status = `Depth ${event.depth} complete; searching deeper`;
}

function handleAnalysisEvent(event) {
  if (event.type === "started") {
    app.analysis.engineLabel = event.label || app.analysis.engineLabel;
    app.analysis.movetimeMs = event.movetime_ms || ANALYSIS_MOVETIME_MS;
    app.analysis.status = "Sgurr is searching";
  } else if (event.type === "iteration") {
    recordIteration(event);
  } else if (event.type === "complete") {
    app.analysis.running = false;
    app.analysis.complete = true;
    app.analysis.bestmove = event.bestmove && event.bestmove !== "0000" ? event.bestmove : null;
    app.analysis.bestmoveSan = event.bestmove_san || event.final?.pv_san?.[0] || null;
    if (event.final) {
      recordIteration(event.final);
    }
    app.analysis.status = app.analysis.bestmoveSan
      ? `Analysis complete; Sgurr prefers ${app.analysis.bestmoveSan}`
      : "Analysis complete";
  } else if (event.type === "error") {
    throw new Error(event.detail || "Sgurr's analysis stopped unexpectedly");
  }
  render();
}

async function startPositionAnalysis(fen, { orientation = "white", validated = null } = {}) {
  stopPositionAnalysis({ updateStatus: false });
  const sourceFen = String(fen || "").trim();
  const runId = app.analysis.runId + 1;
  app.analysis.runId = runId;
  const controller = new AbortController();
  app.analysis.controller = controller;
  resetAnalysisState(sourceFen, orientation);
  render();

  try {
    const position = validated || await postJson("/api/load-fen", { fen: sourceFen }, controller.signal);
    if (app.analysis.runId !== runId) {
      return;
    }
    applyValidatedPosition(position);
    if (position.game_over) {
      app.analysis.running = false;
      app.analysis.complete = true;
      app.analysis.status = `${position.result || "Game over"}${position.reason ? `; ${position.reason.replaceAll("_", " ")}` : ""}`;
      app.busy = false;
      render();
      return;
    }

    app.analysis.status = "Starting Sgurr";
    render();
    const response = await fetch(apiUrl("/api/search-trace"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fen: position.fen,
        engine: "v8.2",
        movetime_ms: ANALYSIS_MOVETIME_MS,
      }),
      signal: controller.signal,
    });
    if (!response.ok) {
      let detail = `Analysis request failed (${response.status})`;
      try {
        detail = (await response.json()).detail || detail;
      } catch {
        // Preserve the HTTP status when the response is not JSON.
      }
      throw new Error(detail);
    }
    await readNdjson(response, (event) => {
      if (app.analysis.runId === runId) {
        handleAnalysisEvent(event);
      }
    });
  } catch (error) {
    if (error.name !== "AbortError" && app.analysis.runId === runId) {
      app.analysis.running = false;
      app.analysis.error = error.message || String(error);
      app.analysis.status = app.analysis.error;
    }
  } finally {
    if (app.analysis.runId === runId) {
      app.analysis.controller = null;
      app.analysis.running = false;
      app.busy = false;
      render();
    }
  }
}

function stopPositionAnalysis({ updateStatus = true } = {}) {
  const controller = app.analysis.controller;
  if (controller) {
    app.analysis.runId += 1;
    controller.abort();
    app.analysis.controller = null;
  }
  if (app.analysis.running) {
    app.analysis.running = false;
    app.analysis.stopped = true;
    app.busy = false;
    if (updateStatus) {
      app.analysis.status = app.analysis.iterations.length
        ? "Stopped; showing the last completed depth"
        : "Analysis stopped";
      render();
    }
  }
}

function selectAnalysisDepth(depth) {
  const iteration = app.analysis.iterations.find((item) => item.depth === Number(depth));
  if (!iteration) {
    return;
  }
  app.analysis.selectedDepth = iteration.depth;
  app.latestEval = iteration;
  setAnalysisPosition(app.analysis.sourceFen, 0);
  render();
}

function selectAnalysisPly(ply) {
  setAnalysisPosition(app.analysis.sourceFen, ply);
  render();
}

function stepAnalysisPly(direction) {
  selectAnalysisPly(app.analysis.selectedPly + direction);
}

async function copyAnalysisFen() {
  try {
    await navigator.clipboard.writeText(app.analysis.sourceFen);
    app.analysis.status = "FEN copied to clipboard";
  } catch {
    app.analysis.status = app.analysis.sourceFen;
  }
  render();
}

export {
  copyAnalysisFen,
  selectAnalysisDepth,
  selectAnalysisPly,
  selectedAnalysisIteration,
  startPositionAnalysis,
  stepAnalysisPly,
  stopPositionAnalysis,
};
