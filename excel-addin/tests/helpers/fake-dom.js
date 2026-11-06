/**
 * Just enough DOM for panes/view.js and the pane renderers under node --test:
 * elements, text nodes, attributes and listeners. Not a browser: no layout,
 * no CSS, no selectors beyond what replaceKeepingFocus asks for.
 */
class FakeNode {}

class FakeText extends FakeNode {
  constructor(text) { super(); this.data = String(text); }
  get textContent() { return this.data; }
}

export class FakeElement extends FakeNode {
  constructor(tag) {
    super();
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.listeners = {};
    this.className = "";
    this.disabled = false;
    this.value = "";
  }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "disabled") this.disabled = true; }
  getAttribute(k) { return Object.hasOwn(this.attrs, k) ? this.attrs[k] : null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  contains(n) { return n === this || this.children.some((c) => c instanceof FakeElement && c.contains(n)); }
  querySelectorAll() { return this.findAll((e) => e.getAttribute("data-focus-key") !== null); }
  focus() { globalThis.document.activeElement = this; }
  get textContent() { return this.children.map((c) => c.textContent).join(""); }
  set textContent(t) { this.children = [new FakeText(t)]; }
  /** Every element below this one, depth first, that `pred` accepts. */
  findAll(pred) {
    const out = [];
    const walk = (e) => {
      for (const c of e.children) {
        if (!(c instanceof FakeElement)) continue;
        if (pred(c)) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  /** Calls this element's listeners for `type`; returns what the last one returned (a promise for an async handler). */
  fire(type, event = {}) {
    let out;
    for (const fn of this.listeners[type] || []) out = fn({ preventDefault() {}, ...event });
    return out;
  }
}

/** Installs globalThis.document and globalThis.Node; returns a fresh root element. */
export function installFakeDom() {
  globalThis.Node = FakeNode;
  globalThis.document = {
    activeElement: null,
    createElement: (tag) => new FakeElement(tag),
    createTextNode: (text) => new FakeText(text),
  };
  return new FakeElement("main");
}
