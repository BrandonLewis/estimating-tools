/**
 * The sheet bundle (bimforge-sheet/1) as sheet tables. Pure: no Office.js.
 *
 * `est-bim sheet-bundle model.ifc` writes a manifest and one JSON (and GLB)
 * per chunk. This module turns one chunk into the 2-D arrays the pane
 * writes into sheets, and reads them back into rows. The sheet layouts are
 * the contract between this module and `changes.js`, so the column lists
 * are exported and the header row is always row 1.
 *
 * Units: the bundle is SI. Quantities are shown in the estimator's units
 * (ft, SF, CY, lb) at the US survey foot, the constant the takeoff workbook
 * uses, with the SI value kept in the next column.
 */
export const CONTRACT = "bimforge-sheet/1";
export const M_PER_FT = 1200 / 3937;
export const KG_PER_LB = 0.45359237;

export const SHEETS = { elements: "IFC Elements", properties: "IFC Properties", types: "IFC Types",
                        quantities: "IFC Quantities", measurements: "IFC Measurements",
                        originElements: "_ifc_origin_elements", originProperties: "_ifc_origin_properties" };

export const ELEMENT_COLUMNS = ["GlobalId", "Class", "PredefinedType", "Name", "Type", "TypeGlobalId",
                                "Container", "Whole", "Codes"];
export const PROPERTY_COLUMNS = ["GlobalId", "Pset", "Property", "Value", "ValueType"];
export const TYPE_COLUMNS = ["GlobalId", "Name", "Class", "Pset", "Property", "Value", "ValueType"];
export const QUANTITY_COLUMNS = ["GlobalId", "Name", "Quantity", "Value", "Unit", "SI value", "SI unit"];
export const MEASUREMENT_COLUMNS = ["Kind", "Value", "Unit", "SI value", "SI unit", "Elements", "Points (m, IFC)", "Chunk"];

/** The spreadsheet kind an IFC value type edits as: "bool", "int", "number" or "text". */
export function kindOf(valueType) {
  if (!valueType) return "text";
  if (valueType === "IfcBoolean" || valueType === "IfcLogical") return "bool";
  if (valueType === "IfcInteger" || valueType === "IfcCountMeasure") return "int";
  if (/Measure$/.test(valueType) || valueType === "IfcReal" || valueType === "IfcNumericMeasure") return "number";
  return "text";
}

/** A bundle value as the cell it is written to. */
export function toCell(value, valueType) {
  if (value === null || value === undefined) return "";
  if (kindOf(valueType) === "bool") return value ? "TRUE" : "FALSE";
  return value;
}

/**
 * A cell as a bundle value of `valueType`: {value} or {error}. Text is
 * trimmed; a blank cell is null. Numbers accept text that reads as a number,
 * the common case for a cell someone typed into.
 */
export function fromCell(cell, valueType) {
  if (cell === null || cell === undefined || cell === "") return { value: null };
  const kind = kindOf(valueType);
  if (kind === "bool") {
    if (typeof cell === "boolean") return { value: cell };
    const t = String(cell).trim().toLowerCase();
    if (["true", "t", "yes", "y", "1"].includes(t)) return { value: true };
    if (["false", "f", "no", "n", "0"].includes(t)) return { value: false };
    return { error: `${JSON.stringify(cell)} is not a ${valueType}` };
  }
  if (kind === "int" || kind === "number") {
    const n = typeof cell === "number" ? cell : Number(String(cell).trim());
    if (!Number.isFinite(n)) return { error: `${JSON.stringify(cell)} is not a ${valueType}` };
    if (kind === "int" && n !== Math.trunc(n)) return { error: `${JSON.stringify(cell)} is not a whole ${valueType}` };
    return { value: n };
  }
  return { value: String(cell) };
}

/** The display unit for a Qto name: SI unit, estimator unit and the factor SI -> estimator. */
export function quantityUnit(name) {
  const n = String(name);
  if (/Volume/.test(n)) return { si: "m3", unit: "CY", factor: 1 / (27 * M_PER_FT ** 3) };
  if (/Area/.test(n)) return { si: "m2", unit: "SF", factor: 1 / M_PER_FT ** 2 };
  if (/Length|Width|Height|Depth|Perimeter|Thickness/.test(n)) return { si: "m", unit: "ft", factor: 1 / M_PER_FT };
  if (/Weight|Mass/.test(n)) return { si: "kg", unit: "lb", factor: 1 / KG_PER_LB };
  return { si: "", unit: "EA", factor: 1 };
}

const round = (x, places) => Math.round(x * 10 ** places) / 10 ** places;

export function elementTable(chunk) {
  return [ELEMENT_COLUMNS, ...chunk.elements.map((e) => [
    e.global_id, e.ifc_class, e.predefined_type ?? "", e.name ?? "", e.type ?? "", e.type_global_id ?? "",
    e.container ?? "", e.whole ?? "", (e.codes || []).join("; ")])];
}

