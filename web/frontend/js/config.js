function parseApiBase(value) {
  const text = String(value || "").trim();
  if (!text) {
    return null;
  }
  if (text.toLowerCase() === "same-origin") {
    return "";
  }

  try {
    const url = new URL(text, window.location.origin);
    if (!['http:', 'https:'].includes(url.protocol)) {
      return null;
    }
    return url.href.replace(/\/+$/, "");
  } catch {
    return null;
  }
}

function defaultApiBase() {
  const localHosts = new Set(["127.0.0.1", "localhost", "::1"]);
  if (
    window.location.protocol === "file:"
    || (localHosts.has(window.location.hostname) && window.location.port !== "8000")
  ) {
    return "http://127.0.0.1:8000";
  }
  return "";
}

const configuredApiBase = parseApiBase(
  new URLSearchParams(window.location.search).get("api")
  || document.querySelector('meta[name="sgurr-api-base"]')?.content
  || window.localStorage.getItem("sgurrApiBase"),
);
const API_BASE = configuredApiBase === null ? defaultApiBase() : configuredApiBase;

function apiUrl(path) {
  return API_BASE ? new URL(path, `${API_BASE}/`).href : path;
}

function apiBaseLabel() {
  return API_BASE || window.location.origin;
}

const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];
const PIECES = {
  P: "\u265f",
  N: "\u265e",
  B: "\u265d",
  R: "\u265c",
  Q: "\u265b",
  K: "\u265a",
  p: "\u265f",
  n: "\u265e",
  b: "\u265d",
  r: "\u265c",
  q: "\u265b",
  k: "\u265a",
};
const CAPTURED_PIECE_CODES = {
  pawn: "p",
  knight: "n",
  bishop: "b",
  rook: "r",
  queen: "q",
};
const PROMOTIONS = [
  { letter: "q", label: "Queen", piece: "q" },
  { letter: "r", label: "Rook", piece: "r" },
  { letter: "b", label: "Bishop", piece: "b" },
  { letter: "n", label: "Knight", piece: "n" },
];
const CORE_THINKING_LINES = [
  "Listening to the position...",
  "Condensing candidate lines...",
  "Reading king pressure...",
  "Following forcing lines...",
  "Measuring material gravity...",
  "Move crystallising...",
];
const CORE_THINKING_LINE_MS = 5200;
const CORE_LINE_FADE_MS = 420;
const CORE_DIALOGUE_COOLDOWN_PLIES = 3;
const CORE_DIALOGUE_LINES = {
  engineMove: [
    "A quiet improvement.",
    "The square accepts me.",
    "Another small lock.",
    "The map narrows.",
    "This line has weight.",
  ],
  engineCapture: [
    "Material shifts.",
    "I keep what falls.",
    "A piece leaves the board.",
    "The balance changes shape.",
  ],
  humanCapture: [
    "Material removed.",
    "A useful wound.",
    "Noted.",
    "The shell records the loss.",
  ],
  engineCheck: [
    "Your king is visible.",
    "Pressure arrives.",
    "The safe squares thin out.",
    "Your king has a shadow.",
  ],
  humanCheck: [
    "Pressure detected.",
    "The shell holds.",
    "You found a bright square.",
    "A direct signal.",
  ],
  engineSwing: [
    "The position tilts.",
    "A door has opened.",
    "The board leans my way.",
    "Your structure loosens.",
  ],
  humanSwing: [
    "The signal wavers.",
    "You bent the line.",
    "That changed the air.",
    "The position resists me.",
  ],
  mateThreat: [
    "A forced ending is forming.",
    "The route is almost closed.",
    "The king has fewer names.",
  ],
  sgurrWin: [
    "The board goes quiet.",
    "Your king has no horizon.",
    "The last square is gone.",
  ],
  humanWin: [
    "Signal lost.",
    "Core fracture.",
    "I did not see that line.",
  ],
  draw: [
    "No further signal.",
    "Balance restored.",
    "The board refuses.",
  ],
};

