/**
 * The change-set (bimforge-changes/1): what differs between the bundle the
 * workbook loaded (the hidden origin sheets) and what the sheets say now.
 * Pure: rows in, operations out. `est-bim apply-changes` writes the result
 * into the IFC; nothing here touches a file.
 *
 * Only what a sheet can honestly express becomes an operation: a property
 * value that changed, a property added on a row someone typed, a value
 * blanked (remove_property), a renamed element. A GlobalId is never edited,
 * so a row with a GlobalId the origin lacks is reported, not applied, and a
 * quantity is never diffed.
 */
export const CONTRACT = "bimforge-changes/1";

const key = (p) => `${p.global_id}\u0000${p.pset}\u0000${p.property}`;
const same = (a, b) => a === b || (typeof a === "number" && typeof b === "number" && Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a)));

/**
 * Property operations. `origin` and `current` are bundle property records
 * ({global_id, pset, property, value, value_type}); `known` is the set of
 * GlobalIds the bundle has (elements and types). Returns {ops, problems}.
 */
export function diffProperties(origin, current, known) {
  const before = new Map(origin.map((p) => [key(p), p]));
  const after = new Map(current.map((p) => [key(p), p]));
  const ops = [], problems = [];
  for (const [k, p] of after) {
    if (known && !known.has(p.global_id)) { problems.push(`${p.global_id}: not an object of the loaded bundle (${p.pset}.${p.property})`); continue; }
    const o = before.get(k);
    if (o && same(o.value, p.value) && (o.value_type || null) === (p.value_type || null)) continue;
    if (p.value === null) {
      if (o && o.value !== null) ops.push({ op: "remove_property", global_id: p.global_id, pset: p.pset, property: p.property });
      continue;
    }
    ops.push({ op: "set_property", global_id: p.global_id, pset: p.pset, property: p.property,
               value: p.value, value_type: p.value_type || (o && o.value_type) || null });
  }
  for (const [k, o] of before) {
    if (!after.has(k) && o.value !== null) {
      ops.push({ op: "remove_property", global_id: o.global_id, pset: o.pset, property: o.property });
    }
  }
  return { ops, problems };
}

/** set_name operations for elements whose Name cell changed. */
export function diffNames(origin, current) {
  const before = new Map(origin.map((e) => [e.global_id, e.name ?? ""]));
  const ops = [];
  for (const e of current) {
    if (before.has(e.global_id) && before.get(e.global_id) !== (e.name ?? "")) {
      ops.push({ op: "set_name", global_id: e.global_id, value: e.name === "" ? null : e.name });
    }
  }
  return ops;
}

/** Operations grouped the way a reviewer reads them: [{title, count, ops}]. */
export function plan(ops) {
  const groups = new Map();
  for (const op of ops) {
    const title = op.op === "set_name" ? "Rename"
      : op.op === "remove_property" ? `Remove ${op.pset}.${op.property}`
      : `Set ${op.pset}.${op.property}`;
    if (!groups.has(title)) groups.set(title, []);
    groups.get(title).push(op);
  }
  return [...groups].map(([title, list]) => ({ title, count: list.length, ops: list }))
    .sort((a, b) => b.count - a.count || a.title.localeCompare(b.title));
}

/** The change-set document for `ops` against the bundle `stamp` (bundle.js parseStamp). */
export function changeSet(stamp, ops) {
  return { contract: CONTRACT, source: { file: stamp ? stamp.file : null, schema: stamp ? stamp.schema : null,
                                         generator: stamp ? stamp.generator : null, chunk: stamp ? stamp.chunk : null },
           operations: ops };
}

/** Deterministic JSON for the file the user saves: sorted keys, 2-space indent. */
export function dumpChangeSet(doc) {
  const sorter = (v) => (Array.isArray(v) ? v.map(sorter)
    : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorter(v[k])])) : v);
  return `${JSON.stringify(sorter(doc), null, 2)}\n`;
}

/** The shell command that applies a saved change-set. */
export function applyCommand(stamp, changesPath = "changes.json") {
  const ifc = stamp && stamp.file ? stamp.file : "model.ifc";
  return `est-bim apply-changes ${ifc} ${changesPath} -o ${ifc.replace(/\.ifc$/i, "")}.edited.ifc`;
}
