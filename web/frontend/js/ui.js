import { playResultSound, syncGameMusic, syncMenuMusic } from "./audio.js";
import { boardOrientation, checkmateRevealPending, engineTurnAvailable, hasPremoves, humanCanMove, materialFromPieces, renderBoard, renderCheckmateEffect } from "./board.js";
import { activeClockColour, colourIsEngine, currentTimeControl, playerCardMarkup, syncClock, visibleClock } from "./clocks.js";
import { CAPTURED_PIECE_CODES, CHECKMATE_DRILLS, EDIT_PALETTE, ODDS_PRESETS, PIECES, THEMES, apiBaseLabel } from "./config.js";
import { setDemoReason } from "./demo-tooltip.js";
import { composeEditorFen, editorOddsLabel, editorReturnLabel, loadCheckmateDrill, loadOddsPreset, toggleEditorBrush } from "./editor.js";
import { favoriteMemoryOpening } from "./memory.js";
import { applyCoreMood, coreLineText } from "./personality.js";
import { plyMoveText, reviewCurrent, reviewEntries, reviewEvalAt, reviewEvalSeries, reviewSwing } from "./review.js";
import { app, refs } from "./state.js";
import { renderSettings, renderThemeGallery, renderTimeGallery } from "./themes.js";
import { decoratePieceNode, formatClock, pieceColor, pieceLabel, title } from "./utils.js";

function setStatus(message, isError = false) {
  app.status = message;
  if (!app.thinking) {
    app.coreMessage = isError ? "Signal interrupted" : message;
    app.coreLineMode = "system";
  }
  if (isError) {
    app.error = message;
  } else {
    app.error = "";
  }
  render();
}

function modeLabel() {
  if (app.humanSide === null) {
    return `Watching${app.watchPaused ? " / paused" : ""}`;
  }
  return `You play ${title(app.humanSide)}`;
}

function statusPanelText() {
  if (app.error) {
    return app.error;
  }
  if (hasPremoves()) {
    const count = app.premoves.length;
    return `${count} premove${count === 1 ? "" : "s"} queued`;
  }
  if (app.thinking) {
    return "Sgurr is thinking...";
  }
  if (app.gameOver) {
    return app.result || "Game over";
  }
  if (humanCanMove()) {
    return "Your move";
  }
  if (app.humanSide === null && app.watchPaused) {
    return "Watch paused";
  }
  if (app.mode === "game") {
    return `${title(app.turn)} to move`;
  }
  return app.status;
}

function renderWatchArena() {
  const watching = app.mode === "game" && app.humanSide === null;
  const coreHeader = refs.coreLine.closest(".core-header");
  coreHeader.classList.toggle("watch-mode", watching);
  // Body-level hook so the board-side presences can adhere to their colours
  // in the arena (see board.css) without affecting human-vs-engine games.
  document.body.classList.toggle("watch-mode", watching);
  if (!watching) {
    return;
  }

  const lastMover = app.turn === "white" ? "black" : "white";
  const active = !app.gameOver && !app.watchPaused ? app.turn : null;
  const thinking = app.thinking && !app.error ? app.turn : null;
  const cooling = app.coreCooling && !app.thinking ? lastMover : null;
  const mating = checkmateRevealPending() ? lastMover : null;

  refs.watchTimeControl.textContent = currentTimeControl().label.toUpperCase();
  refs.watchWhiteClock.textContent = formatClock(visibleClock("white"));
  refs.watchBlackClock.textContent = formatClock(visibleClock("black"));

  for (const colour of ["white", "black"]) {
    const instance = colour === "white" ? refs.watchWhiteInstance : refs.watchBlackInstance;
    const core = colour === "white" ? refs.watchWhiteCore : refs.watchBlackCore;
    instance.classList.toggle("active", active === colour);
    instance.classList.toggle("thinking", thinking === colour);
    instance.classList.toggle("flagged", app.clockFlagged === colour);
    core.classList.toggle("ready", app.backendOk && app.engineExists);
    core.classList.toggle("thinking", thinking === colour);
    core.classList.toggle("cooling", cooling === colour);
    core.classList.toggle("mating", mating === colour);
    applyCoreMood(core, colour);
  }

  if (app.error) {
    refs.watchMatchLine.textContent = "Arena signal interrupted";
  } else if (app.gameOver) {
    refs.watchMatchLine.textContent = `Match complete · ${app.result || "Game over"}`;
  } else if (app.watchPaused) {
    refs.watchMatchLine.textContent = "Arena paused · Space to resume";
  } else if (hasPremoves()) {
    refs.statusPill.textContent = `${app.premoves.length} premove${app.premoves.length === 1 ? "" : "s"} queued`;
  } else if (app.thinking) {
    refs.watchMatchLine.textContent = `${title(app.turn)} Core calculating`;
  } else if (app.moves.length && app.lastMoveInfo) {
    refs.watchMatchLine.textContent = `${title(lastMover)} Core played ${app.lastMoveInfo.san || app.lastMoveInfo.uci}`;
  } else {
    refs.watchMatchLine.textContent = "Two Sgurr cores online · White Core to move";
  }
}

