import { initAudio, playSound, syncGameMusic, syncMenuMusic } from "./audio.js";
import { copyAnalysisFen, selectAnalysisDepth, selectAnalysisPly, startPositionAnalysis, stepAnalysisPly, stopPositionAnalysis } from "./analysis.js";
import { cancelDrag, cancelPromotion, handleBoardPointerMove, handleBoardPointerUp, hasPremoves, positionPromotionDialog } from "./board.js";
import { currentTimeControl, syncClock } from "./clocks.js";
import { ANIMATION_MODES, TIME_CONTROLS } from "./config.js";
import { initDemoTooltips } from "./demo-tooltip.js";
import { analyseEditorPosition, clearEditorBoard, copyEditorFen, cycleEditorOddsRecipient, cycleEditorPlayer, cycleEditorTurn, enterBoardEditor, exitBoardEditor, finishBoardEditor, finishEditorPrimaryAction, loadEditorStartPosition, loadFenIntoEditor } from "./editor.js";
import { cycleEngine, fetchEngines, refreshHealth, renderEngineGallery } from "./engine.js";
import { cancelPremoves, copyFen, exportPgn, redoPly, rematchGame, returnToMainMenu, scheduleWatchMove, startGame, toggleFocusMode, triggerEngineMove, undoMove, undoPly } from "./game.js";
import { finishIntro, initIntro, wakeSgurr } from "./intro.js";
import { initMenuCore } from "./menu-core.js";
import { defaultBlobMemory } from "./memory.js";
import { enterReview, exitReview, reviewEntries, reviewGoto, reviewIndexForPly, reviewStep, reviewSwing } from "./review.js";
import { app, refs } from "./state.js";
import { applyAnimationMode, applyTheme, closeAllModals, cycleTheme, cycleTime, openModal, renderSettings, saveSettings } from "./themes.js";
import { render, renderClockUi } from "./ui.js";

