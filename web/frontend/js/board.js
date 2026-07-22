import { playCheckmateRevealSound, playSound } from "./audio.js";
import { FILES, PROMOTIONS } from "./config.js";
import { handleEditorDelete } from "./editor.js";
import { cancelPremoves, handleSquare, makePlayerMove, queuePremove, tryMove } from "./game.js";
import { reviewCurrent } from "./review.js";
import { app, refs } from "./state.js";
import { render } from "./ui.js";
import { clampNumber, clonePieces, decoratePieceNode, parseFenPieces, pieceColor, pieceForColour, pieceLabel } from "./utils.js";

function hasPremoves() {
  return app.premoves.length > 0;
}

function clearPremoveQueueState({ restoreMoves = true } = {}) {
  app.premoves = [];
  app.premoveRequestToken += 1;
  if (restoreMoves) {
    app.premoveMoves = [...app.basePremoveMoves];
  }
}

function applyProjectedPremove(pieces, premove) {
  const { uci, from, to } = premove;
  const movingPiece = pieces[from] || premove.piece;
  if (!movingPiece || !uci) {
    return pieces;
  }

  const projected = pieces;
  delete projected[from];

  if (
    movingPiece.toLowerCase() === "p" &&
    from[0] !== to[0] &&
    !projected[to]
  ) {
    delete projected[`${to[0]}${from[1]}`];
  }

  let placedPiece = movingPiece;
  if (uci.length === 5) {
    placedPiece = pieceForColour(uci[4], pieceColor(movingPiece));
  }
  projected[to] = placedPiece;

  if (movingPiece.toLowerCase() === "k" && Math.abs(FILES.indexOf(from[0]) - FILES.indexOf(to[0])) === 2) {
    const rank = from[1];
    const rookFrom = to[0] === "g" ? `h${rank}` : `a${rank}`;
    const rookTo = to[0] === "g" ? `f${rank}` : `d${rank}`;
    if (projected[rookFrom]) {
      projected[rookTo] = projected[rookFrom];
      delete projected[rookFrom];
    }
  }

  return projected;
}

function projectPremovePieces(pieces) {
  if (!hasPremoves()) {
    return pieces;
  }

  const projected = { ...pieces };
  for (const premove of app.premoves) {
    applyProjectedPremove(projected, premove);
  }
  return projected;
}

function materialFromPieces(pieces) {
  const values = { p: 1, n: 3, b: 3, r: 5, q: 9, k: 0 };
  const starting = { pawn: 8, knight: 2, bishop: 2, rook: 2, queen: 1 };
  const names = { p: "pawn", n: "knight", b: "bishop", r: "rook", q: "queen" };
  const remaining = {
    white: { pawn: 0, knight: 0, bishop: 0, rook: 0, queen: 0 },
    black: { pawn: 0, knight: 0, bishop: 0, rook: 0, queen: 0 },
  };
  const material = {
    white: 0,
    black: 0,
    diff: 0,
    captured: { white: [], black: [] },
  };

  for (const piece of Object.values(pieces)) {
    const side = pieceColor(piece);
    const name = names[piece.toLowerCase()];
    material[side] += values[piece.toLowerCase()] || 0;
    if (name) {
      remaining[side][name] += 1;
    }
  }

  material.diff = material.white - material.black;
  for (const side of ["white", "black"]) {
    for (const [name, count] of Object.entries(starting)) {
      for (let index = remaining[side][name]; index < count; index += 1) {
        material.captured[side].push(name);
      }
    }
  }
  return material;
}

function boardOrientation() {
  const orientationSide = app.mode === "editor" ? app.editor.returnSide : app.humanSide;
  const autoOrientation = app.autoFlipAsBlack && orientationSide === "black" ? "black" : "white";
  if (!app.manualFlip) {
    return autoOrientation;
  }
  return autoOrientation === "black" ? "white" : "black";
}

function orientedSquares() {
  const ranks =
    boardOrientation() === "black" ? [1, 2, 3, 4, 5, 6, 7, 8] : [8, 7, 6, 5, 4, 3, 2, 1];
  const files = boardOrientation() === "black" ? [...FILES].reverse() : FILES;
  const squares = [];

  for (const rank of ranks) {
    for (const file of files) {
      squares.push(`${file}${rank}`);
    }
  }
  return squares;
}

function squareIsLight(square) {
  const file = FILES.indexOf(square[0]);
  const rank = Number(square[1]) - 1;
  return (file + rank) % 2 === 1;
}

