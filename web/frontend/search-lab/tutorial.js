import { initLabTour } from "../js/lab-tour.js";

const STEPS = Object.freeze([
  {
    key: "modes",
    selector: ".mode-tabs",
    placement: "bottom",
    kicker: "Start here",
    title: "Three ways to watch the search",
    text: "Search network shows individual positions. Live engine shows completed depths. Guided walkthrough explains a recorded search one step at a time.",
  },
  {
    key: "position",
    selector: ".position-panel",
    placement: "right",
    kicker: "Starting position",
    title: "Every search begins here",
    text: "This is the position Sgurr must solve. Choose a preset or paste a FEN to change the board and the side to move.",
  },
  {
    key: "setup",
    selector: "#livePositionControls",
    placement: "right",
    kicker: "Search settings",
    title: "Choose depth, then run Sgurr",
    text: "A live run draws nodes as they arrive. A recorded run can be replayed afterwards. Higher depth means looking farther ahead and can take much longer.",
  },
  {
    key: "network",
    selector: ".network-canvas-wrap",
    placement: "left",
    kicker: "The search network",
    title: "Each point is a position",
    text: "The root position sits in the centre. A line is a move, and each ring is one move farther into the future. Drag to move around and scroll to zoom.",
  },
  {
    key: "stats",
    selector: ".network-stats",
    placement: "bottom",
    kicker: "Work done",
    title: "How far the search has reached",
    text: "Depth is the completed search horizon. Nodes searched counts all work, while visible nodes keeps the diagram readable. Cutoffs are branches Sgurr proved it could stop exploring.",
  },
  {
    key: "best",
    selector: ".network-best",
    placement: "right",
    kicker: "Current leader",
    title: "The best move can change",
    text: "This shows the root move currently in front and its score. A deeper reply can overturn it, so early leaders are only provisional.",
  },
  {
    key: "legend",
    selector: ".network-legend",
    placement: "top",
    kicker: "Reading the map",
    title: "Colour marks what happened",
    text: "The bright route is the main line. A cutoff ends a branch early. A transposition joins routes that reach the same position. Quiescence continues forcing moves at the edge.",
  },
  {
    key: "event",
    selector: ".network-event",
    placement: "top",
    kicker: "Search log",
    title: "Why the picture just changed",
    text: "This note names the latest search event and explains it in context, so the animation is not just decoration.",
  },
  {
    key: "controls",
    selector: ".network-controls",
    placement: "top",
    kicker: "Replay",
    title: "Inspect the search at your pace",
    text: "After a recorded run, play it back, change the speed or drag the timeline. Restart returns to the beginning without running the engine again.",
  },
]);

export function initSearchTutorial(prepare) {
  return initLabTour({
    name: "search",
    storageKey: "sgurrSearchTutorialSeen",
    steps: STEPS,
    prepare,
    mobileBreakpoint: 540,
  });
}