const OPENING_BOOK = [
  {
    key: "sicilian_najdorf",
    name: "Sicilian Defence: Najdorf",
    moves: ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "a7a6"],
    line: "The Najdorf. Every square has teeth.",
  },
  {
    key: "sicilian_dragon",
    name: "Sicilian Defence: Dragon",
    moves: ["e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "g7g6"],
    line: "The Dragon wakes. The long diagonal burns.",
  },
  { key: "sicilian", name: "Sicilian Defence", moves: ["e2e4", "c7c5"], line: "The Sicilian. The board divides early." },
  { key: "french", name: "French Defence", moves: ["e2e4", "e7e6"], line: "The French chain closes around the centre." },
  { key: "caro_kann", name: "Caro-Kann Defence", moves: ["e2e4", "c7c6"], line: "Caro-Kann. A patient shell." },
  { key: "scandinavian", name: "Scandinavian Defence", moves: ["e2e4", "d7d5"], line: "Immediate contact. The Scandinavian is awake." },
  {
    key: "pirc",
    name: "Pirc Defence",
    moves: ["e2e4", "d7d6", "d2d4", "g8f6", "b1c3", "g7g6"],
    line: "The centre advances. I will watch it from the dark.",
  },
  { key: "italian", name: "Italian Game", moves: ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4"], line: "The Italian paths are old, but not quiet." },
  { key: "ruy_lopez", name: "Ruy Lopez", moves: ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"], line: "The Spanish bishop asks its ancient question." },
  { key: "scotch", name: "Scotch Game", moves: ["e2e4", "e7e5", "g1f3", "b8c6", "d2d4"], line: "The centre opens before either side is ready." },
  { key: "petrov", name: "Petrov Defence", moves: ["e2e4", "e7e5", "g1f3", "g8f6"], line: "A mirror in the centre. Petrov." },
  { key: "open_game", name: "Open Game", moves: ["e2e4", "e7e5"], line: "An open game. We have walked this road before." },
  { key: "queens_gambit", name: "Queen's Gambit", moves: ["d2d4", "d7d5", "c2c4"], line: "The c-pawn is offered. The centre remembers." },
  { key: "slav", name: "Slav Defence", moves: ["d2d4", "d7d5", "c2c4", "c7c6"], line: "The Slav structure settles into stone." },
  { key: "london", name: "London System", moves: ["d2d4", "d7d5", "c1f4"], line: "A familiar London shell takes shape." },
  { key: "kings_indian", name: "King's Indian Defence", moves: ["d2d4", "g8f6", "c2c4", "g7g6"], line: "The King's Indian waits, then strikes." },
  { key: "nimzo_indian", name: "Nimzo-Indian Defence", moves: ["d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4"], line: "The knight is pinned. The Nimzo web begins." },
  { key: "grunfeld", name: "Grunfeld Defence", moves: ["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "d7d5"], line: "Take the centre. The Grunfeld will attack it later." },
  { key: "dutch", name: "Dutch Defence", moves: ["d2d4", "f7f5"], line: "The Dutch wing moves before the centre settles." },
  { key: "english", name: "English Opening", moves: ["c2c4"], line: "The English begins from the flank." },
  { key: "reti", name: "Reti Opening", moves: ["g1f3"], line: "A Reti signal. The centre remains undefined." },
  { key: "queens_pawn", name: "Queen's Pawn Game", moves: ["d2d4"], line: "The queen's pawn claims its space." },
  { key: "kings_pawn", name: "King's Pawn Game", moves: ["e2e4"], line: "The king's pawn opens the first gate." },
];

const EDIT_PALETTE = ["K", "Q", "R", "B", "N", "P", "k", "q", "r", "b", "n", "p"];
const CHECKMATE_DRILLS = [
  { key: "queen", label: "K+Q vs K", pieces: ["Q"] },
  { key: "rook", label: "K+R vs K", pieces: ["R"] },
  { key: "two_rooks", label: "K+2R vs K", pieces: ["R", "R"] },
  { key: "two_bishops", label: "K+2B vs K", pieces: ["B", "B"] },
  { key: "bishop_knight", label: "K+B+N vs K", pieces: ["B", "N"] },
];
const ODDS_PRESETS = [
  { key: "queen", label: "Queen odds", squares: ["d1"] },
  { key: "rook", label: "Rook odds", squares: ["a1"] },
  { key: "knight", label: "Knight odds", squares: ["b1"] },
  { key: "bishop", label: "Bishop odds", squares: ["c1"] },
  { key: "two_pawns", label: "Two-pawn odds", squares: ["c2", "f2"] },
];
const EDIT_RETURN_SIDES = ["white", "black", null];
const ODDS_RECIPIENTS = ["you", "engine"];
const ANIMATION_MODES = ["Off", "On"];
const INTRO_WAKE_DURATION_MS = 1650;
const INTRO_NAME_DURATION_MS = 3600;
const INTRO_BLACKOUT_DURATION_MS = 1350;
const INTRO_HANDOFF_DURATION_MS = 1000;
const INTRO_REVEAL_DURATION_MS = 1500;
const SOUND_FILES = {
  clock_warning: "clock-warning.ogg",
  clock_flag: "clock-flag.ogg",
  result_human_explosion: "result-human-splat.ogg",
  result_human_victory: "result-human-victory.ogg",
  result_sgurr_energy: "result-sgurr-energy.ogg",
  result_sgurr_alien: "result-sgurr-alien.ogg",
  result_sgurr_burble: "result-sgurr-burble.ogg",
  result_draw: "result-draw-neutral.ogg",
};
const PROCEDURAL_SOUND_NAMES = new Set([
  "button",
  "move_self",
  "move_opponent",
  "capture",
  "castle",
  "promote",
  "check",
  "illegal",
  "game_start",
  "game_end",
  "boss_rumble",
  "boss_reveal",
]);

const TIME_CONTROLS = [
  { key: "bullet_1_0", label: "Bullet 1+0", baseSeconds: 60, incrementSeconds: 0 },
  { key: "bullet_2_1", label: "Bullet 2+1", baseSeconds: 120, incrementSeconds: 1 },
  { key: "blitz_3_0", label: "Blitz 3+0", baseSeconds: 180, incrementSeconds: 0 },
  { key: "blitz_3_2", label: "Blitz 3+2", baseSeconds: 180, incrementSeconds: 2 },
  { key: "blitz_5_0", label: "Blitz 5+0", baseSeconds: 300, incrementSeconds: 0 },
  { key: "rapid_10_0", label: "Rapid 10+0", baseSeconds: 600, incrementSeconds: 0 },
  { key: "rapid_15_10", label: "Rapid 15+10", baseSeconds: 900, incrementSeconds: 10 },
  { key: "classical_90_30", label: "Classical 90+30", baseSeconds: 5400, incrementSeconds: 30 },
];

const THEMES = {
  neon: {
    label: "Neon Dark",
    vars: {
      "--bg": "#0c0f15",
      "--surface": "#141820",
      "--surface-2": "#1b212c",
      "--surface-3": "#273141",
      "--edge": "#30394a",
      "--text": "#eff4fc",
      "--muted": "#94a1bb",
      "--accent": "#36cae2",
      "--accent-2": "#cc6cef",
      "--board-light": "#46587c",
      "--board-dark": "#2b3752",
      "--white-eval": "#edf3fb",
      "--black-eval": "#1f2531",
      "--piece-white": "#f2f6fc",
      "--piece-black": "#171c26",
      "--piece-white-edge": "#0d1118",
      "--piece-black-edge": "#53b1c5",
      "--last-move": "rgba(54, 202, 226, 0.4)",
      "--selected": "rgba(204, 108, 239, 0.46)",
      "--legal": "rgba(239, 244, 252, 0.34)",
      "--danger": "#ee6266",
    },
  },
  modern: {
    label: "Modern Dark",
    vars: {
      "--bg": "#161916",
      "--surface": "#1f231f",
      "--surface-2": "#2b302a",
      "--surface-3": "#3a4338",
      "--edge": "#4c5549",
      "--text": "#f4f6f0",
      "--muted": "#aeb7a8",
      "--accent": "#568fe2",
      "--accent-2": "#5db05d",
      "--board-light": "#eef1db",
      "--board-dark": "#528042",
      "--white-eval": "#f7f9f3",
      "--black-eval": "#222722",
      "--piece-white": "#fdfdf8",
      "--piece-black": "#171c18",
      "--piece-white-edge": "#232823",
      "--piece-black-edge": "#e1e7da",
      "--last-move": "rgba(244, 224, 105, 0.5)",
      "--selected": "rgba(86, 143, 226, 0.52)",
      "--legal": "rgba(18, 24, 18, 0.34)",
      "--danger": "#ee6266",
    },
  },
  wood: {
    label: "Classic Wood",
    vars: {
      "--bg": "#251a16",
      "--surface": "#33241d",
      "--surface-2": "#432f25",
      "--surface-3": "#5a3d2d",
      "--edge": "#76523d",
      "--text": "#fcf2e0",
      "--muted": "#d3bb9d",
      "--accent": "#e2b147",
      "--accent-2": "#c96f3a",
      "--board-light": "#f5d8aa",
      "--board-dark": "#975e39",
      "--white-eval": "#fcf4e5",
      "--black-eval": "#33241d",
      "--piece-white": "#fff8e9",
      "--piece-black": "#261914",
      "--piece-white-edge": "#482d1d",
      "--piece-black-edge": "#ebcfa8",
      "--last-move": "rgba(220, 178, 91, 0.58)",
      "--selected": "rgba(188, 126, 195, 0.52)",
      "--legal": "rgba(23, 25, 29, 0.38)",
      "--danger": "#ee6266",
    },
  },
  highland: {
    label: "Highland Heather",
    vars: {
      "--bg": "#1c1720",
      "--surface": "#261f2b",
      "--surface-2": "#332c39",
      "--surface-3": "#413746",
      "--edge": "#5b4e62",
      "--text": "#f7f0e2",
      "--muted": "#bcb1ad",
      "--accent": "#bc7ec3",
      "--accent-2": "#dcb25b",
      "--board-light": "#b4bea4",
      "--board-dark": "#4c5b46",
      "--white-eval": "#f7f1e3",
      "--black-eval": "#302835",
      "--piece-white": "#faf4e6",
      "--piece-black": "#231c27",
      "--piece-white-edge": "#403442",
      "--piece-black-edge": "#e1cdb0",
      "--last-move": "rgba(220, 178, 91, 0.55)",
      "--selected": "rgba(188, 126, 195, 0.56)",
      "--legal": "rgba(23, 25, 29, 0.36)",
      "--danger": "#ee6266",
    },
  },
  ocean: {
    label: "Deep Ocean",
    vars: {
      "--bg": "#081b26",
      "--surface": "#0e2632",
      "--surface-2": "#163543",
      "--surface-3": "#214c5a",
      "--edge": "#365e6c",
      "--text": "#e8f6f6",
      "--muted": "#8bb0b5",
      "--accent": "#30c9bc",
      "--accent-2": "#f79268",
      "--board-light": "#9dc2c4",
      "--board-dark": "#265b6a",
      "--white-eval": "#e8f6f4",
      "--black-eval": "#14303c",
      "--piece-white": "#f1f6eb",
      "--piece-black": "#0b2731",
      "--piece-white-edge": "#1e454c",
      "--piece-black-edge": "#84e0d6",
      "--last-move": "rgba(48, 201, 188, 0.44)",
      "--selected": "rgba(247, 146, 104, 0.5)",
      "--legal": "rgba(8, 27, 38, 0.36)",
      "--danger": "#ee6266",
    },
  },
  frost: {
    label: "Nordic Frost",
    vars: {
      "--bg": "#819197",
      "--surface": "#aab7ba",
      "--surface-2": "#99a9ad",
      "--surface-3": "#83999f",
      "--edge": "#506870",
      "--text": "#142329",
      "--muted": "#3c535b",
      "--accent": "#176f7d",
      "--accent-2": "#a85138",
      "--board-light": "#bbc7c4",
      "--board-dark": "#4e6b72",
      "--white-eval": "#d2dad8",
      "--black-eval": "#354b52",
      "--piece-white": "#ecece4",
      "--piece-black": "#17282e",
      "--piece-white-edge": "#354b51",
      "--piece-black-edge": "#d5e0de",
      "--last-move": "rgba(23, 111, 125, 0.46)",
      "--selected": "rgba(168, 81, 56, 0.5)",
      "--legal": "rgba(20, 35, 41, 0.36)",
      "--danger": "#982f37",
    },
  },
  galaxy: {
    label: "Galaxy",
    vars: {
      "--bg": "#090b1c",
      "--surface": "#111428",
      "--surface-2": "#191d38",
      "--surface-3": "#262b4f",
      "--edge": "#3b4170",
      "--text": "#eef0ff",
      "--muted": "#9aa1c9",
      "--accent": "#a07bf5",
      "--accent-2": "#4ecbe8",
      "--board-light": "#525a92",
      "--board-dark": "#282d55",
      "--white-eval": "#eef0fb",
      "--black-eval": "#1c2039",
      "--piece-white": "#f3f4ff",
      "--piece-black": "#141830",
      "--piece-white-edge": "#101430",
      "--piece-black-edge": "#8b93e8",
      "--last-move": "rgba(78, 203, 232, 0.4)",
      "--selected": "rgba(160, 123, 245, 0.5)",
      "--legal": "rgba(238, 240, 255, 0.32)",
      "--danger": "#ee6266",
    },
  },
};
const THEME_ORDER = ["neon", "modern", "wood", "highland", "ocean", "frost", "galaxy"];
const savedTheme = localStorage.getItem("sgurrTheme");
const initialTheme = THEME_ORDER.includes(savedTheme) ? savedTheme : "wood";

export {
  parseApiBase,
  defaultApiBase,
  configuredApiBase,
  API_BASE,
  apiUrl,
  apiBaseLabel,
  START_FEN,
  FILES,
  PIECES,
  CAPTURED_PIECE_CODES,
  PROMOTIONS,
  CORE_THINKING_LINES,
  CORE_THINKING_LINE_MS,
  CORE_LINE_FADE_MS,
  CORE_DIALOGUE_COOLDOWN_PLIES,
  CORE_DIALOGUE_LINES,
  OPENING_BOOK,
  EDIT_PALETTE,
  CHECKMATE_DRILLS,
  ODDS_PRESETS,
  EDIT_RETURN_SIDES,
  ODDS_RECIPIENTS,
  ANIMATION_MODES,
  INTRO_WAKE_DURATION_MS,
  INTRO_NAME_DURATION_MS,
  INTRO_BLACKOUT_DURATION_MS,
  INTRO_HANDOFF_DURATION_MS,
  INTRO_REVEAL_DURATION_MS,
  SOUND_FILES,
  PROCEDURAL_SOUND_NAMES,
  TIME_CONTROLS,
  THEMES,
  THEME_ORDER,
  savedTheme,
  initialTheme,
};
