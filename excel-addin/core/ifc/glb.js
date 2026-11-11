/**
 * A reader for the GLB files `est-bim sheet-bundle` writes: one node per
 * element named by its GlobalId, each with one triangle primitive of float32
 * positions and uint32 (or uint16) indices. Pure: works on an ArrayBuffer
 * under node --test as well as in the pane. Not a general glTF loader.
 *
 * Positions are glTF Y-up, offset as the bundle manifest says
 * (`geometry.offset_m`). `toIfc` puts a point back into IFC Z-up metres.
 */
const MAGIC = 0x46546C67;   // "glTF"
const JSON_CHUNK = 0x4E4F534A;
const BIN_CHUNK = 0x004E4942;
const BYTES = { 5121: 1, 5123: 2, 5125: 4, 5126: 4 };

function typed(componentType, buffer, byteOffset, count) {
  switch (componentType) {
    case 5126: return new Float32Array(buffer, byteOffset, count);
    case 5125: return new Uint32Array(buffer, byteOffset, count);
    case 5123: return new Uint16Array(buffer, byteOffset, count);
    case 5121: return new Uint8Array(buffer, byteOffset, count);
    default: throw new Error(`unsupported glTF component type ${componentType}`);
  }
}

/** {doc, bin} of a GLB: the JSON document and its binary chunk as an ArrayBuffer slice. */
export function splitGlb(arrayBuffer) {
  const view = new DataView(arrayBuffer);
  if (view.getUint32(0, true) !== MAGIC || view.getUint32(4, true) !== 2) throw new Error("not a glTF 2.0 binary");
  const length = view.getUint32(8, true);
  if (length !== arrayBuffer.byteLength) throw new Error("GLB length does not match the file");
  let pos = 12, doc = null, bin = null;
  while (pos < length) {
    const n = view.getUint32(pos, true), kind = view.getUint32(pos + 4, true);
    if (kind === JSON_CHUNK) doc = JSON.parse(new TextDecoder().decode(new Uint8Array(arrayBuffer, pos + 8, n)));
    else if (kind === BIN_CHUNK) bin = arrayBuffer.slice(pos + 8, pos + 8 + n);
    pos += 8 + n;
  }
  if (!doc) throw new Error("GLB has no JSON chunk");
  return { doc, bin: bin || new ArrayBuffer(0) };
}

function accessor(doc, bin, index) {
  const a = doc.accessors[index], bv = doc.bufferViews[a.bufferView];
  const comps = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 }[a.type];
  const offset = (bv.byteOffset || 0) + (a.byteOffset || 0);
  if (offset % BYTES[a.componentType]) {           // unaligned: copy
    const bytes = bin.slice(offset, offset + a.count * comps * BYTES[a.componentType]);
    return typed(a.componentType, bytes, 0, a.count * comps);
  }
  return typed(a.componentType, bin, offset, a.count * comps);
}

/**
 * Every node that has a mesh, in scene order:
 * [{name, extras, positions: Float32Array (3 per vertex), indices: Uint32Array (3 per triangle)}].
 * Also returns the scene's extras (the bundle writes the chunk id and offset there).
 */
export function parseGlb(arrayBuffer) {
  const { doc, bin } = splitGlb(arrayBuffer);
  const scene = doc.scenes[doc.scene || 0];
  const nodes = [];
  for (const ni of scene.nodes || []) {
    const node = doc.nodes[ni];
    if (node.mesh === undefined) continue;
    const prim = doc.meshes[node.mesh].primitives[0];
    const positions = accessor(doc, bin, prim.attributes.POSITION);
    const raw = accessor(doc, bin, prim.indices);
    const indices = raw instanceof Uint32Array ? raw : Uint32Array.from(raw);
    nodes.push({ name: node.name, extras: node.extras || {}, positions, indices });
  }
  return { nodes, extras: scene.extras || {} };
}

/** A glTF Y-up point (array or {x,y,z}) back in IFC Z-up metres, offset restored. */
export function toIfc(p, offset = [0, 0, 0]) {
  const [x, y, z] = Array.isArray(p) ? p : [p.x, p.y, p.z];
  return [x + offset[0], -z + offset[1], y + offset[2]];
}