function humanCanMove() {
  return (
    app.mode === "game" &&
    app.humanSide !== null &&
    !app.busy &&
    !app.thinking &&
    !app.gameOver &&
    app.turn === app.humanSide
  );
}

function canQueuePremove() {
  return (
    app.mode === "game" &&
    app.humanSide !== null &&
    !app.gameOver &&
    app.thinking &&
    app.turn !== app.humanSide
  );
}

function boardInteractionAvailable() {
  // Review is a read-only view of a finished game; the board is scenery.
  if (app.review.active) {
    return false;
  }
  return humanCanMove() || canQueuePremove();
}

function engineTurnAvailable() {
  if (app.mode !== "game" || app.gameOver || app.busy || app.thinking || !app.backendOk) {
    return false;
  }
  return app.humanSide === null || app.turn !== app.humanSide;
}

function engineToMove() {
  return engineTurnAvailable() && (app.humanSide === null || !app.engineAutoPaused);
}

function legalFrom(square) {
  const moves = canQueuePremove() ? app.premoveMoves : app.legalMoves;
  return moves.filter((move) => move.slice(0, 2) === square);
}

function legalTargets(square) {
  return new Set(legalFrom(square).map((move) => move.slice(2, 4)));
}

function lastMoveSquares() {
  // In review the highlight tracks the move that produced the position on
  // screen, not the last move of the finished game.
  const uci = app.review.active ? reviewCurrent()?.uci : app.lastMove;
  if (!uci || uci.length < 4) {
    return new Set();
  }
  return new Set([uci.slice(0, 2), uci.slice(2, 4)]);
}

function kingSquare(pieces, colour) {
  const king = colour === "white" ? "K" : "k";
  for (const [square, piece] of Object.entries(pieces)) {
    if (piece === king) {
      return square;
    }
  }
  return null;
}

function squareCenterPercent(square) {
  if (!square) {
    return { x: 50, y: 50 };
  }
  const orientation = boardOrientation();
  const files = orientation === "black" ? [...FILES].reverse() : FILES;
  const ranks = orientation === "black" ? [1, 2, 3, 4, 5, 6, 7, 8] : [8, 7, 6, 5, 4, 3, 2, 1];
  const col = Math.max(0, files.indexOf(square[0]));
  const row = Math.max(0, ranks.indexOf(Number(square[1])));
  return {
    x: ((col + 0.5) / 8) * 100,
    y: ((row + 0.5) / 8) * 100,
  };
}

function renderCheckmateEffect() {
  const active = app.mode === "game" && checkmateRevealPending() && app.animationMode !== "Off";
  // The mated side is the side to move. When the human delivered the mate,
  // the board plays Sgurr's death instead of Sgurr's feast.
  const humanWon = active && app.humanSide !== null && app.turn !== app.humanSide;
  refs.boardWrap.classList.toggle("checkmate-reveal", active);
  refs.board.classList.toggle("checkmate-reveal", active);
  refs.sidePanel.classList.toggle("checkmate-reveal", active);
  refs.boardWrap.classList.toggle("human-victory", humanWon);
  refs.mateDevour.classList.toggle("human-victory", humanWon);
  refs.mateDevour.hidden = !active;

  if (!active) {
    refs.board.style.removeProperty("--mate-duration");
    refs.boardWrap.style.removeProperty("--mate-duration");
    return;
  }

  const pieces = projectPremovePieces(parseFenPieces(app.fen));
  const square = kingSquare(pieces, app.turn);
  const center = squareCenterPercent(square);
  const piece = app.turn === "white" ? "K" : "k";
  const duration = checkmateRevealDelayMs();
  refs.mateDevour.style.setProperty("--mate-x", `${center.x}%`);
  refs.mateDevour.style.setProperty("--mate-y", `${center.y}%`);
  // The eye opens directly over the king, clamped inward just enough that
  // it never clips the board edge when the king dies in a corner.
  refs.mateDevour.style.setProperty("--eye-x", `${clampNumber(center.x, 24, 76)}%`);
  refs.mateDevour.style.setProperty("--eye-y", `${clampNumber(center.y, 24, 76)}%`);
  refs.mateDevour.style.setProperty("--mate-duration", `${duration}ms`);
  refs.board.style.setProperty("--mate-duration", `${duration}ms`);
  refs.boardWrap.style.setProperty("--mate-duration", `${duration}ms`);

  if (refs.mateDevourPiece.dataset.piece !== piece) {
    refs.mateDevourPiece.replaceChildren();
    refs.mateDevourPiece.className = `mate-devour-piece ${pieceColor(piece)}`;
    decoratePieceNode(refs.mateDevourPiece, piece);
  }
}