refs.introCoreTrigger.addEventListener("click", wakeSgurr);
refs.wakeSgurrButton.addEventListener("click", wakeSgurr);
refs.playWhiteButton.addEventListener("click", () => startGame("white"));
refs.playBlackButton.addEventListener("click", () => startGame("black"));
refs.watchButton.addEventListener("click", () => {
  if (app.publicDemo) {
    app.menuMessage = "Self-play is available locally; continuous play is disabled on the free demo.";
    render();
    return;
  }
  startGame(null);
});
refs.timeDownButton.addEventListener("click", () => cycleTime(-1));
refs.timeUpButton.addEventListener("click", () => cycleTime(1));
refs.menuTimeButton.addEventListener("click", () => openModal(refs.timeModal));
refs.themeDownButton.addEventListener("click", () => cycleTheme(-1));
refs.themeUpButton.addEventListener("click", () => cycleTheme(1));
refs.menuThemeButton.addEventListener("click", () => openModal(refs.themeModal));
refs.engineDownButton.addEventListener("click", () => cycleEngine(-1));
refs.engineUpButton.addEventListener("click", () => cycleEngine(1));
refs.menuEngineButton.addEventListener("click", () => {
  renderEngineGallery();
  openModal(refs.engineModal);
});
refs.menuSettingsButton.addEventListener("click", () => openModal(refs.settingsModal));
refs.menuHelpButton.addEventListener("click", () => openModal(refs.helpModal));
refs.analysePositionButton.addEventListener("click", () => enterBoardEditor("analysis"));
refs.boardEditorButton.addEventListener("click", () => enterBoardEditor("play"));
refs.focusModeButton.addEventListener("click", () => toggleFocusMode());
refs.newGameButton.addEventListener("click", () => startGame(app.humanSide));
refs.undoMoveButton.addEventListener("click", undoMove);
refs.redoMoveButton.addEventListener("click", redoPly);
refs.engineNowButton.addEventListener("click", triggerEngineMove);
refs.copyFenButton.addEventListener("click", copyFen);
refs.exportPgnButton.addEventListener("click", exportPgn);
refs.sideSettingsButton.addEventListener("click", () => openModal(refs.settingsModal));
refs.sideHelpButton.addEventListener("click", () => openModal(refs.helpModal));
refs.mainMenuButton.addEventListener("click", returnToMainMenu);
refs.rematchButton.addEventListener("click", rematchGame);
refs.resultMenuButton.addEventListener("click", returnToMainMenu);
refs.editorPlayerButton.addEventListener("click", cycleEditorPlayer);
refs.editorTurnButton.addEventListener("click", cycleEditorTurn);
refs.editorPlayButton.addEventListener("click", finishBoardEditor);
refs.editorAnalyseButton.addEventListener("click", analyseEditorPosition);
refs.editorLoadFenButton.addEventListener("click", loadFenIntoEditor);
refs.editorOddsRecipientButton.addEventListener("click", cycleEditorOddsRecipient);
refs.editorStartButton.addEventListener("click", loadEditorStartPosition);
refs.editorCopyFenButton.addEventListener("click", copyEditorFen);
refs.editorClearButton.addEventListener("click", clearEditorBoard);
refs.editorCancelButton.addEventListener("click", () => exitBoardEditor());
refs.editorMainMenuButton.addEventListener("click", returnToMainMenu);
refs.editorSettingsButton.addEventListener("click", () => openModal(refs.settingsModal));
refs.editorHelpButton.addEventListener("click", () => openModal(refs.helpModal));
refs.analysisStopButton.addEventListener("click", () => stopPositionAnalysis());
refs.analysisAgainButton.addEventListener("click", () => startPositionAnalysis(
  app.analysis.sourceFen,
  { orientation: app.analysis.orientation },
));
refs.analysisEditButton.addEventListener("click", () => {
  const fen = app.analysis.sourceFen;
  app.editor.returnSide = app.analysis.orientation;
  stopPositionAnalysis({ updateStatus: false });
  enterBoardEditor("analysis", fen);
});
refs.analysisCopyFenButton.addEventListener("click", copyAnalysisFen);
refs.analysisMenuButton.addEventListener("click", () => {
  stopPositionAnalysis({ updateStatus: false });
  returnToMainMenu();
});
refs.analysisPrevPlyButton.addEventListener("click", () => stepAnalysisPly(-1));
refs.analysisRootButton.addEventListener("click", () => selectAnalysisPly(0));
refs.analysisNextPlyButton.addEventListener("click", () => stepAnalysisPly(1));
refs.analysisPvMoves.addEventListener("click", (event) => {
  const button = event.target instanceof Element ? event.target.closest("button[data-ply]") : null;
  if (button) {
    selectAnalysisPly(Number(button.dataset.ply));
  }
});
refs.analysisDepths.addEventListener("click", (event) => {
  const button = event.target instanceof Element ? event.target.closest("button[data-depth]") : null;
  if (button) {
    selectAnalysisDepth(Number(button.dataset.depth));
  }
});
refs.pauseWatchButton.addEventListener("click", () => {
  if (app.humanSide !== null) {
    return;
  }
  syncClock();
  app.watchPaused = !app.watchPaused;
  app.clockLastTick = performance.now();
  if (!app.watchPaused) {
    scheduleWatchMove(100);
  }
  render();
});
refs.movetimeSelect.addEventListener("change", () => {
  const value = refs.movetimeSelect.value;
  const index = TIME_CONTROLS.findIndex((control) => control.key === value);
  if (index >= 0) {
    app.timeIndex = index;
    localStorage.setItem("sgurrTimeIndex", String(app.timeIndex));
  }
  render();
});
refs.autoFlipInput.addEventListener("change", () => {
  app.autoFlipAsBlack = refs.autoFlipInput.checked;
  saveSettings();
  render();
});
refs.showEngineInfoInput.addEventListener("change", () => {
  app.showEngineInfo = refs.showEngineInfoInput.checked;
  saveSettings();
  render();
});
refs.animationModeSelect.addEventListener("change", () => {
  app.animationMode = ANIMATION_MODES.includes(refs.animationModeSelect.value)
    ? refs.animationModeSelect.value
    : "On";
  saveSettings();
  render();
});
refs.soundEnabledInput.addEventListener("change", () => {
  app.soundEnabled = refs.soundEnabledInput.checked;
  saveSettings();
  if (app.soundEnabled) {
    playSound("button", { volume: 1.1 });
  }
  render();
});
refs.soundVolumeInput.addEventListener("input", () => {
  app.soundVolume = Math.max(0, Math.min(1, Number(refs.soundVolumeInput.value)));
  saveSettings();
  renderSettings();
});
refs.musicEnabledInput.addEventListener("change", () => {
  app.musicEnabled = refs.musicEnabledInput.checked;
  saveSettings();
  syncMenuMusic({ force: true });
  renderSettings();
});
refs.musicVolumeInput.addEventListener("input", () => {
  app.musicVolume = Math.max(0, Math.min(1, Number(refs.musicVolumeInput.value)));
  saveSettings();
  syncMenuMusic({ force: true });
  renderSettings();
});
refs.gameMusicEnabledInput.addEventListener("change", () => {
  app.gameMusicEnabled = refs.gameMusicEnabledInput.checked;
  saveSettings();
  syncGameMusic({ force: true });
  renderSettings();
});
refs.gameMusicVolumeInput.addEventListener("input", () => {
  app.gameMusicVolume = Math.max(0, Math.min(1, Number(refs.gameMusicVolumeInput.value)));
  saveSettings();
  syncGameMusic({ force: true });
  renderSettings();
});
refs.clearPreferencesButton.addEventListener("click", () => {
  localStorage.removeItem("sgurrTheme");
  localStorage.removeItem("sgurrTimeIndex");
  localStorage.removeItem("sgurrAutoFlip");
  localStorage.removeItem("sgurrShowEngineInfo");
  localStorage.removeItem("sgurrAnimationMode");
  localStorage.removeItem("sgurrSoundEnabled");
  localStorage.removeItem("sgurrSoundVolume");
  localStorage.removeItem("sgurrMusicEnabled");
  localStorage.removeItem("sgurrMusicVolume");
  localStorage.removeItem("sgurrGameMusicEnabled");
  localStorage.removeItem("sgurrGameMusicVolume");
  app.themeKey = "wood";
  app.timeIndex = 2;
  app.autoFlipAsBlack = true;
  app.showEngineInfo = true;
  app.animationMode = "On";
  app.soundEnabled = true;
  app.soundVolume = 0.8;
  app.musicEnabled = true;
  app.musicVolume = 0.2;
  app.gameMusicEnabled = true;
  app.gameMusicVolume = 0.35;
  applyTheme();
  saveSettings();
  render();
});
refs.clearMemoryButton.addEventListener("click", () => {
  app.memory = defaultBlobMemory();
  app.memoryRecorded = false;
  localStorage.removeItem("sgurrBlobMemory");
  render();
});
document.querySelectorAll("[data-close-modal]").forEach((button) => {
  button.addEventListener("click", closeAllModals);
});
document.querySelectorAll(".modal-backdrop").forEach((modal) => {
  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      closeAllModals();
    }
  });
});
refs.promotionBackdrop.addEventListener("click", (event) => {
  if (event.target === refs.promotionBackdrop) {
    cancelPromotion();
  }
});
refs.board.addEventListener("pointermove", handleBoardPointerMove);
refs.board.addEventListener("pointerup", handleBoardPointerUp);
refs.board.addEventListener("pointercancel", cancelDrag);
window.addEventListener("resize", positionPromotionDialog);
document.addEventListener("visibilitychange", () => {
  const hidden = document.hidden;
  syncMenuMusic({ force: true, immediate: hidden });
  syncGameMusic({ force: true, immediate: hidden });
});
document.addEventListener("click", (event) => {
  const button = event.target instanceof Element ? event.target.closest("button") : null;
  if (
    !button
    || button.disabled
    || button.getAttribute("aria-disabled") === "true"
    || button.classList.contains("square")
    || button.dataset.sound === "none"
  ) {
    return;
  }
  playSound("button", { volume: 1.1 });
});

