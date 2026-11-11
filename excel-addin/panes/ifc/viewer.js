/**
 * The measuring viewer: three.js over the chunk's GLB. All geometry maths is
 * core/ifc/measure.js; this module only draws, picks and reports.
 *
 * Modes: "select" (click an element), "distance" (two snapped points),
 * "face" (a coplanar face's area), "box" (an element's L, W, H). Every
 * measurement is reported in SI metres with the points in IFC coordinates
 * (offset restored), and the pane formats it.
 *
 * Picking raycasts against every element; for a very large chunk a GPU id
 * buffer would replace that, which is why chunks are per container.
 */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { toIfc } from "../../core/ifc/glb.js";
import { boxDims, distance, growFace, snapVertex, triangle, vertex } from "../../core/ifc/measure.js";

export const MODES = ["select", "distance", "face", "box"];
const SNAP_PX = 12;
const PALETTE = [0x7fa7d1, 0xc9a37a, 0x8fbf8f, 0xd19c9c, 0xb5a3d6, 0x9fc7c1, 0xd6c48a, 0xa8a8a8];

function colorFor(ifcClass) {
  let hsh = 0;
  for (const ch of String(ifcClass || "")) hsh = (hsh * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[hsh % PALETTE.length];
}

export function createViewer(canvas, { onPick = () => {}, onMeasure = () => {}, onStatus = () => {} } = {}) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  } catch (err) {
    onStatus(`WebGL is not available here: ${err.message}`);
    return null;
  }
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(50, 1, 0.01, 10000);
  camera.position.set(10, 10, 10);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = false;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x667788, 1.1));
  const sun = new THREE.DirectionalLight(0xffffff, 0.8);
  sun.position.set(1, 2, 1.5);
  scene.add(sun);
  const elements = new THREE.Group();
  const marks = new THREE.Group();
  scene.add(elements, marks);

  const state = { mode: "select", offset: [0, 0, 0], meshes: new Map(), first: null, highlighted: null, pending: false };
  const raycaster = new THREE.Raycaster();

  function render() {
    if (state.pending) return;
    state.pending = true;
    requestAnimationFrame(() => { state.pending = false; renderer.render(scene, camera); });
  }
  controls.addEventListener("change", render);

  function resize() {
    const w = canvas.clientWidth || 300, hgt = canvas.clientHeight || 240;
    renderer.setSize(w, hgt, false);
    camera.aspect = w / hgt;
    camera.updateProjectionMatrix();
    render();
  }
  const observer = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
  if (observer) observer.observe(canvas);

  function fit() {
    const box = new THREE.Box3().setFromObject(elements);
    if (box.isEmpty()) return;
    const size = box.getSize(new THREE.Vector3()), centre = box.getCenter(new THREE.Vector3());
    const radius = Math.max(size.x, size.y, size.z, 0.1);
    camera.near = radius / 1000;
    camera.far = radius * 100;
    camera.position.copy(centre).add(new THREE.Vector3(radius, radius * 0.8, radius));
    camera.updateProjectionMatrix();
    controls.target.copy(centre);
    controls.update();
    render();
  }

  function clearMarks() {
    for (const m of [...marks.children]) { marks.remove(m); m.geometry?.dispose(); }
    state.first = null;
    render();
  }

  /** Replace the scene with `nodes` (core/ifc/glb.js parseGlb) at the bundle's offset. */
  function load(nodes, offset = [0, 0, 0]) {
    clear();
    state.offset = offset;
    for (const n of nodes) {
      const geom = new THREE.BufferGeometry();
      geom.setAttribute("position", new THREE.BufferAttribute(n.positions, 3));
      geom.setIndex(new THREE.BufferAttribute(n.indices, 1));
      const drawn = geom.toNonIndexed();          // flat faces: a box is six faces, not a smoothed blob
      drawn.computeVertexNormals();
      geom.dispose();
      const material = new THREE.MeshLambertMaterial({ color: colorFor(n.extras.ifc_class), flatShading: true });
      const mesh = new THREE.Mesh(drawn, material);
      mesh.userData = { globalId: n.name, ifcClass: n.extras.ifc_class, positions: n.positions, indices: n.indices, color: material.color.getHex() };
      elements.add(mesh);
      state.meshes.set(n.name, mesh);
    }
    fit();
    onStatus(`${nodes.length} elements in view`);
  }

  function clear() {
    clearMarks();
    for (const m of [...elements.children]) { elements.remove(m); m.geometry.dispose(); m.material.dispose(); }
    state.meshes.clear();
    state.highlighted = null;
    render();
  }

  function highlight(globalId) {
    if (state.highlighted) {
      const prev = state.meshes.get(state.highlighted);
      if (prev) prev.material.color.setHex(prev.userData.color);
    }
    state.highlighted = null;
    const mesh = globalId ? state.meshes.get(globalId) : null;
    if (mesh) { mesh.material.color.setHex(0xff8c1a); state.highlighted = globalId; }
    render();
  }

  function mark(point, color = 0xff8c1a) {
    const r = controls.target.distanceTo(camera.position) / 150;
    const dot = new THREE.Mesh(new THREE.SphereGeometry(r, 12, 8), new THREE.MeshBasicMaterial({ color }));
    dot.position.set(...point);
    marks.add(dot);
  }

  function markLine(a, b) {
    const geom = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...a), new THREE.Vector3(...b)]);
    marks.add(new THREE.Line(geom, new THREE.LineBasicMaterial({ color: 0xff8c1a })));
  }

  function markFace(mesh, tris) {
    const { positions, indices } = mesh.userData;
    const pts = [];
    for (const t of tris) for (const i of triangle(indices, t)) pts.push(...vertex(positions, i));
    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    const mat = new THREE.MeshBasicMaterial({ color: 0xff8c1a, transparent: true, opacity: 0.55, side: THREE.DoubleSide,
                                             polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
    marks.add(new THREE.Mesh(geom, mat));
  }

  /** World metres per screen pixel at `depth` from the camera. */
  function metresPerPixel(depth) {
    const h = canvas.clientHeight || 240;
    return (2 * depth * Math.tan((camera.fov * Math.PI) / 360)) / h;
  }

  function pick(event) {
    const rect = canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const hit = raycaster.intersectObjects(elements.children, false)[0];
    return hit || null;
  }

  function onClick(event) {
    const hit = pick(event);
    if (!hit) return;
    const mesh = hit.object, { globalId, positions, indices } = mesh.userData;
    const point = [hit.point.x, hit.point.y, hit.point.z];
    const ifcPoint = (p) => toIfc(p, state.offset).map((x) => Math.round(x * 1e4) / 1e4);
    if (state.mode === "select") {
      highlight(globalId);
      onPick(globalId);
    } else if (state.mode === "distance") {
      const tol = metresPerPixel(hit.distance) * SNAP_PX;
      const snap = snapVertex(positions, indices, hit.faceIndex, point, tol);
      const p = snap ? snap.point : point;
      mark(p);
      if (!state.first) {
        state.first = { point: p, globalId, snapped: Boolean(snap) };
        onStatus(snap ? "Snapped to a vertex. Pick the second point." : "On the surface. Pick the second point.");
      } else {
        markLine(state.first.point, p);
        const si = distance(state.first.point, p);
        const elementsHit = [...new Set([state.first.globalId, globalId])];
        onMeasure({ kind: "length", si, elements: elementsHit, points: [ifcPoint(state.first.point), ifcPoint(p)],
                    snapped: state.first.snapped && Boolean(snap) });
        state.first = null;
      }
    } else if (state.mode === "face") {
      clearMarks();
      const face = growFace(positions, indices, hit.faceIndex);
      markFace(mesh, face.triangles);
      onMeasure({ kind: "area", si: face.area, elements: [globalId], triangles: face.triangles.length,
                  points: [ifcPoint(point)], normal: face.normal });
    } else if (state.mode === "box") {
      clearMarks();
      highlight(globalId);
      const dims = boxDims(positions);
      onMeasure({ kind: "box", dims, elements: [globalId], points: [ifcPoint(point)] });
    }
    render();
  }
  canvas.addEventListener("click", onClick);

  function setMode(mode) {
    if (!MODES.includes(mode)) return;
    state.mode = mode;
    clearMarks();
    onStatus({ select: "Click an element to select its row.", distance: "Click two points. Vertices snap.",
               face: "Click a face to measure its area.", box: "Click an element for its L, W, H." }[mode]);
  }

  function dispose() {
    canvas.removeEventListener("click", onClick);
    if (observer) observer.disconnect();
    controls.dispose();
    clear();
    renderer.dispose();
  }

  resize();
  return { load, clear, fit, highlight, setMode, clearMarks, resize, dispose, get mode() { return state.mode; },
           get count() { return state.meshes.size; } };
}