function renderStatus() {
  const mateReveal = checkmateRevealPending();
  refs.appShell.dataset.mode = app.mode;
  refs.appShell.dataset.thinking = String(app.thinking);
  refs.appShell.dataset.inCheck = String(app.mode === "game" && app.inCheck && !app.gameOver);
  refs.appShell.dataset.mateReveal = String(mateReveal);
  refs.appShell.dataset.focus = String(app.mode === "game" && app.focusMode);
  refs.focusModeButton.hidden = app.mode !== "game";
  refs.focusModeButton.textContent = app.focusMode ? "Exit focus" : "Focus";
  refs.focusModeButton.setAttribute("aria-pressed", String(app.focusMode));
  refs.focusModeButton.title = app.focusMode ? "Exit focus mode (Z)" : "Focus mode (Z)";
  refs.sidePanel.hidden = app.mode === "editor" || app.mode === "analysis";
  refs.editorPanel.hidden = app.mode !== "editor";
  refs.analysisPanel.hidden = app.mode !== "analysis";
  refs.sidePanel.dataset.turn = app.turn;
  refs.sidePanel.dataset.thinking = String(app.thinking);

  const disabled = app.busy || app.thinking;
  refs.movetimeSelect.disabled = disabled;
  refs.newGameButton.disabled = disabled || app.mode !== "game";
  refs.pauseWatchButton.disabled = app.humanSide !== null || app.mode !== "game" || app.gameOver;
  refs.undoMoveButton.disabled = disabled || app.mode !== "game" || app.history.length <= 1;
  refs.redoMoveButton.disabled = disabled || app.mode !== "game" || app.redoStack.length === 0;
  refs.engineNowButton.disabled = disabled || !engineTurnAvailable();
  refs.copyFenButton.disabled = app.mode !== "game";
  refs.exportPgnButton.disabled = app.mode !== "game";
  refs.pauseWatchButton.textContent = app.watchPaused ? "Resume" : "Pause";
  refs.movetimeSelect.value = currentTimeControl().key;
  refs.sideTimeControl.textContent = currentTimeControl().label.toUpperCase();
  renderWatchArena();

  if (app.error) {
    refs.statusPill.textContent = app.error;
  } else if (app.mode === "menu") {
    refs.statusPill.textContent = "Choose a side";
  } else if (app.thinking) {
    refs.statusPill.textContent = "Sgurr is thinking";
  } else if (app.gameOver) {
    refs.statusPill.textContent = app.result || "Game over";
  } else if (humanCanMove()) {
    refs.statusPill.textContent = "Your move";
  } else if (app.humanSide === null && app.watchPaused) {
    refs.statusPill.textContent = "Watch paused";
  } else {
    refs.statusPill.textContent = `${title(app.turn)} to move`;
  }

  refs.statusModeLabel.textContent = "Status";
  refs.turnValue.textContent = app.gameOver
    ? app.result || "Game over"
    : `${title(app.turn)}${app.inCheck ? " in check" : " to move"}`;
  refs.resultValue.textContent = app.gameOver
    ? `${app.result}${app.reason ? `, ${app.reason.replaceAll("_", " ")}` : ""}`
    : `${modeLabel()}${app.currentOpening ? ` / ${app.currentOpening.name}` : ""}`;
  refs.statusValue.textContent = statusPanelText();
  refs.coreLine.textContent = coreLineText();
  const coreSpeaking = app.humanSide !== null
    && !app.thinking
    && !app.error
    && ["dialogue", "opening", "memory"].includes(app.coreLineMode);
  const openingAware = coreSpeaking && app.coreLineMode === "opening";
  refs.coreLine.classList.toggle("thinking", app.thinking && !app.error);
  refs.coreLine.classList.toggle("fading", app.coreLineFading && app.thinking && !app.error);
  refs.coreLine.classList.toggle("speaking", coreSpeaking);
  refs.engineDot.classList.toggle("thinking", app.thinking && !app.error);
  refs.engineDot.classList.toggle("cooling", app.coreCooling && !app.error);
  refs.engineDot.classList.toggle("mating", mateReveal);
  refs.engineDot.classList.toggle("speaking", coreSpeaking);
  refs.engineDot.classList.toggle("opening-aware", openingAware);
  applyCoreMood(refs.engineDot, app.humanSide === "white" ? "black" : "white");
  const coreHeader = refs.coreLine.closest(".core-header");
  if (coreHeader) {
    coreHeader.classList.toggle("speaking", coreSpeaking);
    coreHeader.classList.toggle("opening-aware", openingAware);
  }
  const statusBlock = refs.statusValue.closest(".status-block");
  statusBlock.classList.toggle("error", Boolean(app.error));
  statusBlock.classList.toggle("thinking", app.thinking && !app.error);
  statusBlock.classList.toggle("in-check", app.mode === "game" && app.inCheck && !app.gameOver);
  statusBlock.classList.toggle("checkmate-reveal", mateReveal);
  statusBlock.classList.toggle("animations-off", app.animationMode === "Off");

  if (app.mode === "editor") {
    refs.statusPill.textContent = app.editor.error || "Position Lab";
  } else if (app.mode === "analysis") {
    refs.statusPill.textContent = app.analysis.error
      || (app.analysis.running ? "Sgurr is analysing" : "Position analysis");
  }
}

function renderPlayerCards() {
  const topColour = boardOrientation() === "black" ? "white" : "black";
  const bottomColour = boardOrientation() === "black" ? "black" : "white";
  const active = activeClockColour();
  refs.topPlayerCard.dataset.colour = topColour;
  refs.bottomPlayerCard.dataset.colour = bottomColour;

  if (app.mode === "editor") {
    refs.topPlayerPresence.hidden = true;
    refs.bottomPlayerPresence.hidden = true;
    refs.topPlayerCard.classList.remove("engine-side", "human-side");
    refs.bottomPlayerCard.classList.remove("engine-side", "human-side");
    refs.topPlayerName.innerHTML = `<strong>${title(topColour)} pieces</strong><small>BOARD EDITOR</small>`;
    refs.bottomPlayerName.innerHTML = `<strong>${title(bottomColour)} pieces</strong><small>BOARD EDITOR</small>`;
    refs.topPlayerClock.textContent = app.editor.turn === topColour ? "to move" : "—";
    refs.bottomPlayerClock.textContent = app.editor.turn === bottomColour ? "to move" : "—";
    refs.topPlayerCard.classList.toggle("active", app.editor.turn === topColour);
    refs.bottomPlayerCard.classList.toggle("active", app.editor.turn === bottomColour);
    refs.topPlayerCard.classList.remove("flagged");
    refs.bottomPlayerCard.classList.remove("flagged");
    return;
  }

  if (app.mode === "analysis") {
    refs.topPlayerPresence.hidden = true;
    refs.bottomPlayerPresence.hidden = true;
    refs.topPlayerCard.classList.remove("engine-side", "human-side", "flagged");
    refs.bottomPlayerCard.classList.remove("engine-side", "human-side", "flagged");
    refs.topPlayerName.innerHTML = `<strong>${title(topColour)} pieces</strong><small>ANALYSIS BOARD</small>`;
    refs.bottomPlayerName.innerHTML = `<strong>${title(bottomColour)} pieces</strong><small>ANALYSIS BOARD</small>`;
    refs.topPlayerClock.textContent = app.turn === topColour ? "to move" : "—";
    refs.bottomPlayerClock.textContent = app.turn === bottomColour ? "to move" : "—";
    refs.topPlayerCard.classList.toggle("active", app.turn === topColour);
    refs.bottomPlayerCard.classList.toggle("active", app.turn === bottomColour);
    return;
  }

  updatePlayerPresence(refs.topPlayerCard, refs.topPlayerPresence, topColour, active);
  updatePlayerPresence(refs.bottomPlayerCard, refs.bottomPlayerPresence, bottomColour, active);

  refs.topPlayerName.innerHTML = playerCardMarkup(topColour);
  refs.bottomPlayerName.innerHTML = playerCardMarkup(bottomColour);
  refs.topPlayerClock.textContent = formatClock(visibleClock(topColour));
  refs.bottomPlayerClock.textContent = formatClock(visibleClock(bottomColour));

  refs.topPlayerCard.classList.toggle("active", active === topColour);
  refs.bottomPlayerCard.classList.toggle("active", active === bottomColour);
  refs.topPlayerCard.classList.toggle("flagged", app.clockFlagged === topColour);
  refs.bottomPlayerCard.classList.toggle("flagged", app.clockFlagged === bottomColour);
}

