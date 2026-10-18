/** Excel error values arrive as these strings in `range.values`. */
export const ERROR_VALUES = new Set([
  "#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#N/A", "#NULL!", "#NUM!", "#SPILL!",
  "#CALC!", "#GETTING_DATA", "#BLOCKED!", "#CONNECT!", "#FIELD!", "#UNKNOWN!",
]);

export function isErrorValue(v) {
  return typeof v === "string" && ERROR_VALUES.has(v);
}

/** Cell text for display. An error cell shows its error, like the grid does. */
export function cellText(v) {
  if (v === null || v === undefined) return "";
  return String(v);
}

/** Cell number, or null when the cell is blank, text or an error. */
export function cellNumber(v) {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  return null;
}

/**
 * Trims the "Item # " boilerplate off an item cell.
 *
 * Estimate sheets often carry `Item # 66`; the repeated prefix is noise in a
 * narrow pane. Conservative in two ways, both deliberate: "Item" counts as a
 * prefix only when a delimiter follows it, so "Itemized bid" survives intact;
 * and a value that would reduce to nothing ("Item #", "#") keeps its original
 * text, because a blank is worse than a redundant one where a bid item number
 * belongs.
 */
export function itemLabel(s) {
  const original = String(s ?? "").trim();
  if (!original) return "";

  // "#REF!" is an Excel error, not an item number with a # prefix. Stripping
  // it yields "REF!" -- an error that no longer looks like one, in the column
  // where a broken reference most needs to be obvious.
  if (isErrorValue(original.toUpperCase())) return original;

  let t = original;
  if (t.length >= 4 && t.slice(0, 4).toLowerCase() === "item") {
    const rest = t.slice(4);
    if (rest.length === 0) return original;
    if (" #.:-".includes(rest[0])) t = rest.trim();
  }
  if (t.startsWith("#")) t = t.slice(1).trim();

  return t.length ? t : original;
}

/** True for a bare single-cell A1 address: letters then digits, nothing else. */
export function isSingleCellA1(addr) {
  return /^[A-Za-z]{1,3}[0-9]{1,7}$/.test(addr);
}

export function hasAnyChar(s, chars) {
  for (const c of chars) if (s.includes(c)) return true;
  return false;
}

/** Characters Excel would have quoted, so their presence unquoted means
 *  this is an expression rather than a sheet name. */
export const EXPRESSION_CHARS = "+-*/(),[] ";

/**
 * Parses a plain single-cell reference to another sheet in this workbook,
 * e.g. ='SP soldier piles'!$G$107 -> {sheet, addr}. Returns null for
 * expressions, ranges and external workbook references.
 *
 * Hand-rolled rather than a regex. Excel forbids \ / ? * [ ] : in sheet
 * names but allows !, and always quotes a name that holds one. An address
 * never contains !, so the LAST ! is the separator, and a ! left in an
 * unquoted sheet part means an expression. `addr` keeps its $ signs.
 */
export function tryParseRef(formula) {
  let f = String(formula ?? "").trim();
  if (f.length < 4) return null;
  if (f[0] !== "=") return null;
  f = f.slice(1).trim();

  const p = f.lastIndexOf("!");
  if (p < 0) return null;

  let sheetPart = f.slice(0, p);
  const addrPart = f.slice(p + 1);
  if (!sheetPart.length || !addrPart.length) return null;

  if (sheetPart[0] === "'") {
    if (sheetPart.length < 3) return null;
    if (sheetPart[sheetPart.length - 1] !== "'") return null;
    sheetPart = sheetPart.slice(1, -1).replaceAll("''", "'");
    // An external reference survives quoting; a sheet name cannot hold [.
    if (sheetPart.includes("[")) return null;
  } else if (hasAnyChar(sheetPart, EXPRESSION_CHARS) || sheetPart.includes("!")) {
    return null;
  }

  if (!sheetPart.length) return null;
  if (!isSingleCellA1(addrPart.replaceAll("$", ""))) return null;

  return { sheet: sheetPart, addr: addrPart };
}

/** Column letter(s) -> 0-based index (A=0, E=4, AA=26). */
export function colIndex(letter) {
  let n = 0;
  for (const ch of String(letter)) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n - 1;
}

/** 0-based index -> column letters (0=A, 26=AA). */
export function colLetter(index) {
  let n = index + 1, s = "";
  while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
  return s;
}