// --- Post-game review -------------------------------------------------
function openReview() {
  if (enterReview()) {
    closeAllModals();
  }
  render();
}

function leaveReview() {
  exitReview();
  render();
}

function stepReview(direction) {
  reviewStep(direction);
  render();
}

refs.reviewGameButton.addEventListener("click", openReview);
refs.reviewExitButton.addEventListener("click", leaveReview);
refs.reviewPrevButton.addEventListener("click", () => stepReview(-1));
refs.reviewNextButton.addEventListener("click", () => stepReview(1));
refs.reviewStartButton.addEventListener("click", () => {
  reviewGoto(0);
  render();
});
refs.reviewEndButton.addEventListener("click", () => {
  reviewGoto(reviewEntries().length - 1);
  render();
});
refs.reviewScrub.addEventListener("input", () => {
  reviewGoto(Number(refs.reviewScrub.value));
  render();
});
refs.reviewSwingButton.addEventListener("click", () => {
  const swing = reviewSwing();
  if (swing) {
    reviewGoto(reviewIndexForPly(swing.ply));
    render();
  }
});

function overlayIsOpen() {
  return (
    !refs.promotionBackdrop.hidden ||
    [
      refs.themeModal,
      refs.timeModal,
      refs.engineModal,
      refs.settingsModal,
      refs.helpModal,
    ].some((modal) => !modal.hidden)
  );
}