function updatePlayerPresence(card, presence, colour, active) {
  const isEngine = colourIsEngine(colour);
  const isHuman = app.mode === "game" && app.humanSide === colour;
  card.classList.toggle("engine-side", isEngine);
  card.classList.toggle("human-side", isHuman);
  presence.hidden = !isEngine;
  presence.classList.toggle("ready", isEngine && app.backendOk && app.engineExists);
  const isThinking = isEngine && app.thinking && active === colour;
  presence.classList.toggle("thinking", isThinking);
  presence.classList.toggle("cooling", isEngine && app.coreCooling && !isThinking);
  applyCoreMood(presence, isEngine ? colour : null);
}

function evalFraction(evalInfo) {
  if (!evalInfo) {
    return 0.5;
  }
  if (evalInfo.kind === "mate") {
    return evalInfo.value > 0 ? 1 : 0;
  }
  if (Math.abs(Number(evalInfo.value) || 0) >= 90000) {
    return evalInfo.value > 0 ? 1 : 0;
  }
  const pawns = Math.max(-8, Math.min(8, evalInfo.value / 100));
  return 1 / (1 + 10 ** (-pawns / 4));
}

function evalDisplay(evalInfo) {
  if (!evalInfo) {
    return "0.0";
  }
  if (evalInfo.kind === "mate") {
    const distance = Math.abs(Math.trunc(Number(evalInfo.value) || 0));
    return evalInfo.display || `${evalInfo.value < 0 ? "-" : ""}M${distance || ""}`;
  }
  const cp = Number(evalInfo.value) || 0;
  if (cp >= 90000) {
    return "M";
  }
  if (cp <= -90000) {
    return "-M";
  }
  return evalInfo.display || `${cp / 100 >= 0 ? "+" : ""}${(cp / 100).toFixed(1)}`;
}

function evalTrendCentipawns(evalInfo) {
  if (!evalInfo) {
    return 0;
  }
  if (evalInfo.kind === "mate") {
    return evalInfo.value > 0 ? 100000 : -100000;
  }
  return Number(evalInfo.value) || 0;
}

function addEvalHistoryPoint(evalInfo, ply) {
  if (!evalInfo) {
    return;
  }

  const point = {
    ply,
    cp: evalTrendCentipawns(evalInfo),
    display: evalInfo.display || "0.0",
  };
  const last = app.evalHistory[app.evalHistory.length - 1];
  if (last && last.ply === point.ply) {
    app.evalHistory[app.evalHistory.length - 1] = point;
  } else {
    app.evalHistory.push(point);
  }
  app.evalHistory = app.evalHistory.slice(-36);
}

function renderEvalTrend(display) {
  const reviewing = app.review.active;
  // Live: the capped rolling window, spaced evenly. Review: the whole game,
  // spaced by ply so the graph reads as elapsed game time and the swing mark
  // lands where the move actually was.
  const reviewSeries = reviewing ? reviewEvalSeries() : [];
  const points = reviewing
    ? (reviewSeries.length ? reviewSeries : [{ ply: 0, cp: 0, display }])
    : app.evalHistory.length
      ? app.evalHistory
      : [{ ply: app.moves.length, cp: 0, display }];
  const width = 320;
  const height = 96;
  const plotPad = 10;
  const maxCp = 800;
  const lastIndex = Math.max(1, points.length - 1);
  const maxPly = Math.max(1, points[points.length - 1]?.ply || 1);
  const xForPly = (ply) => plotPad + (ply / maxPly) * (width - plotPad * 2);
  const svgPoints = points.map((point, index) => {
    const x = reviewing
      ? xForPly(point.ply)
      : points.length === 1
        ? plotPad
        : plotPad + (index / lastIndex) * (width - plotPad * 2);
    const clamped = Math.max(-maxCp, Math.min(maxCp, point.cp));
    const y = height / 2 - (clamped / maxCp) * (height / 2 - plotPad);
    return { x, y };
  });
  const path = svgPoints.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");

  // Live the dot marks the latest eval; in review it marks where you are.
  let marker = svgPoints[svgPoints.length - 1] || { x: 0, y: height / 2 };
  if (reviewing) {
    const currentPly = reviewCurrent()?.ply ?? 0;
    let nearest = 0;
    for (let i = 1; i < points.length; i += 1) {
      if (Math.abs(points[i].ply - currentPly) < Math.abs(points[nearest].ply - currentPly)) {
        nearest = i;
      }
    }
    marker = svgPoints[nearest] || marker;
  }
  const dotX = Math.max(plotPad, Math.min(width - plotPad, marker.x));
  const dotY = Math.max(plotPad, Math.min(height - plotPad, marker.y));

  refs.trendPath.setAttribute("points", path);
  refs.trendDot.style.left = `${(dotX / width) * 100}%`;
  refs.trendDot.style.top = `${(dotY / height) * 100}%`;

  if (refs.trendSwingMark) {
    const swing = reviewing ? reviewSwing() : null;
    if (swing) {
      const x = xForPly(swing.toPly).toFixed(1);
      refs.trendSwingMark.setAttribute("x1", x);
      refs.trendSwingMark.setAttribute("x2", x);
      refs.trendSwingMark.hidden = false;
    } else {
      refs.trendSwingMark.hidden = true;
    }
  }
}