export function propertyTable(chunk) {
  return [PROPERTY_COLUMNS, ...chunk.properties.map((p) => [
    p.global_id, p.pset, p.property, toCell(p.value, p.value_type), p.value_type ?? ""])];
}

export function typeTable(chunk) {
  return [TYPE_COLUMNS, ...chunk.types.map((t) => [
    t.global_id, t.name ?? "", t.ifc_class, t.pset, t.property, toCell(t.value, t.value_type), t.value_type ?? ""])];
}

export function quantityTable(chunk) {
  const names = new Map(chunk.elements.map((e) => [e.global_id, e.name ?? ""]));
  return [QUANTITY_COLUMNS, ...chunk.quantities.map((q) => {
    const u = quantityUnit(q.quantity);
    return [q.global_id, names.get(q.global_id) ?? "", q.quantity, round(q.value * u.factor, 4), u.unit, q.value, u.si];
  })];
}

/**
 * One property set as a wide table: a row per element that carries it (or,
 * with `all`, every element), a column per property. The second row holds
 * each column's value type so a reader (and the diff) knows how to parse it.
 */
export function psetView(chunk, pset) {
  const rows = chunk.properties.filter((p) => p.pset === pset);
  const props = [...new Set(rows.map((p) => p.property))];
  const types = Object.fromEntries(rows.map((p) => [p.property, p.value_type ?? ""]));
  const byElement = new Map();
  for (const p of rows) {
    if (!byElement.has(p.global_id)) byElement.set(p.global_id, {});
    byElement.get(p.global_id)[p.property] = toCell(p.value, p.value_type);
  }
  const names = new Map(chunk.elements.map((e) => [e.global_id, e.name ?? ""]));
  return [["GlobalId", "Name", ...props],
          ["", `types of ${pset}`, ...props.map((p) => types[p])],
          ...[...byElement].map(([gid, vals]) => [gid, names.get(gid) ?? "", ...props.map((p) => vals[p] ?? "")])];
}

/** Rows of a table read back from a sheet, as objects keyed by the header. Blank trailing rows are dropped. */
export function rowsOf(table) {
  if (!table || !table.length) return [];
  const [header, ...body] = table;
  return body.filter((r) => r.some((c) => c !== "" && c !== null && c !== undefined))
    .map((r) => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ""])));
}

/**
 * Property rows read back from the properties sheet, as bundle property
 * records with parsed values. A cell that does not parse is listed in
 * `errors` and its row in `invalid`, so a diff can leave that property
 * alone rather than read the dropped row as a removal.
 */
export function propertiesFromTable(table) {
  const out = [], errors = [], invalid = [];
  for (const r of rowsOf(table)) {
    if (!r.GlobalId || !r.Pset || !r.Property) continue;
    const id = { global_id: String(r.GlobalId), pset: String(r.Pset), property: String(r.Property) };
    const parsed = fromCell(r.Value, r.ValueType || null);
    if (parsed.error) { errors.push(`${id.global_id} ${id.pset}.${id.property}: ${parsed.error}`); invalid.push(id); continue; }
    out.push({ ...id, value: parsed.value, value_type: r.ValueType ? String(r.ValueType) : null });
  }
  return { properties: out, errors, invalid };
}

/** `properties` without the records `invalid` names (bundle.js propertiesFromTable). */
export function withoutInvalid(properties, invalid) {
  const bad = new Set(invalid.map((p) => `${p.global_id}\u0000${p.pset}\u0000${p.property}`));
  return properties.filter((p) => !bad.has(`${p.global_id}\u0000${p.pset}\u0000${p.property}`));
}

/** Element rows read back from the elements sheet: {global_id, name}. */
export function elementsFromTable(table) {
  return rowsOf(table).filter((r) => r.GlobalId).map((r) => ({ global_id: String(r.GlobalId), name: String(r.Name ?? "") }));
}

/** Manifest sanity: throws on another contract. Returns the manifest. */
export function checkManifest(manifest) {
  if (!manifest || manifest.contract !== CONTRACT) {
    throw new Error(`not a ${CONTRACT} bundle (contract ${manifest && manifest.contract})`);
  }
  for (const k of ["model", "chunks", "psets", "geometry"]) {
    if (!(k in manifest)) throw new Error(`manifest lacks ${k}`);
  }
  return manifest;
}

/** The chunk entry for `id`, or the first chunk. */
export function chunkEntry(manifest, id) {
  return manifest.chunks.find((c) => c.id === id) || manifest.chunks[0] || null;
}

/** What the workbook remembers about the loaded bundle, as text for a custom document property. */
export function stampOf(manifest, chunkId) {
  return JSON.stringify({ contract: manifest.contract, file: manifest.model.file, schema: manifest.model.schema,
                          generator: manifest.model.generator, chunk: chunkId,
                          offset_m: manifest.geometry ? manifest.geometry.offset_m : null });
}

export function parseStamp(text) {
  try { const s = JSON.parse(text); return s && s.contract === CONTRACT ? s : null; } catch { return null; }
}
