/** Tiny DOM helpers. Text always goes in through textContent, never innerHTML. */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function replace(root, ...children) {
  root.replaceChildren(...children.flat().filter(Boolean));
}

/**
 * replace(), keeping keyboard focus across the re-render: if focus was on an
 * element with a `data-focus-key` inside `root`, the new element with the same
 * key gets it back, caret included for a text input.
 */
export function replaceKeepingFocus(root, ...children) {
  const el = document.activeElement;
  const key = el && el !== root && root.contains(el) && el.getAttribute ? el.getAttribute("data-focus-key") : null;
  const caret = key && typeof el.selectionStart === "number" ? [el.selectionStart, el.selectionEnd] : null;
  replace(root, ...children);
  if (!key) return;
  const next = [...root.querySelectorAll("[data-focus-key]")].find((e) => e.getAttribute("data-focus-key") === key);
  if (!next) return;
  next.focus({ preventScroll: true });
  if (caret && typeof next.setSelectionRange === "function") next.setSelectionRange(caret[0], caret[1]);
}

export const icon = {
  ok: () => h("span", { class: "ok", "aria-hidden": "true" }, "✓"),
  bad: () => h("span", { class: "bad", "aria-hidden": "true" }, "✗"),
  warn: () => h("span", { class: "warn", "aria-hidden": "true" }, "!"),
};