// The review panel: where you are in the game, and the moment it turned.
function renderReviewPanel() {
  if (!refs.reviewBlock) {
    return;
  }
  const reviewing = app.review.active && app.mode === "game";
  refs.sidePanel?.classList.toggle("review-mode", reviewing);
  refs.reviewBlock.hidden = !reviewing;
  if (refs.trendLabel) {
    refs.trendLabel.textContent = reviewing ? "Eval trend (full game)" : "Eval trend";
  }
  if (!reviewing) {
    return;
  }

  const entries = reviewEntries();
  const current = reviewCurrent();
  const lastIndex = Math.max(0, entries.length - 1);

  refs.reviewMove.textContent = plyMoveText(current);

  // The engine only searches on its own turn, so many plies carry no score.
  // Rather than a bare "no eval", fall back to the last real one and say so --
  // that is also what the eval column beside the board is showing.
  const carried = reviewEvalAt(app.review.index);
  const ownEval = current?.display || null;
  refs.reviewEval.textContent = ownEval
    || (carried ? `${carried.display} at the last scored position` : "not yet scored");
  refs.reviewEval.classList.toggle("is-empty", !ownEval);

  refs.reviewScrub.max = String(lastIndex);
  refs.reviewScrub.value = String(app.review.index);
  refs.reviewCounter.textContent = `${app.review.index} / ${lastIndex}`;

  refs.reviewStartButton.disabled = app.review.index <= 0;
  refs.reviewPrevButton.disabled = app.review.index <= 0;
  refs.reviewNextButton.disabled = app.review.index >= lastIndex;
  refs.reviewEndButton.disabled = app.review.index >= lastIndex;

  const swing = reviewSwing();
  if (swing) {
    refs.reviewSwingButton.hidden = false;
    refs.reviewSwingButton.textContent =
      `Turning point: ${swing.moveText} — ${swing.fromDisplay} to ${swing.toDisplay}`
      + ` (${swing.pawns.toFixed(1)} pawns)`;
  } else {
    refs.reviewSwingButton.hidden = true;
  }
}

function renderEval() {
  const editorMaterial = app.mode === "editor" ? materialFromPieces(app.editor.pieces) : null;
  const reviewEval = app.review.active ? reviewEvalAt(app.review.index) : null;
  const evalInfo =
    app.review.active
      ? reviewEval
      : app.mode === "editor"
      ? {
          kind: "cp",
          value: editorMaterial.diff * 100,
          display:
            editorMaterial.diff > 0
              ? `+${editorMaterial.diff}.0`
              : editorMaterial.diff < 0
                ? `${editorMaterial.diff}.0`
                : "0.0",
        }
      : app.latestEval;
  const shownEval = evalDisplay(evalInfo);
  refs.evalChip.textContent = shownEval;
  refs.evalValue.textContent = shownEval;
  refs.trendValue.textContent =
    shownEval.startsWith("+") || shownEval.startsWith("-") || shownEval.startsWith("M")
      ? shownEval
      : `+${shownEval}`;
  refs.evalFill.style.height = `${Math.round(evalFraction(evalInfo) * 100)}%`;
  if (app.mode === "editor") {
    renderEvalTrend(shownEval);
  } else {
    renderEvalTrend(refs.trendValue.textContent);
  }

  if (app.mode === "editor") {
    refs.evalMeta.textContent = "Material only";
    return;
  }

  if (!evalInfo) {
    refs.evalMeta.textContent = "Waiting for Sgurr";
    return;
  }

  const parts = [];
  if (evalInfo.depth !== null && evalInfo.depth !== undefined) {
    parts.push(`depth ${evalInfo.depth}`);
  }
  if (evalInfo.nodes !== null && evalInfo.nodes !== undefined) {
    parts.push(`${Number(evalInfo.nodes).toLocaleString()} nodes`);
  }
  if (evalInfo.time_ms !== null && evalInfo.time_ms !== undefined) {
    parts.push(`${evalInfo.time_ms} ms`);
  }
  refs.evalMeta.textContent = parts.join(" / ") || "White perspective";
}

function renderMaterial() {
  const material =
    app.mode === "editor"
      ? materialFromPieces(app.editor.pieces)
      : app.material || {
          white: 39,
          black: 39,
          diff: 0,
          captured: { white: [], black: [] },
        };
  refs.materialValue.textContent = `${material.white} : ${material.black}`;
  refs.materialDiff.textContent =
    material.diff > 0
      ? `White +${material.diff}`
      : material.diff < 0
        ? `Black +${Math.abs(material.diff)}`
        : "Level";

  refs.capturedPieces.innerHTML = "";
  for (const side of ["white", "black"]) {
    const row = document.createElement("div");
    row.className = "captured-row";

    const label = document.createElement("span");
    label.className = "captured-label";
    label.textContent = `${title(side)} lost`;

    const pieces = document.createElement("span");
    pieces.className = "captured-pieces";
    const lost = material.captured?.[side] || [];
    if (lost.length) {
      for (const name of lost) {
        const code = CAPTURED_PIECE_CODES[name] || "p";
        const pieceCode = side === "white" ? code.toUpperCase() : code;
        const icon = document.createElement("span");
        icon.className = `captured-piece ${pieceColor(pieceCode)}`;
        decoratePieceNode(icon, pieceCode);
        pieces.appendChild(icon);
      }
    } else {
      pieces.textContent = "-";
    }

    row.append(label, pieces);
    refs.capturedPieces.appendChild(row);
  }
}

