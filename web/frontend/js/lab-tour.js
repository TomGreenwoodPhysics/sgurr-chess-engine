const clamp = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, value));

function seen(storageKey) {
  try {
    return localStorage.getItem(storageKey) === "1";
  } catch {
    return false;
  }
}

function remember(storageKey) {
  try {
    localStorage.setItem(storageKey, "1");
  } catch {
    // Storage is optional.
  }
}

function controlsIn(card) {
  return [...card.querySelectorAll("button:not([disabled])")].filter((button) => button.offsetParent !== null);
}

function elements(name) {
  const get = (suffix) => document.querySelector(`#${name}${suffix}`);
  return {
    trigger: get("TutorialButton"),
    tour: get("Tour"),
    focus: get("TourFocus"),
    arrow: get("TourArrow"),
    card: get("TourCard"),
    count: get("TourCount"),
    kicker: get("TourKicker"),
    title: get("TourTitle"),
    text: get("TourText"),
    progress: get("TourProgress"),
    skip: get("TourSkip"),
    back: get("TourBack"),
    next: get("TourNext"),
  };
}

export function initLabTour({ name, storageKey, steps, prepare = null, mobileBreakpoint = 620 }) {
  const refs = elements(name);
  let index = 0;
  let active = false;
  let previousFocus = null;
  let currentTarget = null;
  let layoutFrame = 0;

  refs.progress.style.setProperty("--lab-tour-steps", String(steps.length));

  function markProgress() {
    const dots = steps.map((_, dotIndex) => {
      const dot = document.createElement("i");
      if (dotIndex === index) dot.dataset.current = "true";
      if (dotIndex < index) dot.dataset.complete = "true";
      return dot;
    });
    refs.progress.replaceChildren(...dots);
  }

  function edgePoint(rect, towardsX, towardsY) {
    const centreX = rect.left + rect.width / 2;
    const centreY = rect.top + rect.height / 2;
    const dx = towardsX - centreX;
    const dy = towardsY - centreY;
    if (Math.abs(dx) < 0.01 && Math.abs(dy) < 0.01) return { x: centreX, y: centreY };
    const scaleX = Math.abs(dx) > 0.01 ? rect.width / 2 / Math.abs(dx) : Infinity;
    const scaleY = Math.abs(dy) > 0.01 ? rect.height / 2 / Math.abs(dy) : Infinity;
    const scale = Math.min(scaleX, scaleY);
    return { x: centreX + dx * scale, y: centreY + dy * scale };
  }

  function placeArrow(targetRect, cardRect) {
    const targetCentre = {
      x: targetRect.left + targetRect.width / 2,
      y: targetRect.top + targetRect.height / 2,
    };
    const cardCentre = {
      x: cardRect.left + cardRect.width / 2,
      y: cardRect.top + cardRect.height / 2,
    };
    const start = edgePoint(cardRect, targetCentre.x, targetCentre.y);
    const end = edgePoint(targetRect, cardCentre.x, cardCentre.y);
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const length = Math.hypot(dx, dy);
    refs.arrow.style.left = `${start.x}px`;
    refs.arrow.style.top = `${start.y}px`;
    refs.arrow.style.width = `${Math.max(0, length)}px`;
    refs.arrow.style.transform = `rotate(${Math.atan2(dy, dx)}rad)`;
    refs.arrow.hidden = length < 18;
  }

  function cardPosition(targetRect, cardRect, preferred) {
    const margin = 14;
    const gap = 28;
    const candidates = {
      right: { left: targetRect.right + gap, top: targetRect.top + (targetRect.height - cardRect.height) / 2 },
      left: { left: targetRect.left - cardRect.width - gap, top: targetRect.top + (targetRect.height - cardRect.height) / 2 },
      bottom: { left: targetRect.left + (targetRect.width - cardRect.width) / 2, top: targetRect.bottom + gap },
      top: { left: targetRect.left + (targetRect.width - cardRect.width) / 2, top: targetRect.top - cardRect.height - gap },
    };
    const order = [preferred, "right", "left", "bottom", "top"].filter((side, position, all) => all.indexOf(side) === position);
    const fits = ({ left, top }) => (
      left >= margin && top >= margin
      && left + cardRect.width <= window.innerWidth - margin
      && top + cardRect.height <= window.innerHeight - margin
    );
    const chosen = order.map((side) => candidates[side]).find(fits) || candidates[preferred];
    return {
      left: clamp(chosen.left, margin, Math.max(margin, window.innerWidth - cardRect.width - margin)),
      top: clamp(chosen.top, margin, Math.max(margin, window.innerHeight - cardRect.height - margin)),
    };
  }

  function placeStep() {
    if (!active || !currentTarget) return;
    const targetRect = currentTarget.getBoundingClientRect();
    const padding = 8;
    refs.focus.style.left = `${targetRect.left - padding}px`;
    refs.focus.style.top = `${targetRect.top - padding}px`;
    refs.focus.style.width = `${targetRect.width + padding * 2}px`;
    refs.focus.style.height = `${targetRect.height + padding * 2}px`;

    refs.card.style.left = "0px";
    refs.card.style.top = "0px";
    const cardRect = refs.card.getBoundingClientRect();
    const position = window.innerWidth <= mobileBreakpoint
      ? { left: 12, top: window.innerHeight - cardRect.height - 12 }
      : cardPosition(targetRect, cardRect, steps[index].placement);
    refs.card.style.left = `${position.left}px`;
    refs.card.style.top = `${Math.max(12, position.top)}px`;
    placeArrow(targetRect, refs.card.getBoundingClientRect());
  }

  function queueLayout() {
    cancelAnimationFrame(layoutFrame);
    layoutFrame = requestAnimationFrame(placeStep);
  }

  function showStep(nextIndex, { focusButton = false } = {}) {
    index = clamp(nextIndex, 0, steps.length - 1);
    const step = steps[index];
    currentTarget = document.querySelector(step.selector);
    if (!currentTarget) return;
    refs.tour.dataset.step = String(index);
    refs.tour.dataset.target = step.key;
    refs.count.textContent = `${index + 1} of ${steps.length}`;
    refs.kicker.textContent = step.kicker;
    refs.title.textContent = step.title;
    refs.text.textContent = step.text;
    refs.back.disabled = index === 0;
    refs.next.textContent = index === steps.length - 1 ? "Finish" : "Next";
    markProgress();
    currentTarget.scrollIntoView({ block: "center", inline: "nearest", behavior: "auto" });
    requestAnimationFrame(() => requestAnimationFrame(queueLayout));
    if (focusButton) refs.next.focus({ preventScroll: true });
  }

  function close() {
    if (!active) return;
    remember(storageKey);
    active = false;
    cancelAnimationFrame(layoutFrame);
    refs.tour.hidden = true;
    refs.arrow.hidden = false;
    window.removeEventListener("resize", queueLayout);
    window.removeEventListener("scroll", queueLayout, true);
    const restore = previousFocus instanceof HTMLElement && previousFocus.isConnected
      ? previousFocus
      : refs.trigger;
    restore?.focus({ preventScroll: true });
  }

  function start() {
    if (active) return;
    prepare?.();
    previousFocus = document.activeElement;
    active = true;
    refs.tour.hidden = false;
    window.addEventListener("resize", queueLayout);
    window.addEventListener("scroll", queueLayout, true);
    showStep(0, { focusButton: true });
  }

  function advance() {
    if (index === steps.length - 1) close();
    else showStep(index + 1, { focusButton: true });
  }

  refs.trigger.addEventListener("click", start);
  refs.skip.addEventListener("click", close);
  refs.back.addEventListener("click", () => showStep(index - 1, { focusButton: true }));
  refs.next.addEventListener("click", advance);
  refs.tour.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      advance();
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      showStep(index - 1, { focusButton: true });
      return;
    }
    if (event.key !== "Tab") return;
    const buttons = controlsIn(refs.card);
    const first = buttons[0];
    const last = buttons.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  return {
    maybeStart() {
      if (!seen(storageKey)) start();
    },
    start,
    close,
  };
}
