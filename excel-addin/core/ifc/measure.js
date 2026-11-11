/**
 * Measuring on a tessellated mesh. Pure: arrays in, numbers out, so the
 * viewer's three.js stays in panes/ifc/viewer.js and this is unit-tested.
 *
 * Points are [x, y, z] in metres in whatever frame the mesh is in (lengths
 * and areas do not care). The caller converts for display with `display`.
 * A tessellation has no points between its vertices, so a measurement
 * snaps: `snapVertex` to the nearest vertex of the picked triangle, within
 * a tolerance the caller derives from the view (pixels, not metres).
 * Face area grows across coplanar neighbours from the picked triangle, so a
 * wall face is one face even though it is many triangles.
 */
import { M_PER_FT } from "./bundle.js";

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a) => Math.hypot(a[0], a[1], a[2]);

export function distance(a, b) { return norm(sub(a, b)); }

/** Vertex `i` of `positions` as [x, y, z]. */
export function vertex(positions, i) { return [positions[3 * i], positions[3 * i + 1], positions[3 * i + 2]]; }

/** Triangle `t`'s vertex indices. */
export function triangle(indices, t) { return [indices[3 * t], indices[3 * t + 1], indices[3 * t + 2]]; }

/** Unit normal of triangle `t`, or null for a degenerate one. */
export function normal(positions, indices, t) {
  const [a, b, c] = triangle(indices, t).map((i) => vertex(positions, i));
  const n = cross(sub(b, a), sub(c, a));
  const len = norm(n);
  return len > 0 ? n.map((x) => x / len) : null;
}

export function triangleArea(positions, indices, t) {
  const [a, b, c] = triangle(indices, t).map((i) => vertex(positions, i));
  return norm(cross(sub(b, a), sub(c, a))) / 2;
}

/**
 * The nearest of triangle `t`'s vertices to `point`, when within `tol`:
 * {index, point, distance} or null. `tol` is in the mesh's units; the
 * viewer derives it from pixels at the hit's depth.
 */
export function snapVertex(positions, indices, t, point, tol) {
  let best = null;
  for (const i of triangle(indices, t)) {
    const v = vertex(positions, i), d = distance(v, point);
    if (d <= tol && (!best || d < best.distance)) best = { index: i, point: v, distance: d };
  }
  return best;
}

/**
 * Grow from triangle `t` across shared edges while the neighbour's normal
 * is within `angleDeg` of the seed's and it lies in the seed's plane
 * (within `planeTol`). Returns {triangles: [t...], area, normal}.
 * An edge is shared when both its vertex indices match, so the mesh must be
 * welded at the seams a face crosses — the iterator's output is.
 */
export function growFace(positions, indices, t, { angleDeg = 1, planeTol = 1e-4 } = {}) {
  const seedN = normal(positions, indices, t);
  if (!seedN) return { triangles: [], area: 0, normal: null };
  const cosTol = Math.cos((angleDeg * Math.PI) / 180);
  const seedP = vertex(positions, indices[3 * t]);
  const edgeKey = (i, j) => (i < j ? `${i}:${j}` : `${j}:${i}`);
  const byEdge = new Map();
  const triCount = indices.length / 3;
  for (let k = 0; k < triCount; k += 1) {
    const [a, b, c] = triangle(indices, k);
    for (const key of [edgeKey(a, b), edgeKey(b, c), edgeKey(c, a)]) {
      if (!byEdge.has(key)) byEdge.set(key, []);
      byEdge.get(key).push(k);
    }
  }
  const seen = new Set([t]), queue = [t], out = [];
  let area = 0;
  while (queue.length) {
    const k = queue.pop();
    out.push(k);
    area += triangleArea(positions, indices, k);
    const [a, b, c] = triangle(indices, k);
    for (const key of [edgeKey(a, b), edgeKey(b, c), edgeKey(c, a)]) {
      for (const n of byEdge.get(key)) {
        if (seen.has(n)) continue;
        const nn = normal(positions, indices, n);
        if (!nn || dot(nn, seedN) < cosTol) continue;
        const p = vertex(positions, indices[3 * n]);
        if (Math.abs(dot(sub(p, seedP), seedN)) > planeTol) continue;
        seen.add(n);
        queue.push(n);
      }
    }
  }
  return { triangles: out.sort((x, y) => x - y), area, normal: seedN };
}

/** Axis-aligned bounds of a mesh: {min, max, size}. */
export function bounds(positions) {
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < positions.length; i += 3) {
    for (let k = 0; k < 3; k += 1) {
      const v = positions[i + k];
      if (v < min[k]) min[k] = v;
      if (v > max[k]) max[k] = v;
    }
  }
  return { min, max, size: [max[0] - min[0], max[1] - min[1], max[2] - min[2]] };
}

/**
 * The box an element's bounds describe in IFC terms: plan length and width
 * (the longer and shorter horizontal extents) and height, in metres. The
 * mesh is glTF Y-up, so Y is the vertical.
 */
export function boxDims(positions) {
  const { size } = bounds(positions);
  const [x, h, z] = size;
  return { L: Math.max(x, z), W: Math.min(x, z), H: h };
}

/** A measurement in the estimator's units: {value, unit, si, siUnit}. `kind` is "length" or "area". */
export function display(si, kind) {
  if (kind === "area") return { value: si / M_PER_FT ** 2, unit: "SF", si, siUnit: "m2" };
  return { value: si / M_PER_FT, unit: "ft", si, siUnit: "m" };
}

export function formatNumber(x, places = 3) {
  return Number.isFinite(x) ? x.toLocaleString("en-US", { maximumFractionDigits: places, minimumFractionDigits: 0 }) : "";
}