function renderMoves() {
  refs.plyCount.textContent = `${app.moves.length} ply`;
  refs.moveRows.innerHTML = "";

  if (!app.moveRows.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td></td><td colspan="2">No moves yet</td>';
    refs.moveRows.appendChild(row);
    return;
  }

  app.moveRows.forEach((moveRow, index) => {
    const row = document.createElement("tr");
    if (index === app.moveRows.length - 1) {
      row.className = "latest";
    }
    row.innerHTML = `
      <td>${moveRow.number}.</td>
      <td>${moveRow.white || "-"}</td>
      <td>${moveRow.black || "-"}</td>
    `;
    refs.moveRows.appendChild(row);
  });

  if (app.redoStack.length) {
    const row = document.createElement("tr");
    row.className = "redo-notice";
    row.innerHTML = `<td></td><td colspan="2">${app.redoStack.length} move(s) available to redo</td>`;
    refs.moveRows.appendChild(row);
  }

  requestAnimationFrame(() => {
    refs.movesScroll.scrollTop = refs.movesScroll.scrollHeight;
  });
}

function renderBackend() {
  const base = apiBaseLabel();
  refs.backendValue.textContent = app.backendOk
    ? `${base} / ${app.backendDetail}`
    : `${base} unavailable`;
  refs.engineDot.classList.toggle("ready", app.backendOk && app.engineExists);
  refs.backendValue.closest(".engine-block").hidden = !app.showEngineInfo;
  refs.evalMeta.hidden = !app.showEngineInfo;
}

function resultMessage() {
  if (!app.gameOver) {
    return { title: "Game over", detail: "", king: "♔" };
  }

  const reason = (app.reason || "").replaceAll("_", " ");
  const detail = reason ? reason.charAt(0).toUpperCase() + reason.slice(1) : app.result || "";

  if (app.result === "1-0") {
    return { title: "White wins", detail, king: "♔" };
  }
  if (app.result === "0-1") {
    return { title: "Black wins", detail, king: "♚" };
  }
  return { title: "Draw", detail, king: "♔" };
}

function desktopResultMessage() {
  if (!app.gameOver) {
    return { title: "Game over", detail: "", king: PIECES.K };
  }

  if (app.reason === "time_forfeit" || app.clockFlagged) {
    const flagged = app.clockFlagged ? title(app.clockFlagged) : app.result === "1-0" ? "Black" : "White";
    if (app.reason === "timeout_insufficient_material") {
      return {
        title: "Draw",
        detail: `${flagged} ran out of time, but checkmate is impossible`,
        king: PIECES.K,
      };
    }
    const winner = app.result === "1-0" ? "White" : "Black";
    return {
      title: `${winner} wins`,
      detail: `${flagged} loses on time`,
      king: app.result === "1-0" ? PIECES.K : PIECES.k,
    };
  }

  const details = {
    checkmate: "Checkmate",
    stalemate: "Stalemate",
    insufficient_material: "Insufficient material",
    seventyfive_moves: "75-move rule",
    fivefold_repetition: "Fivefold repetition",
    fifty_moves: "50-move rule",
    threefold_repetition: "Threefold repetition",
  };
  const detail = details[app.reason] || app.result || "";

  if (app.result === "1-0") {
    return { title: "White wins", detail, king: PIECES.K };
  }
  if (app.result === "0-1") {
    return { title: "Black wins", detail, king: PIECES.k };
  }
  return { title: "Draw", detail, king: PIECES.k };
}

function resultOutcome() {
  if (!app.gameOver || !app.result) {
    return "";
  }

  const winner =
    app.winner ||
    (app.result === "1-0" ? "white" : app.result === "0-1" ? "black" : null);

  if (!winner) {
    return app.humanSide === null ? "watch-draw" : "human-draw";
  }
  if (app.humanSide === null) {
    return winner === "white" ? "watch-white-win" : "watch-black-win";
  }
  return winner === app.humanSide ? "human-win" : "sgurr-win";
}

function resultPresentation(outcome, message) {
  const detail = message.detail || "Game complete";
  const presentations = {
    "human-win": {
      label: "CORE FAILURE // VICTORY CONFIRMED",
      title: "You prevailed",
      detail: `${detail} / ${message.title}`,
    },
    "sgurr-win": {
      label: "SGURR // GAME CONCLUDED",
      title: "Sgurr prevails",
      detail: `${detail} / ${message.title}`,
    },
    "human-draw": {
      label: "POSITION STABLE // EQUILIBRIUM",
      title: "Neither yielded",
      detail: `${detail} / Human and Core remain level`,
    },
    "watch-draw": {
      label: "ARENA CONVERGENCE // NO VICTOR",
      title: "Perfect equilibrium",
      detail: `${detail} / Both cores resolve equally`,
    },
    "watch-white-win": {
      label: "WHITE CORE // VICTORY CONFIRMED",
      title: "White Core prevails",
      detail: `${detail} / Sgurr White wins`,
    },
    "watch-black-win": {
      label: "BLACK CORE // VICTORY CONFIRMED",
      title: "Black Core prevails",
      detail: `${detail} / Sgurr Black wins`,
    },
  };
  return presentations[outcome] || {
    label: "SGURR // GAME CONCLUDED",
    title: message.title,
    detail: message.detail,
  };
}

