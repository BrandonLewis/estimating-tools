import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ELEMENT_COLUMNS, M_PER_FT, PROPERTY_COLUMNS, checkManifest, chunkEntry, elementTable, elementsFromTable,
         fromCell, kindOf, parseStamp, propertiesFromTable, propertyTable, psetView, quantityTable, quantityUnit,
         rowsOf, stampOf, toCell, typeTable, withoutInvalid } from "../core/ifc/bundle.js";
import { parseGlb, splitGlb, toIfc } from "../core/ifc/glb.js";
import { bounds, boxDims, display, distance, growFace, normal, snapVertex, triangleArea } from "../core/ifc/measure.js";
import { applyCommand, changeSet, diffNames, diffProperties, dumpChangeSet, plan } from "../core/ifc/changes.js";

const FIX = new URL("./fixtures/ifc/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL("manifest.json", FIX), "utf8"));
const chunk = JSON.parse(readFileSync(new URL("chunks/web.json", FIX), "utf8"));
const glbBytes = readFileSync(new URL("chunks/web.glb", FIX));
const glb = glbBytes.buffer.slice(glbBytes.byteOffset, glbBytes.byteOffset + glbBytes.byteLength);
const WALL = chunk.elements.find((e) => e.name === "Abut 1 wall");

test("the fixture bundle is a bimforge-sheet/1 manifest with one chunk and geometry", () => {
  assert.equal(checkManifest(manifest), manifest);
  assert.equal(chunkEntry(manifest, "web").files.geometry, "chunks/web.glb");
  assert.equal(chunkEntry(manifest, "nope").id, "web");
  assert.throws(() => checkManifest({ contract: "bimforge-web/1" }), /not a bimforge-sheet\/1/);
  const stamp = parseStamp(stampOf(manifest, "web"));
  assert.deepEqual(stamp, { contract: "bimforge-sheet/1", file: "web.ifc", schema: "IFC4X3", generator: manifest.model.generator,
                            chunk: "web", offset_m: manifest.geometry.offset_m });
  assert.equal(parseStamp("{}"), null);
  assert.equal(parseStamp("not json"), null);
});

test("value kinds and cell round trips follow the IFC value type", () => {
  assert.equal(kindOf("IfcLabel"), "text");
  assert.equal(kindOf("IfcBoolean"), "bool");
  assert.equal(kindOf("IfcInteger"), "int");
  assert.equal(kindOf("IfcLengthMeasure"), "number");
  assert.equal(kindOf(null), "text");
  assert.equal(toCell(true, "IfcBoolean"), "TRUE");
  assert.equal(toCell(null, "IfcLabel"), "");
  assert.equal(toCell(0.5, "IfcThermalTransmittanceMeasure"), 0.5);
  assert.deepEqual(fromCell("yes", "IfcBoolean"), { value: true });
  assert.deepEqual(fromCell(false, "IfcLogical"), { value: false });
  assert.deepEqual(fromCell(" 12 ", "IfcLengthMeasure"), { value: 12 });
  assert.deepEqual(fromCell(3, "IfcInteger"), { value: 3 });
  assert.deepEqual(fromCell("", "IfcLabel"), { value: null });
  assert.deepEqual(fromCell(12, "IfcLabel"), { value: "12" });
  assert.match(fromCell("maybe", "IfcBoolean").error, /not a IfcBoolean/);
  assert.match(fromCell("2.5", "IfcCountMeasure").error, /whole/);
  assert.match(fromCell("tall", "IfcReal").error, /not a IfcReal/);
});

test("the element, property, type and quantity tables carry the chunk", () => {
  const el = elementTable(chunk);
  assert.deepEqual(el[0], ELEMENT_COLUMNS);
  assert.equal(el.length, chunk.elements.length + 1);
  const wallRow = el.find((r) => r[3] === "Abut 1 wall");
  assert.equal(wallRow[0], WALL.global_id);
  assert.equal(wallRow[1], "IfcWall");
  assert.equal(wallRow[4], "Stem wall");
  assert.equal(wallRow[8], "W-CONC");
  const post = el.find((r) => r[3] === "Rail post 1");
  assert.equal(post[7], chunk.elements.find((e) => e.name === "Rail run").global_id);
  const pr = propertyTable(chunk);
  assert.deepEqual(pr[0], PROPERTY_COLUMNS);
  assert.deepEqual(pr.slice(1).map((r) => r.slice(2)), [["FireRating", "2HR", "IfcLabel"], ["IsExternal", "TRUE", "IfcBoolean"],
                                                        ["ThermalTransmittance", 0.5, "IfcThermalTransmittanceMeasure"]]);
  assert.equal(typeTable(chunk).length, 1 + chunk.types.length);
  const q = quantityTable(chunk);
  const vol = q.find((r) => r[0] === WALL.global_id && r[2] === "GrossVolume");
  assert.equal(vol[1], "Abut 1 wall");
  assert.equal(vol[4], "CY");
  assert.ok(Math.abs(vol[3] - (3 * 20 * 12) / 27) < 1e-3, `wall volume ${vol[3]} CY`);
  assert.equal(vol[6], "m3");
  assert.deepEqual(quantityUnit("GrossArea"), { si: "m2", unit: "SF", factor: 1 / M_PER_FT ** 2 });
  assert.deepEqual(quantityUnit("Count"), { si: "", unit: "EA", factor: 1 });
  assert.equal(quantityUnit("Length").unit, "ft");
  assert.equal(quantityUnit("NetWeight").unit, "lb");
});

test("a pset view is one row per element and one column per property, with a type row", () => {
  const v = psetView(chunk, "Pset_WallCommon");
  assert.deepEqual(v[0], ["GlobalId", "Name", "FireRating", "IsExternal", "ThermalTransmittance"]);
  assert.deepEqual(v[1], ["", "types of Pset_WallCommon", "IfcLabel", "IfcBoolean", "IfcThermalTransmittanceMeasure"]);
  assert.deepEqual(v[2], [WALL.global_id, "Abut 1 wall", "2HR", "TRUE", 0.5]);
  assert.equal(psetView(chunk, "Pset_Nope").length, 2);
});

test("tables read back from a sheet become records, with bad cells reported", () => {
  const table = [PROPERTY_COLUMNS, [WALL.global_id, "Pset_WallCommon", "FireRating", "4HR", "IfcLabel"],
                 [WALL.global_id, "Pset_WallCommon", "IsExternal", "nah", "IfcBoolean"],
                 ["", "", "", "", ""], [WALL.global_id, "ARR", "Width", "10", "IfcLengthMeasure"], ["", "", "", "", ""]];
  assert.deepEqual(rowsOf(table).length, 3);
  const { properties, errors } = propertiesFromTable(table);
  assert.deepEqual(properties, [
    { global_id: WALL.global_id, pset: "Pset_WallCommon", property: "FireRating", value: "4HR", value_type: "IfcLabel" },
    { global_id: WALL.global_id, pset: "ARR", property: "Width", value: 10, value_type: "IfcLengthMeasure" }]);
  assert.deepEqual(errors, [`${WALL.global_id} Pset_WallCommon.IsExternal: "nah" is not a IfcBoolean`]);
  const { invalid } = propertiesFromTable(table);
  assert.deepEqual(invalid, [{ global_id: WALL.global_id, pset: "Pset_WallCommon", property: "IsExternal" }]);
  // the bad cell's property is neither set nor removed by the diff
  const kept = withoutInvalid(chunk.properties, invalid);
  assert.equal(kept.length, chunk.properties.length - 1);
  assert.deepEqual(diffProperties(kept, properties, null).ops.filter((o) => o.property === "IsExternal"), []);
  assert.deepEqual(elementsFromTable(elementTable(chunk)).find((e) => e.global_id === WALL.global_id),
                   { global_id: WALL.global_id, name: "Abut 1 wall" });
  assert.deepEqual(rowsOf([]), []);
});

test("the GLB parses into one node per element whose volume matches the sheet's Qto", () => {
  const { doc, bin } = splitGlb(glb);
  assert.equal(doc.asset.version, "2.0");
  assert.equal(bin.byteLength, doc.buffers[0].byteLength);
  const { nodes, extras } = parseGlb(glb);
  assert.equal(extras.chunk, "web");
  assert.deepEqual(extras.offset_m, manifest.geometry.offset_m);
  const names = new Set(nodes.map((n) => n.name));
  for (const n of names) assert.ok(chunk.elements.some((e) => e.global_id === n), `${n} is an element`);
  const wall = nodes.find((n) => n.name === WALL.global_id);
  assert.equal(wall.extras.ifc_class, "IfcWall");
  assert.ok(wall.positions instanceof Float32Array && wall.indices instanceof Uint32Array);
  assert.equal(wall.indices.length % 3, 0);
  // signed-tet volume of the parsed mesh against the bundle's GrossVolume (SI)
  const p = wall.positions, ix = wall.indices;
  let vol = 0;
  const o = [p[0], p[1], p[2]];
  for (let t = 0; t < ix.length; t += 3) {
    const a = [p[3 * ix[t]] - o[0], p[3 * ix[t] + 1] - o[1], p[3 * ix[t] + 2] - o[2]];
    const b = [p[3 * ix[t + 1]] - o[0], p[3 * ix[t + 1] + 1] - o[1], p[3 * ix[t + 1] + 2] - o[2]];
    const c = [p[3 * ix[t + 2]] - o[0], p[3 * ix[t + 2] + 1] - o[1], p[3 * ix[t + 2] + 2] - o[2]];
    vol += a[0] * (b[1] * c[2] - b[2] * c[1]) + a[1] * (b[2] * c[0] - b[0] * c[2]) + a[2] * (b[0] * c[1] - b[1] * c[0]);
  }
  const qto = chunk.quantities.find((q) => q.global_id === WALL.global_id && q.quantity === "GrossVolume").value;
  assert.ok(Math.abs(Math.abs(vol) / 6 - qto) < 1e-4 * qto, `mesh ${Math.abs(vol) / 6} vs Qto ${qto}`);
  // the wall is 12 ft tall along glTF Y and 20 ft long along IFC Y (glTF -Z)
  const { size } = bounds(wall.positions);
  assert.ok(Math.abs(size[1] - 12 * M_PER_FT) < 1e-4);
  const dims = boxDims(wall.positions);
  assert.ok(Math.abs(dims.L - 20 * M_PER_FT) < 1e-4 && Math.abs(dims.W - 3 * M_PER_FT) < 1e-4 && Math.abs(dims.H - 12 * M_PER_FT) < 1e-4);
  // back to IFC: the wall's top is 15 ft above the project base
  const top = Math.max(...Array.from({ length: wall.positions.length / 3 }, (_, i) => toIfc([p[3 * i], p[3 * i + 1], p[3 * i + 2]], extras.offset_m)[2]));
  assert.ok(Math.abs(top - 15 * M_PER_FT) < 1e-4, `top ${top}`);
  assert.deepEqual(toIfc({ x: 1, y: 2, z: 3 }, [10, 20, 30]), [11, 17, 32]);
  assert.throws(() => splitGlb(new ArrayBuffer(16)), /not a glTF/);
});

test("measuring: distance, snap, face growth across coplanar triangles, box dims", () => {
  // a unit cube as two triangles per face, welded (8 vertices)
  const P = new Float32Array([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1]);
  const I = new Uint32Array([0, 2, 1, 0, 3, 2,   4, 5, 6, 4, 6, 7,   0, 1, 5, 0, 5, 4,   1, 2, 6, 1, 6, 5,
                             2, 3, 7, 2, 7, 6,   3, 0, 4, 3, 4, 7]);
  assert.equal(distance([0, 0, 0], [3, 4, 0]), 5);
  assert.equal(triangleArea(P, I, 0), 0.5);
  assert.deepEqual(normal(P, I, 4).map(Math.round), [0, -1, 0]);
  assert.deepEqual(normal(P, I, 2).map(Math.round), [0, 0, 1]);
  const face = growFace(P, I, 0);
  assert.deepEqual(face.triangles, [0, 1]);
  assert.ok(Math.abs(face.area - 1) < 1e-12);
  for (let t = 0; t < 12; t += 1) assert.ok(Math.abs(growFace(P, I, t).area - 1) < 1e-12, `face from ${t}`);
  const snap = snapVertex(P, I, 0, [0.98, 0.97, 0], 0.1);
  assert.deepEqual([snap.index, snap.point], [2, [1, 1, 0]]);
  assert.ok(Math.abs(snap.distance - Math.hypot(0.02, 0.03)) < 1e-12);
  assert.equal(snapVertex(P, I, 0, [0.5, 0.3, 0], 0.1), null);
  assert.deepEqual(boxDims(P), { L: 1, W: 1, H: 1 });
  assert.deepEqual(bounds(P), { min: [0, 0, 0], max: [1, 1, 1], size: [1, 1, 1] });
  // degenerate seed: nothing grows
  assert.deepEqual(growFace(new Float32Array(9), new Uint32Array([0, 1, 2]), 0), { triangles: [], area: 0, normal: null });
  // a bent sheet: two coplanar triangles and one folded 90 degrees share edges but only the flat pair grows
  const Q = new Float32Array([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0, 1]);
  const J = new Uint32Array([0, 1, 2, 0, 2, 3, 0, 3, 4]);
  assert.deepEqual(growFace(Q, J, 0).triangles, [0, 1]);
  assert.deepEqual(display(M_PER_FT, "length"), { value: 1, unit: "ft", si: M_PER_FT, siUnit: "m" });
  assert.ok(Math.abs(display(M_PER_FT ** 2, "area").value - 1) < 1e-12);
});

test("the change-set is the diff of origin and current, grouped for review", () => {
  const origin = chunk.properties;
  const known = new Set([...chunk.elements.map((e) => e.global_id), ...chunk.elements.map((e) => e.type_global_id).filter(Boolean)]);
  const footing = chunk.elements.find((e) => e.name === "Abut 2 footing");
  const current = [
    { ...origin[0], value: "4HR" },                                    // changed
    { ...origin[1], value: null },                                     // blanked -> remove
    { ...origin[2] },                                                  // same
    { global_id: footing.global_id, pset: "ARR_Takeoff", property: "Width", value: 10, value_type: "IfcLengthMeasure" },   // new
    { global_id: footing.global_id, pset: "ARR_Takeoff", property: "Note", value: null, value_type: null },               // new but blank: nothing
    { global_id: "stranger", pset: "P", property: "X", value: 1, value_type: null },                                         // unknown object
    { global_id: WALL.type_global_id, pset: "Pset_WallCommon", property: "Reference", value: "Std B", value_type: "IfcIdentifier" },
  ];
  const { ops, problems } = diffProperties(origin, current, known);
  assert.deepEqual(ops, [
    { op: "set_property", global_id: WALL.global_id, pset: "Pset_WallCommon", property: "FireRating", value: "4HR", value_type: "IfcLabel" },
    { op: "remove_property", global_id: WALL.global_id, pset: "Pset_WallCommon", property: "IsExternal" },
    { op: "set_property", global_id: footing.global_id, pset: "ARR_Takeoff", property: "Width", value: 10, value_type: "IfcLengthMeasure" },
    { op: "set_property", global_id: WALL.type_global_id, pset: "Pset_WallCommon", property: "Reference", value: "Std B", value_type: "IfcIdentifier" },
  ]);
  assert.deepEqual(problems, ["stranger: not an object of the loaded bundle (P.X)"]);
  // a row deleted from the sheet removes the property
  assert.deepEqual(diffProperties(origin, origin.slice(1), null).ops,
                   [{ op: "remove_property", global_id: WALL.global_id, pset: "Pset_WallCommon", property: "FireRating" }]);
  // the same number spelled differently is not a change
  assert.deepEqual(diffProperties([{ ...origin[2], value: 0.5 }], [{ ...origin[2], value: 0.5000000000001 }], null).ops, []);
  const names = diffNames([{ global_id: "a", name: "A" }, { global_id: "b", name: "B" }],
                          [{ global_id: "a", name: "A" }, { global_id: "b", name: "" }, { global_id: "c", name: "C" }]);
  assert.deepEqual(names, [{ op: "set_name", global_id: "b", value: null }]);
  const groups = plan([...ops, ...names, { op: "set_property", global_id: "x", pset: "Pset_WallCommon", property: "FireRating", value: "1HR", value_type: "IfcLabel" }]);
  assert.deepEqual(groups.map((g) => [g.title, g.count]), [["Set Pset_WallCommon.FireRating", 2], ["Remove Pset_WallCommon.IsExternal", 1],
                                                           ["Rename", 1], ["Set ARR_Takeoff.Width", 1], ["Set Pset_WallCommon.Reference", 1]]);
  const stamp = parseStamp(stampOf(manifest, "web"));
  const doc = changeSet(stamp, ops);
  assert.equal(doc.contract, "bimforge-changes/1");
  assert.deepEqual(doc.source, { file: "web.ifc", schema: "IFC4X3", generator: manifest.model.generator, chunk: "web" });
  const text = dumpChangeSet(doc);
  assert.ok(text.startsWith('{\n  "contract": "bimforge-changes/1",\n  "operations": [') && text.endsWith("}\n"));
  assert.deepEqual(JSON.parse(text).operations, ops);
  assert.equal(applyCommand(stamp), "est-bim apply-changes web.ifc changes.json -o web.edited.ifc");
  assert.equal(applyCommand(null), "est-bim apply-changes model.ifc changes.json -o model.edited.ifc");
});
