const TOOLTIP_ID = "demoTooltip";

function setDemoReason(element, reason) {
  if (!element) return;
  if (reason) {
    element.dataset.demoReason = reason;
    element.setAttribute("aria-describedby", TOOLTIP_ID);
  } else {
    delete element.dataset.demoReason;
    if (element.getAttribute("aria-describedby") === TOOLTIP_ID) {
      element.removeAttribute("aria-describedby");
    }
  }
}

function initDemoTooltips() {
  let tooltip = document.querySelector(`#${TOOLTIP_ID}`);
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = TOOLTIP_ID;
    tooltip.className = "demo-tooltip";
    tooltip.setAttribute("role", "tooltip");
    tooltip.hidden = true;
    document.body.appendChild(tooltip);
  }

  function hide() {
    tooltip.hidden = true;
  }

  function show(target, x, y) {
    const reason = target?.dataset.demoReason;
    if (!reason) {
      hide();
      return;
    }
    tooltip.textContent = reason;
    tooltip.hidden = false;
    const gap = 14;
    const bounds = tooltip.getBoundingClientRect();
    tooltip.style.left = `${Math.max(8, Math.min(x + gap, innerWidth - bounds.width - 8))}px`;
    tooltip.style.top = `${Math.max(8, Math.min(y + gap, innerHeight - bounds.height - 8))}px`;
  }

  document.addEventListener("pointermove", (event) => {
    if (event.pointerType === "touch") return;
    const hit = document.elementFromPoint(event.clientX, event.clientY);
    const target = hit instanceof Element ? hit.closest("[data-demo-reason]") : null;
    show(target, event.clientX, event.clientY);
  });
  document.addEventListener("pointerleave", hide);
  document.addEventListener("focusin", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-demo-reason]") : null;
    if (!target) return;
    const bounds = target.getBoundingClientRect();
    show(target, bounds.right, bounds.top);
  });
  document.addEventListener("focusout", hide);
  window.addEventListener("blur", hide);
}

export { initDemoTooltips, setDemoReason };