function renderResultModal() {
  refs.rematchButton.textContent = app.gameOrigin === "editor" ? "Replay position" : "Rematch";
  // Reviewing keeps the game-over state, so the modal has to stand aside
  // while it runs -- and reappears when review is dismissed.
  refs.resultModal.hidden =
    !(app.mode === "game" && app.gameOver) || checkmateRevealPending() || app.review.active;
  if (refs.resultModal.hidden) {
    return;
  }

  refs.resultModal.dataset.reason = app.reason || "";
  refs.resultModal.dataset.result = app.result || "";
  const outcome = resultOutcome();
  if (!app.resultSoundPlayed) {
    app.resultSoundPlayed = true;
    playResultSound(outcome);
  }
  refs.resultModal.dataset.outcome = outcome;
  refs.resultModal.dataset.winner = app.winner || "none";
  refs.resultModal.dataset.animation = app.animationMode.toLowerCase();
  const message = desktopResultMessage();
  const resultKingPiece = outcome === "sgurr-win"
    ? app.humanSide === "black" ? "k" : "K"
    : app.result === "1-0" ? "K" : app.result === "0-1" ? "k" : null;
  if (resultKingPiece) {
    if (refs.resultKing.dataset.piece !== resultKingPiece || !refs.resultKing.querySelector(".piece-image")) {
      decoratePieceNode(refs.resultKing, resultKingPiece);
    }
  } else {
    delete refs.resultKing.dataset.piece;
    refs.resultKing.removeAttribute("aria-label");
    refs.resultKing.textContent = message.king;
  }
  if (!refs.resultWhiteKing.querySelector(".piece-image")) {
    decoratePieceNode(refs.resultWhiteKing, "K");
  }
  if (!refs.resultBlackKing.querySelector(".piece-image")) {
    decoratePieceNode(refs.resultBlackKing, "k");
  }
  const presentation = resultPresentation(outcome, message);
  refs.resultSystemLabel.textContent = presentation.label;
  refs.resultTitle.textContent = presentation.title;
  refs.resultDetail.textContent = presentation.detail;
  refs.resultPill.textContent = app.result || "*";
}

function renderEditor() {
  if (app.mode !== "editor") {
    return;
  }

  refs.editorHeading.textContent = "Position Lab";
  refs.editorPurpose.textContent = "Build or paste a position, then play it or ask Sgurr for a deep analysis.";
  if (document.activeElement !== refs.editorFenInput && !app.busy) {
    refs.editorFenInput.value = composeEditorFen();
  }
  refs.editorPlayerButton.textContent = editorReturnLabel();
  const editorSelfPlayReason = app.publicDemo
    ? "Self-play is available locally; the free demo supports White or Black."
    : "";
  refs.editorPlayerButton.title = editorSelfPlayReason;
  setDemoReason(refs.editorPlayerButton, editorSelfPlayReason);
  refs.editorTurnButton.textContent = `First move: ${title(app.editor.turn)}`;
  refs.editorOddsRecipientButton.textContent = editorOddsLabel();
  const actionDisabled = app.busy || app.thinking || !app.backendOk || !app.engineExists;
  refs.editorPlayButton.disabled = actionDisabled;
  refs.editorAnalyseButton.disabled = actionDisabled;
  refs.editorLoadFenButton.disabled = app.busy || !app.backendOk;
  refs.editorAnalyseButton.classList.add("preferred");
  refs.editorStatus.textContent = app.editor.status;
  refs.editorStatus.closest(".status-block").classList.toggle("error", Boolean(app.editor.error));

  refs.editorDrills.innerHTML = "";
  for (const drill of CHECKMATE_DRILLS) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = drill.label;
    button.addEventListener("click", () => loadCheckmateDrill(drill.key));
    refs.editorDrills.appendChild(button);
  }

  refs.editorOdds.innerHTML = "";
  for (const preset of ODDS_PRESETS) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = preset.label;
    button.addEventListener("click", () => loadOddsPreset(preset.key));
    refs.editorOdds.appendChild(button);
  }

  refs.editorPalette.innerHTML = "";
  for (const piece of EDIT_PALETTE) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `palette-button ${app.editor.brush === piece ? "active" : ""}`;
    button.title = pieceLabel(piece);
    const icon = document.createElement("span");
    icon.className = `palette-piece ${pieceColor(piece)}`;
    decoratePieceNode(icon, piece);
    button.appendChild(icon);
    button.addEventListener("click", () => toggleEditorBrush(piece));
    refs.editorPalette.appendChild(button);
  }
}

function formatAnalysisCount(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "—";
  }
  if (number >= 1_000_000) {
    return `${(number / 1_000_000).toFixed(number >= 10_000_000 ? 0 : 1)}m`;
  }
  if (number >= 1_000) {
    return `${(number / 1_000).toFixed(number >= 100_000 ? 0 : 1)}k`;
  }
  return number.toLocaleString();
}

function analysisLeaderRuns(iterations) {
  const runs = [];
  const ordered = [...iterations].sort((left, right) => left.depth - right.depth);
  ordered.forEach((iteration) => {
    const uci = iteration.pv?.[0] || "";
    const move = iteration.pv_san?.[0] || uci;
    if (!move) {
      return;
    }
    const key = uci || move;
    const current = runs.at(-1);
    if (current?.key === key) {
      current.endDepth = iteration.depth;
      current.iteration = iteration;
      current.depths.push(iteration.depth);
      return;
    }
    runs.push({
      key,
      uci,
      move,
      startDepth: iteration.depth,
      endDepth: iteration.depth,
      firstIteration: iteration,
      iteration,
      depths: [iteration.depth],
    });
  });
  return runs;
}

function analysisRunDetail(run, previousRun) {
  const details = [run.startDepth === run.endDepth
    ? `reported at depth ${run.startDepth}`
    : `held through depth ${run.endDepth}`];
  if (run.depths.length > 1) {
    details.push(`${run.depths.length} completed iterations`);
  }
  if (
    previousRun?.iteration?.kind === "cp"
    && run.firstIteration?.kind === "cp"
    && Number.isFinite(previousRun.iteration.value)
    && Number.isFinite(run.firstIteration.value)
  ) {
    const shift = run.firstIteration.value - previousRun.iteration.value;
    if (shift !== 0) {
      details.push(`${shift > 0 ? "+" : ""}${(shift / 100).toFixed(1)} eval shift`);
    }
  }
  return details.join(" · ");
}

