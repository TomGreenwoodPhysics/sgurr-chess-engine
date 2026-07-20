import { FILES, START_FEN } from "./config.js";

function title(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

function clampNumber(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function fenPositionKey(fen) {
  return String(fen || "")
    .trim()
    .split(/\s+/)
    .slice(0, 4)
    .join(" ");
}

function clonePieces(pieces) {
  return { ...pieces };
}

function fenTurn(fen) {
  return fen.split(" ")[1] === "b" ? "black" : "white";
}

function startingPieces() {
  return parseFenPieces(START_FEN);
}

function pieceForColour(piece, colour) {
  return colour === "white" ? piece.toUpperCase() : piece.toLowerCase();
}

function pieceLabel(piece) {
  const colour = pieceColor(piece);
  const names = {
    k: "king",
    q: "queen",
    r: "rook",
    b: "bishop",
    n: "knight",
    p: "pawn",
  };
  return `${title(colour)} ${names[piece.toLowerCase()]}`;
}

function pieceAssetPath(piece) {
  const colour = piece === piece.toUpperCase() ? "w" : "b";
  return `assets/pieces/chessnut/${colour}${piece.toUpperCase()}.svg`;
}

function decoratePieceNode(node, piece) {
  node.dataset.piece = piece;
  node.setAttribute("aria-label", pieceLabel(piece));
  const image = document.createElement("img");
  image.className = "piece-image";
  image.src = pieceAssetPath(piece);
  image.alt = "";
  image.draggable = false;
  node.replaceChildren(image);
}

function piecesToBoardFen(pieces) {
  const rows = [];
  for (let rank = 8; rank >= 1; rank -= 1) {
    let row = "";
    let empty = 0;
    for (const file of FILES) {
      const piece = pieces[`${file}${rank}`];
      if (piece) {
        if (empty) {
          row += String(empty);
          empty = 0;
        }
        row += piece;
      } else {
        empty += 1;
      }
    }
    if (empty) {
      row += String(empty);
    }
    rows.push(row);
  }
  return rows.join("/");
}

function formatNodesShort(value) {
  if (value >= 1e6) {
    return `${(value / 1e6).toFixed(1)}M`;
  }
  if (value >= 1e3) {
    return `${Math.round(value / 1e3)}k`;
  }
  return String(Math.round(value));
}

// Live search readout while Sgurr thinks. The backend answers with the final
// depth/nodes only, so the ticking values are extrapolated from the previous
// search's speed (nodes from measured NPS; depth from iterative-deepening
// growth, ~2.2x time per ply) and snap to the real figures on arrival.
function formatClock(seconds) {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const wholeSeconds = Math.floor(safe % 60);
  const tenths = Math.floor((safe % 1) * 10);

  if (safe < 10 && safe > 0) {
    return `${minutes}:${String(wholeSeconds).padStart(2, "0")}.${tenths}`;
  }

  return `${minutes}:${String(wholeSeconds).padStart(2, "0")}`;
}

function pieceColor(piece) {
  return piece === piece.toUpperCase() ? "white" : "black";
}

function parseFenPieces(fen) {
  const placement = fen.split(" ")[0];
  const rows = placement.split("/");
  const pieces = {};

  rows.forEach((row, rowIndex) => {
    let fileIndex = 0;
    const rank = 8 - rowIndex;
    for (const char of row) {
      if (/\d/.test(char)) {
        fileIndex += Number(char);
      } else {
        pieces[`${FILES[fileIndex]}${rank}`] = char;
        fileIndex += 1;
      }
    }
  });

  return pieces;
}

export {
  title,
  clampNumber,
  fenPositionKey,
  clonePieces,
  fenTurn,
  startingPieces,
  pieceForColour,
  pieceLabel,
  pieceAssetPath,
  decoratePieceNode,
  piecesToBoardFen,
  formatNodesShort,
  formatClock,
  pieceColor,
  parseFenPieces,
};