function moveAnimationDurationMs() {
  if (app.animationMode === "Off") {
    return 0;
  }
  return 140;
}

function humanMoveAnimationDurationMs() {
  if (app.animationMode === "Off") {
    return 0;
  }
  return 210;
}

function checkmateRevealDelayMs() {
  if (app.animationMode === "Off") {
    return 0;
  }
  return 4200;
}

function isCheckmateResult() {
  return app.gameOver && app.reason === "checkmate";
}

function checkmateRevealPending() {
  return isCheckmateResult() && app.gameOverRevealAt !== null && performance.now() < app.gameOverRevealAt;
}

function clearGameOverRevealTimer() {
  window.clearTimeout(app.gameOverRevealTimer);
  app.gameOverRevealTimer = null;
}

function scheduleGameOverRevealEnd() {
  clearGameOverRevealTimer();
  if (!app.gameOverRevealAt) {
    return;
  }

  const remaining = Math.max(0, app.gameOverRevealAt - performance.now());
  app.gameOverRevealTimer = window.setTimeout(() => {
    app.gameOverRevealTimer = null;
    app.gameOverRevealAt = null;
    render();
  }, remaining + 40);
}

function updateGameOverReveal(previousGameOver) {
  if (!app.gameOver) {
    app.gameOverRevealAt = null;
    clearGameOverRevealTimer();
    return;
  }

  if (previousGameOver) {
    scheduleGameOverRevealEnd();
    return;
  }

  const delay = isCheckmateResult() ? checkmateRevealDelayMs() : 0;
  app.gameOverRevealAt = delay > 0 ? performance.now() + delay : null;
  if (delay > 0) {
    // Score the reveal as it starts, so the rumble, the swallow and the
    // rupture land on their frames instead of arriving with the modal.
    playCheckmateRevealSound(app.humanSide !== null && app.turn !== app.humanSide);
  }
  scheduleGameOverRevealEnd();
}

function squareElement(square) {
  return refs.board.querySelector(`[data-square="${square}"]`);
}

function squareFromPoint(x, y) {
  const element = document.elementFromPoint(x, y)?.closest(".square");
  if (!element || !refs.board.contains(element)) {
    return null;
  }
  return element.dataset.square || null;
}

function boardSquareSize() {
  return refs.board.getBoundingClientRect().width / 8;
}

function clearDragHints() {
  refs.board.querySelectorAll(".drag-source, .drag-over, .selected, .legal, .capture").forEach((node) => {
    node.classList.remove("drag-source", "drag-over", "selected", "legal", "capture");
  });
}

function showGameDragHints(from) {
  clearDragHints();
  squareElement(from)?.classList.add("selected", "drag-source");
  const pieces = parseFenPieces(app.fen);
  const showCaptureHints = !canQueuePremove();
  for (const move of legalFrom(from)) {
    const target = move.slice(2, 4);
    const targetElement = squareElement(target);
    if (!targetElement) {
      continue;
    }
    targetElement.classList.add("legal");
    if (showCaptureHints && pieces[target]) {
      targetElement.classList.add("capture");
    }
  }
}

function updateDragOver(square) {
  refs.board.querySelectorAll(".drag-over").forEach((node) => node.classList.remove("drag-over"));
  if (square) {
    squareElement(square)?.classList.add("drag-over");
  }
}

function animationPieceForMove(uci, beforePieces, afterPieces) {
  if (!uci || uci.length < 4) {
    return null;
  }
  return afterPieces[uci.slice(2, 4)] || beforePieces[uci.slice(0, 2)] || null;
}

function createFloatingPiece(piece, className) {
  const node = document.createElement("div");
  node.className = `${className} ${pieceColor(piece)}`;
  decoratePieceNode(node, piece);
  node.style.setProperty("--piece-size", `${boardSquareSize()}px`);
  document.body.appendChild(node);
  return node;
}