function renderAnalysis() {
  if (app.mode !== "analysis") {
    return;
  }

  const analysis = app.analysis;
  const selected = analysis.iterations.find(
    (iteration) => iteration.depth === analysis.selectedDepth,
  ) || analysis.iterations.at(-1) || null;
  const pvSan = selected?.pv_san || [];
  const pvFens = selected?.pv_fens || [analysis.sourceFen];
  const selectedPly = Math.min(analysis.selectedPly, Math.max(0, pvFens.length - 1));
  const bestSan = selected?.pv_san?.[0] || analysis.bestmoveSan;
  const bestUci = selected?.pv?.[0] || analysis.bestmove;

  refs.analysisEngineName.textContent = analysis.engineLabel;
  refs.analysisStatus.textContent = analysis.status;
  refs.analysisPanel.dataset.state = analysis.error
    ? "error"
    : analysis.running
      ? "running"
      : analysis.complete
        ? "complete"
        : "idle";
  refs.analysisCore.classList.toggle("ready", app.backendOk && app.engineExists);
  refs.analysisCore.classList.toggle("thinking", analysis.running);
  refs.analysisScore.textContent = selected?.display || "0.0";
  refs.analysisBestMove.textContent = bestSan || (analysis.running ? "Calculating" : "—");
  refs.analysisBestMoveUci.textContent = bestUci || "Completed depths will appear live";
  refs.analysisDepth.textContent = selected?.depth ?? "—";
  refs.analysisNodes.textContent = formatAnalysisCount(selected?.nodes);
  refs.analysisNps.textContent = selected?.nps ? `${formatAnalysisCount(selected.nps)}/s` : "—";
  refs.analysisTime.textContent = selected?.time_ms === null || selected?.time_ms === undefined
    ? "—"
    : selected.time_ms >= 1_000
      ? `${(selected.time_ms / 1_000).toFixed(1)}s`
      : `${selected.time_ms}ms`;
  refs.analysisLineLabel.textContent = selected
    ? `Depth ${selected.depth} · ${pvSan.length} predicted ${pvSan.length === 1 ? "ply" : "plies"}`
    : "Sgurr's predicted continuation";
  refs.analysisPlyCounter.textContent = selectedPly
    ? `After ${selectedPly} ${selectedPly === 1 ? "ply" : "plies"}`
    : "Root position";
  refs.analysisLimitNote.textContent = `Bounded server analysis · up to ${(analysis.movetimeMs / 1_000).toFixed(0)} seconds · one principal variation`;
  refs.analysisLiveBadge.textContent = analysis.running ? "LIVE" : analysis.error ? "ERROR" : "COMPLETE";
  refs.analysisStopButton.disabled = !analysis.running;
  refs.analysisAgainButton.disabled = analysis.running || !app.backendOk || !app.engineExists;
  refs.analysisPrevPlyButton.disabled = selectedPly <= 0;
  refs.analysisRootButton.disabled = selectedPly === 0;
  refs.analysisNextPlyButton.disabled = selectedPly >= pvFens.length - 1;

  refs.analysisPvMoves.innerHTML = "";
  if (!pvSan.length) {
    const empty = document.createElement("p");
    empty.className = "analysis-empty-line";
    empty.textContent = analysis.error
      ? "No completed principal variation"
      : "Waiting for the first completed depth…";
    refs.analysisPvMoves.appendChild(empty);
  } else {
    pvSan.forEach((san, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.ply = String(index + 1);
      button.className = index + 1 === selectedPly ? "active" : "";
      const count = document.createElement("span");
      count.textContent = String(index + 1);
      const move = document.createElement("strong");
      move.textContent = san;
      button.append(count, move);
      refs.analysisPvMoves.appendChild(button);
    });
  }

  refs.analysisDepths.innerHTML = "";
  const leaderRuns = analysisLeaderRuns(analysis.iterations);
  refs.analysisChangeCount.textContent = leaderRuns.length === 1
    ? "1 leader"
    : `${leaderRuns.length} leaders`;
  if (!leaderRuns.length) {
    refs.analysisDecisionSummary.textContent = "Only changes in Sgurr's preferred move appear here.";
    const waiting = document.createElement("p");
    waiting.className = "analysis-depth-waiting";
    waiting.textContent = analysis.error ? analysis.error : "Waiting for Sgurr's first completed search depth";
    refs.analysisDepths.appendChild(waiting);
  } else {
    const latestRun = leaderRuns.at(-1);
    refs.analysisDecisionSummary.textContent = leaderRuns.length === 1
      ? `${latestRun.move} has led at every completed depth${analysis.running ? " so far." : "."}`
      : `${latestRun.move} took the lead at depth ${latestRun.startDepth} and ${analysis.running ? "leads now." : `held through depth ${latestRun.endDepth}.`}`;
    leaderRuns.slice(-8).reverse().forEach((run, index) => {
      const sourceIndex = leaderRuns.length - 1 - index;
      const previousRun = sourceIndex > 0 ? leaderRuns[sourceIndex - 1] : null;
      const isLatest = sourceIndex === leaderRuns.length - 1;
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.depth = String(run.endDepth);
      button.className = `analysis-leader-card${run.depths.includes(analysis.selectedDepth) ? " active" : ""}${isLatest ? " latest" : ""}`;
      button.setAttribute("aria-label", `Inspect ${run.move} at depth ${run.endDepth}`);

      const marker = document.createElement("span");
      marker.className = "analysis-leader-marker";
      marker.textContent = String(sourceIndex + 1).padStart(2, "0");

      const copy = document.createElement("span");
      copy.className = "analysis-leader-copy";
      const moveLine = document.createElement("span");
      moveLine.className = "analysis-leader-move";
      const move = document.createElement("strong");
      move.textContent = run.move;
      const uci = document.createElement("code");
      uci.textContent = run.uci || "candidate";
      moveLine.append(move, uci);
      const detail = document.createElement("small");
      detail.textContent = analysisRunDetail(run, previousRun);
      const work = document.createElement("span");
      work.className = "analysis-leader-work";
      work.textContent = `${formatAnalysisCount(run.iteration.nodes)} nodes · ${formatAnalysisCount(run.iteration.time_ms)} ms`;
      copy.append(moveLine, detail, work);

      const readout = document.createElement("span");
      readout.className = "analysis-leader-readout";
      const depth = document.createElement("strong");
      depth.textContent = run.startDepth === run.endDepth
        ? `D${run.startDepth}`
        : `D${run.startDepth}-D${run.endDepth}`;
      const score = document.createElement("span");
      score.className = "depth-score";
      score.textContent = run.iteration.display || "0.0";
      const state = document.createElement("small");
      state.textContent = isLatest ? analysis.running ? "LEADING" : "FINAL" : "CHANGED";
      readout.append(depth, score, state);

      button.append(marker, copy, readout);
      refs.analysisDepths.appendChild(button);
    });
  }
}