window.addEventListener("keydown", (event) => {
  const target = event.target;
  if (!app.intro.complete) {
    if ((event.key === "Enter" || event.key === " ") && !app.intro.waking) {
      event.preventDefault();
      wakeSgurr();
    }
    return;
  }
  if (
    event.key !== "Escape" &&
    target instanceof HTMLElement &&
    target.matches("input, textarea, select")
  ) {
    return;
  }

  if (event.key === "Escape") {
    if (app.review.active && !overlayIsOpen()) {
      leaveReview();
    } else if (app.mode === "game" && hasPremoves() && !overlayIsOpen()) {
      cancelPremoves();
    } else if (app.mode === "game" && app.focusMode && !overlayIsOpen()) {
      toggleFocusMode(false);
    } else if (app.mode === "editor" && !overlayIsOpen()) {
      exitBoardEditor();
    } else if (app.mode === "analysis" && !overlayIsOpen()) {
      stopPositionAnalysis({ updateStatus: false });
      returnToMainMenu();
    } else {
      closeAllModals();
      if (!refs.promotionBackdrop.hidden) {
        cancelPromotion();
      } else {
        render();
      }
    }
  } else if (event.key.toLowerCase() === "r" && app.mode === "game") {
    startGame(app.humanSide);
  } else if (event.key === "Enter" && app.mode === "editor") {
    finishEditorPrimaryAction();
  } else if (event.key.toLowerCase() === "u" && app.mode === "game") {
    undoMove();
  } else if (event.key === "ArrowLeft" && app.mode === "game") {
    // While reviewing, the arrows walk the record instead of taking back
    // plies -- the game is over, there is nothing to take back.
    if (app.review.active) {
      stepReview(-1);
    } else {
      undoPly();
    }
  } else if (event.key === "ArrowRight" && app.mode === "game") {
    if (app.review.active) {
      stepReview(1);
    } else {
      redoPly();
    }
  } else if (event.key === "Home" && app.review.active) {
    reviewGoto(0);
    render();
  } else if (event.key === "End" && app.review.active) {
    reviewGoto(reviewEntries().length - 1);
    render();
  } else if (event.key.toLowerCase() === "g" && app.mode === "game") {
    triggerEngineMove();
  } else if (event.key.toLowerCase() === "c" && app.mode === "game") {
    copyFen();
  } else if (event.key.toLowerCase() === "p" && app.mode === "game") {
    exportPgn();
  } else if (event.key === " " && app.humanSide === null && app.mode === "game") {
    event.preventDefault();
    refs.pauseWatchButton.click();
  } else if (event.key.toLowerCase() === "t") {
    cycleTheme(1);
  } else if (event.key.toLowerCase() === "e" && app.mode !== "editor") {
    enterBoardEditor("play");
  } else if (event.key.toLowerCase() === "l") {
    enterBoardEditor("play");
    window.requestAnimationFrame(() => refs.editorFenInput.focus());
  } else if (event.key.toLowerCase() === "z" && app.mode === "game") {
    toggleFocusMode();
  } else if (event.key.toLowerCase() === "f" && ["game", "editor", "analysis"].includes(app.mode)) {
    app.manualFlip = !app.manualFlip;
    render();
  } else if (event.key === "?" || event.key === "F1") {
    event.preventDefault();
    openModal(refs.helpModal);
  }
});

initAudio();
initDemoTooltips();
applyTheme();
applyAnimationMode();
initIntro();
if (new URLSearchParams(window.location.search).get("view") === "menu") {
  finishIntro();
}
initMenuCore();
refs.movetimeSelect.value = currentTimeControl().key;
render();
refreshHealth();
fetchEngines();
setInterval(refreshHealth, 4000);
setInterval(() => {
  if (app.mode === "game") {
    renderClockUi();
  }
}, 200);