function captureAbsorbTarget(capturerColour) {
  // The capturing engine's presence core on its player card — matched by
  // colour, so in watch mode each core is fed by its own side's captures —
  // with any visible presence or the side panel's header core as fallback.
  const cards = [
    [refs.bottomPlayerCard, refs.bottomPlayerPresence],
    [refs.topPlayerCard, refs.topPlayerPresence],
  ];
  const own = cards.find(([card, presence]) => (
    card?.dataset.colour === capturerColour
    && presence && !presence.hidden && presence.offsetParent !== null
  ));
  if (own) {
    return own[1];
  }
  const candidates = [refs.bottomPlayerPresence, refs.topPlayerPresence, refs.engineDot];
  return candidates.find((el) => el && !el.hidden && el.offsetParent !== null) || null;
}

function humanAbsorbTarget() {
  // The human's answer to the engine's presence core: their name plate on
  // whichever player card is theirs this game.
  const card = [refs.bottomPlayerCard, refs.topPlayerCard].find(
    (el) => el && el.classList.contains("human-side") && el.offsetParent !== null,
  );
  return card?.querySelector(".player-name") || card || null;
}

function capturedPieceForMove(uci, previousPieces) {
  if (!uci || uci.length < 4 || !previousPieces) {
    return null;
  }
  const from = uci.slice(0, 2);
  const to = uci.slice(2, 4);
  const direct = previousPieces[to];
  if (direct) {
    return { piece: direct, square: to };
  }
  // En passant: a pawn moved diagonally onto an empty square; the captured
  // pawn sits on the destination file at the origin rank.
  const mover = previousPieces[from];
  if (mover && mover.toLowerCase() === "p" && from[0] !== to[0]) {
    const epSquare = `${to[0]}${from[1]}`;
    const epPiece = previousPieces[epSquare];
    if (epPiece && epPiece.toLowerCase() === "p") {
      return { piece: epPiece, square: epSquare };
    }
  }
  return null;
}