function renderBlobMemory() {
  const memory = app.memory;
  if (!memory.games) {
    refs.menuMemory.hidden = true;
    refs.menuMemory.textContent = "";
    return;
  }

  const favorite = favoriteMemoryOpening();
  const averagePly = Math.round(memory.totalPly / memory.games);
  const summary = [
    `CORE MEMORY // ${memory.games} ENCOUNTER${memory.games === 1 ? "" : "S"}`,
    `${memory.wins}W ${memory.losses}L ${memory.draws}D`,
    `AVG ${averagePly} PLY`,
    `LONGEST ${memory.longestPly} PLY`,
  ];
  if (favorite) {
    summary.push(`FAV ${favorite.name}`);
  }
  refs.menuMemory.textContent = summary.join(" / ");
  refs.menuMemory.hidden = false;
}

// Self-play is a mirror match, so the arena is named for the build fighting
// itself: the quoted codename where a release has one ('Sgurr v8.2
// "Thearlaich"' -> Thearlaich), otherwise whatever follows "Sgurr"
// ('Sgurr classical' -> Classical). This used to be hardcoded as "MacKenzie
// Mirror" and froze there when v4.0 stopped being the current release.
function engineCodename(label) {
  const quoted = label.match(/"([^"]+)"/)?.[1];
  if (quoted) {
    return quoted;
  }
  const trailing = label.replace(/^Sgurr\s*/i, "").trim();
  return trailing ? title(trailing) : "Sgurr";
}

function renderMenu() {
  refs.menuScreen.hidden = app.mode !== "menu";
  refs.menuTimeButton.textContent = currentTimeControl().label;
  refs.menuThemeButton.textContent = THEMES[app.themeKey]?.label || THEMES.wood.label;
  const engineLabel = app.engineLabel || 'Sgurr v8.2 "Thearlaich"';
  const engineSubtitle = app.engineSubtitle || "GEN8 NNUE + PACKED TT · ~3012";
  refs.menuEngineButton.textContent = engineLabel;
  if (refs.menuEngineCaption) {
    refs.menuEngineCaption.textContent = engineSubtitle;
  }
  if (refs.coreEngineName) {
    refs.coreEngineName.textContent = engineLabel;
  }
  if (refs.coreEngineSubtitle) {
    refs.coreEngineSubtitle.textContent = engineSubtitle;
  }
  if (refs.watchArenaTitle) {
    refs.watchArenaTitle.textContent = `${engineCodename(engineLabel)} Mirror`;
  }
  renderThemeGallery();
  renderTimeGallery();
  renderSettings();
  renderBlobMemory();

  const canStart = app.backendOk && app.engineExists && !app.busy && !app.thinking;
  const availableEngines = app.engines.filter((entry) => entry.available !== false).length;
  const selfPlayReason = app.publicDemo
    ? "Self-play runs continuously and is available when running Sgurr locally."
    : "";
  const historicalReason = app.publicDemo
    ? "Historical Sgurr builds are available locally; the free demo runs v8.2 only."
    : "";
  refs.playWhiteButton.disabled = !canStart;
  refs.playBlackButton.disabled = !canStart;
  refs.watchButton.disabled = !canStart;
  refs.watchButton.classList.toggle("demo-disabled", app.publicDemo);
  if (app.publicDemo) {
    refs.watchButton.setAttribute("aria-disabled", "true");
    refs.watchButton.setAttribute("aria-label", `Watch Sgurr vs itself. ${selfPlayReason}`);
    refs.watchButton.title = selfPlayReason;
  } else {
    refs.watchButton.removeAttribute("aria-disabled");
    refs.watchButton.removeAttribute("aria-label");
    refs.watchButton.title = "";
  }
  setDemoReason(refs.watchButton, selfPlayReason);
  refs.engineDownButton.disabled = availableEngines <= 1;
  refs.engineUpButton.disabled = availableEngines <= 1;
  setDemoReason(refs.engineDownButton, historicalReason);
  setDemoReason(refs.engineUpButton, historicalReason);
  refs.positionLabButton.disabled = app.busy || app.thinking;

  if (app.menuMessage) {
    refs.menuStatus.textContent = app.menuMessage;
    refs.menuStatus.dataset.state = "message";
  } else if (!app.backendOk) {
    refs.menuStatus.textContent = "Waiting for backend at 127.0.0.1:8000";
    refs.menuStatus.dataset.state = "warning";
  } else if (!app.engineExists) {
    refs.menuStatus.textContent = "Build the current Sgurr engine before playing";
    refs.menuStatus.dataset.state = "warning";
  } else {
    refs.menuStatus.textContent = "Ready";
    refs.menuStatus.dataset.state = "ready";
  }
}

function render() {
  syncClock();
  renderMenu();
  renderBoard();
  renderCheckmateEffect();
  renderPlayerCards();
  renderStatus();
  renderEval();
  renderMaterial();
  renderMoves();
  renderBackend();
  renderEditor();
  renderAnalysis();
  renderReviewPanel();
  renderResultModal();
  syncMenuMusic();
  syncGameMusic();
}

function renderClockUi() {
  syncClock();
  renderCheckmateEffect();
  renderPlayerCards();
  renderStatus();
  renderResultModal();
  syncGameMusic();
}

export {
  setStatus,
  modeLabel,
  statusPanelText,
  renderWatchArena,
  renderStatus,
  renderPlayerCards,
  updatePlayerPresence,
  evalFraction,
  evalDisplay,
  evalTrendCentipawns,
  addEvalHistoryPoint,
  renderEvalTrend,
  renderEval,
  renderMaterial,
  renderMoves,
  renderBackend,
  resultMessage,
  desktopResultMessage,
  resultOutcome,
  resultPresentation,
  renderResultModal,
  renderEditor,
  renderAnalysis,
  renderBlobMemory,
  renderMenu,
  render,
  renderClockUi,
};