// Captured pieces don't just vanish: they stream into the capturer. Sgurr's
// captures feed its presence core (the mate-devour motif, extended to
// ordinary captures); the human's captures stream into their own name plate.
// The in-place dissolve remains as a fallback when no target is laid out.
function triggerCaptureAbsorb(lastMove, previousPieces, { byHuman = false } = {}) {
  if (app.animationMode === "Off" || !lastMove?.uci) {
    return;
  }
  const captured = capturedPieceForMove(lastMove.uci, previousPieces);
  if (!captured) {
    return;
  }
  const mover = previousPieces[lastMove.uci.slice(0, 2)];
  const capturerColour = mover ? pieceColor(mover) : "white";

  // Lift off just as the capturing piece lands: a touch of overlap reads as
  // impact, where a gap after the landing reads as hesitation.
  const delay = Math.max(
    0,
    (byHuman ? humanMoveAnimationDurationMs() : moveAnimationDurationMs()) - 30,
  );
  window.setTimeout(() => {
    if (app.mode !== "game") {
      return;
    }
    const cell = squareElement(captured.square) || squareElement(lastMove.uci.slice(2, 4));
    if (!cell) {
      return;
    }
    const rect = cell.getBoundingClientRect();
    if (!rect.width) {
      return;
    }
    const node = createFloatingPiece(captured.piece, "capture-absorb-piece");
    node.style.left = `${rect.left + rect.width / 2}px`;
    node.style.top = `${rect.top + rect.height / 2}px`;
    const finish = () => node.remove();

    const target = byHuman ? humanAbsorbTarget() : captureAbsorbTarget(capturerColour);
    if (target) {
      const t = target.getBoundingClientRect();
      const dx = t.left + t.width / 2 - (rect.left + rect.width / 2);
      const dy = t.top + t.height / 2 - (rect.top + rect.height / 2);
      const anim = node.animate(
        [
          {
            transform: "translate(-50%, -50%) scale(1)",
            opacity: 0.96,
            filter: "drop-shadow(0 0 0 transparent)",
          },
          {
            transform: `translate(calc(-50% + ${dx * 0.55}px), calc(-50% + ${dy * 0.55 - 28}px)) scale(0.62)`,
            opacity: 0.92,
            filter: "drop-shadow(0 0 14px var(--accent))",
            offset: 0.62,
          },
          {
            transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(0.08)`,
            opacity: 0,
            filter: "drop-shadow(0 0 24px var(--accent))",
          },
        ],
        { duration: 460, easing: "cubic-bezier(0.5, 0, 0.2, 1)" },
      );
      // Fire the flash a beat before the piece fully vanishes so arrival and
      // impact read as one motion rather than two queued steps.
      const flashTarget = byHuman ? target.closest(".player-card") || target : target;
      const flashClass = byHuman ? "card-absorb-flash" : "core-absorb-flash";
      const flashTimer = window.setTimeout(() => {
        flashTarget.classList.add(flashClass);
        window.setTimeout(() => flashTarget.classList.remove(flashClass), 500);
      }, 380);
      anim.onfinish = finish;
      anim.oncancel = () => {
        window.clearTimeout(flashTimer);
        finish();
      };
    } else {
      const anim = node.animate(
        [
          {
            transform: "translate(-50%, -50%) scale(1)",
            opacity: 0.95,
            filter: "blur(0) saturate(1)",
          },
          {
            transform: "translate(-50%, -64%) scale(1.5)",
            opacity: 0,
            filter: "blur(8px) saturate(0.15)",
          },
        ],
        { duration: 360, easing: "ease-out" },
      );
      anim.onfinish = finish;
      anim.oncancel = finish;
    }
  }, delay);
}

function updateDragGhost(x, y) {
  if (!app.drag.ghost) {
    return;
  }
  app.drag.ghost.style.left = `${x}px`;
  app.drag.ghost.style.top = `${y}px`;
}

function cleanupDrag({ suppressClick = false } = {}) {
  if (app.drag.ghost) {
    app.drag.ghost.remove();
  }
  clearDragHints();
  app.drag.active = false;
  app.drag.pointerId = null;
  app.drag.mode = null;
  app.drag.from = null;
  app.drag.piece = null;
  app.drag.ghost = null;
  if (suppressClick) {
    app.drag.suppressClick = true;
    window.setTimeout(() => {
      app.drag.suppressClick = false;
    }, 40);
  }
}

function clearMoveAnimations() {
  app.pendingAnimation = null;
  app.activeAnimation = null;
  document.querySelectorAll(".move-ghost").forEach((node) => node.remove());
}

function beginDragCandidate(event, square, piece, mode) {
  app.drag.active = false;
  app.drag.pointerId = event.pointerId;
  app.drag.mode = mode;
  app.drag.from = square;
  app.drag.piece = piece;
  app.drag.startX = event.clientX;
  app.drag.startY = event.clientY;
  app.drag.x = event.clientX;
  app.drag.y = event.clientY;
  refs.board.setPointerCapture?.(event.pointerId);
}

function activateDrag() {
  if (app.drag.active || !app.drag.piece || !app.drag.from) {
    return;
  }
  app.drag.active = true;
  app.drag.ghost = createFloatingPiece(app.drag.piece, "drag-piece");
  updateDragGhost(app.drag.x, app.drag.y);

  if (app.drag.mode === "game") {
    showGameDragHints(app.drag.from);
  } else {
    clearDragHints();
    squareElement(app.drag.from)?.classList.add("drag-source");
  }
}

function handleBoardPointerDown(event, square, piece) {
  if (event.button !== 0) {
    return;
  }

  if (app.mode === "editor") {
    if (app.busy || app.thinking || !piece || app.editor.brush) {
      return;
    }
    beginDragCandidate(event, square, piece, "editor");
    return;
  }

  if (!boardInteractionAvailable() || !piece || pieceColor(piece) !== app.humanSide || !legalFrom(square).length) {
    return;
  }

  beginDragCandidate(event, square, piece, "game");
}

function handleBoardPointerMove(event) {
  if (app.drag.pointerId !== event.pointerId || !app.drag.piece) {
    return;
  }

  app.drag.x = event.clientX;
  app.drag.y = event.clientY;
  const distance = Math.hypot(event.clientX - app.drag.startX, event.clientY - app.drag.startY);
  if (!app.drag.active && distance >= 6) {
    activateDrag();
  }

  if (!app.drag.active) {
    return;
  }

  event.preventDefault();
  updateDragGhost(event.clientX, event.clientY);
  updateDragOver(squareFromPoint(event.clientX, event.clientY));
}

function finishEditorDrag(target) {
  const from = app.drag.from;
  const piece = app.drag.piece;
  if (!from || !piece) {
    return;
  }

  app.editor.pieces = clonePieces(app.editor.pieces);
  delete app.editor.pieces[from];
  if (target) {
    app.editor.pieces[target] = piece;
    app.editor.status = `${pieceLabel(piece)} moved to ${target}`;
  } else {
    app.editor.status = `${pieceLabel(piece)} deleted`;
  }
  app.editor.error = "";
}

function finishGameDrag(target) {
  const from = app.drag.from;
  if (!from) {
    return "none";
  }

  if (!target || target === from) {
    return "click-origin";
  }

  app.selected = null;

  if (!tryMove(from, target, { animate: false })) {
    return "illegal";
  }

  return "moved";
}

function handleBoardPointerUp(event) {
  if (app.drag.pointerId !== event.pointerId || !app.drag.piece) {
    return;
  }

  refs.board.releasePointerCapture?.(event.pointerId);
  if (!app.drag.active) {
    const from = app.drag.from;
    const mode = app.drag.mode;
    cleanupDrag({ suppressClick: true });
    if (from && (mode === "game" || mode === "editor")) {
      handleSquare(from);
    }
    return;
  }

  event.preventDefault();
  const target = squareFromPoint(event.clientX, event.clientY);
  const mode = app.drag.mode;
  const dragFrom = app.drag.from;
  let gameDragResult = "none";
  if (mode === "editor") {
    finishEditorDrag(target);
  } else if (mode === "game") {
    gameDragResult = finishGameDrag(target);
  }
  cleanupDrag({ suppressClick: true });

  if (gameDragResult === "click-origin") {
    handleSquare(dragFrom);
    return;
  }
  if (gameDragResult === "illegal") {
    playSound("illegal");
    app.selected = null;
    app.status = "Illegal move";
    app.error = "Illegal move";
    render();
    return;
  }

  if (mode === "editor") {
    render();
  }
}

function cancelDrag(event) {
  if (event && app.drag.pointerId !== event.pointerId) {
    return;
  }
  cleanupDrag({ suppressClick: Boolean(app.drag.active) });
}

function queueMoveAnimation(uci, piece, { animate = true, duration = moveAnimationDurationMs(), easing = null } = {}) {
  if (!animate || !uci || !piece || duration <= 0) {
    app.pendingAnimation = null;
    return;
  }
  app.pendingAnimation = { uci, piece, duration, easing };
}

function preparePendingMoveAnimation() {
  const pending = app.pendingAnimation;
  app.pendingAnimation = null;
  if (!pending || pending.duration <= 0) {
    app.activeAnimation = null;
    return null;
  }

  app.activeAnimation = {
    ...pending,
    from: pending.uci.slice(0, 2),
    to: pending.uci.slice(2, 4),
  };
  return app.activeAnimation;
}

function startActiveMoveAnimation() {
  const active = app.activeAnimation;
  if (!active || app.mode !== "game" || moveAnimationDurationMs() <= 0) {
    app.activeAnimation = null;
    return;
  }

  const fromElement = squareElement(active.from);
  const toElement = squareElement(active.to);
  if (!fromElement || !toElement) {
    app.activeAnimation = null;
    render();
    return;
  }

  const fromRect = fromElement.getBoundingClientRect();
  const toRect = toElement.getBoundingClientRect();
  const size = fromRect.width;
  const ghost = createFloatingPiece(active.piece, "move-ghost");
  const duration = active.duration || moveAnimationDurationMs();
  ghost.style.setProperty("--piece-size", `${size}px`);
  ghost.style.setProperty("--move-duration", `${duration}ms`);
  if (active.easing) {
    ghost.style.setProperty("--move-ease", active.easing);
  }
  ghost.style.transform = `translate(${fromRect.left}px, ${fromRect.top}px)`;

  requestAnimationFrame(() => {
    ghost.style.transform = `translate(${toRect.left}px, ${toRect.top}px)`;
  });
  window.setTimeout(() => {
    ghost.remove();
    if (app.activeAnimation === active) {
      app.activeAnimation = null;
      render();
    }
  }, duration + 80);
}

function appendBoardCoords(cell, square) {
  const orientation = boardOrientation();
  const file = square[0];
  const rank = square[1];
  const leftFile = orientation === "white" ? "a" : "h";
  const bottomRank = orientation === "white" ? "1" : "8";

  if (file === leftFile) {
    const rankLabel = document.createElement("span");
    rankLabel.className = "coord rank";
    rankLabel.textContent = rank;
    cell.appendChild(rankLabel);
  }

  if (rank === bottomRank) {
    const fileLabel = document.createElement("span");
    fileLabel.className = "coord file";
    fileLabel.textContent = file;
    cell.appendChild(fileLabel);
  }
}

function renderBoard() {
  const editing = app.mode === "editor";
  const reviewing = app.review.active;
  const reviewFen = reviewing ? reviewCurrent()?.fen : null;
  const pieces = editing
    ? app.editor.pieces
    : reviewFen
      ? parseFenPieces(reviewFen)
      : projectPremovePieces(parseFenPieces(app.fen));
  const gameDragFrom =
    !editing && app.drag.active && app.drag.mode === "game" ? app.drag.from : null;
  const editorDragFrom =
    editing && app.drag.active && app.drag.mode === "editor" ? app.drag.from : null;
  const hintFrom = gameDragFrom || app.selected;
  const targets = !editing && hintFrom ? legalTargets(hintFrom) : new Set();
  const premoving = !editing && canQueuePremove();
  const last = editing ? new Set() : lastMoveSquares();
  // app.inCheck and the mate reveal describe the final position, so they must
  // not be painted onto an earlier one while reviewing.
  const checkedKing =
    !editing && !reviewing && app.inCheck ? kingSquare(pieces, app.turn) : null;
  const matedKing =
    !reviewing && checkmateRevealPending() ? kingSquare(pieces, app.turn) : null;

  refs.board.innerHTML = "";
  refs.board.classList.toggle("editor-mode", editing);
  refs.board.classList.toggle("animations-off", app.animationMode === "Off");
  refs.board.classList.toggle("premove-mode", premoving);
  for (const square of orientedSquares()) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = `square ${squareIsLight(square) ? "light" : "dark"}`;
    cell.dataset.square = square;
    cell.setAttribute("role", "gridcell");
    cell.setAttribute("aria-label", square);

    const piece = pieces[square];
    const isOwnPiece = piece && pieceColor(piece) === app.humanSide;
    const canSelect = !editing && boardInteractionAvailable() && isOwnPiece && legalFrom(square).length > 0;
    const hideForAnimation =
      !editing && app.activeAnimation && app.activeAnimation.to === square && piece === app.activeAnimation.piece;
    const hideForDrag =
      Boolean(gameDragFrom && square === gameDragFrom) ||
      Boolean(editorDragFrom && square === editorDragFrom);

    if (last.has(square)) {
      cell.classList.add("last");
    }
    if (!editing && (app.selected === square || gameDragFrom === square)) {
      cell.classList.add("selected");
    }
    if (gameDragFrom === square || editorDragFrom === square) {
      cell.classList.add("drag-source");
    }
    if (editing && (app.editor.heldFrom === square || editorDragFrom === square)) {
      cell.classList.add("held");
    }
    if (targets.has(square)) {
      cell.classList.add("legal");
      cell.classList.toggle("premove-legal", premoving);
      if (piece) {
        cell.classList.add("capture");
      }
    }
    if (!editing && app.premoves.some((premove) => premove.from === square)) {
      cell.classList.add("premove-source");
    }
    if (!editing && app.premoves.some((premove) => premove.to === square)) {
      cell.classList.add("premove-target");
    }
    if (checkedKing === square) {
      cell.classList.add("king-check");
    }
    if (matedKing === square) {
      cell.classList.add("king-mated");
    }
    if (editing || canSelect || (hintFrom && targets.has(square))) {
      cell.classList.add("playable");
    }

    appendBoardCoords(cell, square);

    if (piece && !hideForAnimation && !hideForDrag && matedKing !== square) {
      const pieceNode = document.createElement("span");
      pieceNode.className = `piece ${pieceColor(piece)}`;
      decoratePieceNode(pieceNode, piece);
      cell.appendChild(pieceNode);
    }

    cell.addEventListener("pointerdown", (event) => handleBoardPointerDown(event, square, piece));
    cell.addEventListener("click", () => {
      if (app.drag.suppressClick) {
        return;
      }
      handleSquare(square);
    });
    cell.addEventListener("contextmenu", (event) => {
      if (app.mode === "game") {
        event.preventDefault();
        if (hasPremoves()) {
          cancelPremoves();
        }
        return;
      }
      if (app.mode !== "editor") {
        return;
      }
      event.preventDefault();
      handleEditorDelete(square);
    });
    refs.board.appendChild(cell);
  }
}

function showPromotion(from, to, legalPromotions, { animate = true, premove = false } = {}) {
  refs.promotionChoices.innerHTML = "";
  const legalLetters = new Set(legalPromotions.map((move) => move[4]));
  const promotingPiece = projectPremovePieces(parseFenPieces(app.fen))[from];
  const promotionColour = promotingPiece ? pieceColor(promotingPiece) : app.turn;

  app.status = "Choose a promotion piece";
  app.error = "";
  app.selected = from;
  render();

  for (const promotion of PROMOTIONS) {
    if (!legalLetters.has(promotion.letter)) {
      continue;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("aria-label", `Promote to ${promotion.label}`);
    const icon = document.createElement("span");
    const piece = pieceForColour(promotion.piece, promotionColour);
    icon.className = `promo-piece ${pieceColor(piece)}`;
    decoratePieceNode(icon, piece);
    const label = document.createElement("span");
    label.className = "promo-label";
    label.textContent = promotion.label;
    button.append(icon, label);
    button.addEventListener("click", () => {
      hidePromotion();
      if (premove) {
        queuePremove(`${from}${to}${promotion.letter}`);
      } else {
        makePlayerMove(`${from}${to}${promotion.letter}`, { animate });
      }
    });
    refs.promotionChoices.appendChild(button);
  }

  refs.promotionBackdrop.hidden = false;
  positionPromotionDialog();
  window.requestAnimationFrame(positionPromotionDialog);
}

function hidePromotion() {
  refs.promotionBackdrop.hidden = true;
  refs.promotionChoices.innerHTML = "";
  refs.promotionDialog.style.removeProperty("--promotion-left");
  refs.promotionDialog.style.removeProperty("--promotion-top");
  refs.promotionDialog.style.removeProperty("--promotion-width");
}

function cancelPromotion() {
  hidePromotion();
  app.selected = null;
  app.error = "";
  if (!app.gameOver && app.mode === "game" && humanCanMove()) {
    app.status = "Your move";
  } else if (!app.gameOver && app.mode === "game" && canQueuePremove()) {
    app.status = "Sgurr is thinking";
  }
  render();
}

function positionPromotionDialog() {
  if (refs.promotionBackdrop.hidden) {
    return;
  }

  const boardRect = refs.board.getBoundingClientRect();
  const viewportPadding = 14;
  const maxWidth = Math.max(252, window.innerWidth - viewportPadding * 2);
  const width = Math.min(352, Math.max(308, boardRect.width - 40), maxWidth);
  refs.promotionDialog.style.setProperty("--promotion-width", `${width}px`);

  const dialogRect = refs.promotionDialog.getBoundingClientRect();
  const halfWidth = dialogRect.width / 2;
  const halfHeight = dialogRect.height / 2;
  const x = clampNumber(
    boardRect.left + boardRect.width / 2,
    viewportPadding + halfWidth,
    window.innerWidth - viewportPadding - halfWidth,
  );
  const y = clampNumber(
    boardRect.top + boardRect.height / 2,
    viewportPadding + halfHeight,
    window.innerHeight - viewportPadding - halfHeight,
  );

  refs.promotionDialog.style.setProperty("--promotion-left", `${x}px`);
  refs.promotionDialog.style.setProperty("--promotion-top", `${y}px`);
}

export {
  hasPremoves,
  clearPremoveQueueState,
  applyProjectedPremove,
  projectPremovePieces,
  materialFromPieces,
  boardOrientation,
  orientedSquares,
  squareIsLight,
  humanCanMove,
  canQueuePremove,
  boardInteractionAvailable,
  engineTurnAvailable,
  engineToMove,
  legalFrom,
  legalTargets,
  lastMoveSquares,
  kingSquare,
  squareCenterPercent,
  renderCheckmateEffect,
  moveAnimationDurationMs,
  humanMoveAnimationDurationMs,
  checkmateRevealDelayMs,
  isCheckmateResult,
  checkmateRevealPending,
  clearGameOverRevealTimer,
  scheduleGameOverRevealEnd,
  updateGameOverReveal,
  squareElement,
  squareFromPoint,
  boardSquareSize,
  clearDragHints,
  showGameDragHints,
  updateDragOver,
  animationPieceForMove,
  createFloatingPiece,
  captureAbsorbTarget,
  humanAbsorbTarget,
  capturedPieceForMove,
  triggerCaptureAbsorb,
  updateDragGhost,
  cleanupDrag,
  clearMoveAnimations,
  beginDragCandidate,
  activateDrag,
  handleBoardPointerDown,
  handleBoardPointerMove,
  finishEditorDrag,
  finishGameDrag,
  handleBoardPointerUp,
  cancelDrag,
  queueMoveAnimation,
  preparePendingMoveAnimation,
  startActiveMoveAnimation,
  appendBoardCoords,
  renderBoard,
  showPromotion,
  hidePromotion,
  cancelPromotion,
  positionPromotionDialog,
};
