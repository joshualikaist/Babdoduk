/* The 3D campus map (docs/CAMPUS_MAP.md): the clay miniature of the Daejeon campus, with a pin on the
   building of each free-food event of the day the home calendar shows.

   The model, its baked ground light, the poster and the building table come from data/campus/ (built
   by scripts/campus3d/). The poster is already on the page; this module draws the live model over it
   once it is loaded, and keeps the poster when WebGL is not available. Pins are buttons in the page,
   not part of the 3D scene, so they are reachable by keyboard and read by screen readers, and they
   work on the poster too (it is the same camera).

   mount(stage, options) -> { show(day), select(code), destroy() }
     options.lang()           'ko' | 'en'
     options.t(key, fallback) a translated string
     options.onOpen(eventId)  "일정에서 보기": open that event in the calendar
     options.base             where data/campus/ is, from the page (default 'data/campus/')
     options.onFull()         "크게 보기": open the map full screen (beside the copy only)
*/
import * as THREE from './vendor/three-0.186.1/three.module.js';
import { GLTFLoader } from './vendor/three-0.186.1/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from './vendor/three-0.186.1/addons/loaders/DRACOLoader.js';
import { OrbitControls } from './vendor/three-0.186.1/addons/controls/OrbitControls.js';
import { place } from './campus-place.js';

export { place };

const PIN_LIFT = 14;                 // meters above the roof where a pin's tip points
const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function webgl() {
  try {
    const c = document.createElement('canvas');
    return !!(window.WebGL2RenderingContext && c.getContext('webgl2'));
  } catch (e) {
    return false;
  }
}

function srgb(rgb) {
  return new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);
}

function hm(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const kst = new Date(d.getTime() + 9 * 3600 * 1000);
  return String(kst.getUTCHours()).padStart(2, '0') + ':' + String(kst.getUTCMinutes()).padStart(2, '0');
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
}

/* Walls and roofs of every building, one mesh: roofs by their normal, a band of windows on each
   floor (3.6 m) with mullions, a little darker at the foot of each wall, and the buildings of the
   day's events in the highlight colour (uniform list of _bid). */
function buildingMaterial(palette) {
  const mat = new THREE.MeshLambertMaterial({ color: 0xffffff });
  const uniforms = {
    uWall: { value: srgb(palette.wall) }, uRoof: { value: srgb(palette.roof) }, uGlass: { value: srgb(palette.glass) },
    uHi: { value: srgb(palette.highlight) }, uPick: { value: srgb([0.93, 0.28, 0.55]) },
    uGlassStrong: { value: srgb(palette.glass_strong || palette.glass) },
    uBrickWall: { value: srgb(palette.brick_wall || palette.wall) }, uBrickRoof: { value: srgb(palette.brick_roof || palette.roof) },
    uMetalWall: { value: srgb(palette.metal_wall || palette.wall) }, uMetalRoof: { value: srgb(palette.metal_roof || palette.roof) },
    uIds: { value: new Float32Array(16) }, uSel: { value: 0 },
  };
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nattribute float _bid;\nattribute float _style;\nvarying float vBid;\nvarying float vStyle;\nvarying vec3 vWorld;\nvarying vec3 vNormalW;')
      .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\nvBid = _bid;\nvStyle = _style;\nvWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;\nvNormalW = normalize(mat3(modelMatrix) * objectNormal);');
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>
uniform vec3 uWall; uniform vec3 uRoof; uniform vec3 uGlass; uniform vec3 uHi; uniform vec3 uPick;
uniform vec3 uGlassStrong; uniform vec3 uBrickWall; uniform vec3 uBrickRoof; uniform vec3 uMetalWall; uniform vec3 uMetalRoof;
uniform float uIds[16]; uniform float uSel;
varying float vBid; varying float vStyle; varying vec3 vWorld; varying vec3 vNormalW;`)
      .replace('vec4 diffuseColor = vec4( diffuse, opacity );', `
float ny = abs(vNormalW.y);
float roof = step(0.8, ny);
float wall = 1.0 - step(0.35, ny);
// Landmark styles (buildings-extra.json): 1 glass curtain, 2 red brick with a brown roof, 3 metal.
float glassy = step(0.5, vStyle) * (1.0 - step(1.5, vStyle));
float brick = step(1.5, vStyle) * (1.0 - step(2.5, vStyle));
float metal = step(2.5, vStyle);
float band = fract((vWorld.y - 0.4) / 3.6);
float along = vWorld.x - vWorld.z;
float lo = 0.38 - 0.24 * glassy + 0.04 * brick - 0.18 * metal;
float hi = 0.78 + 0.12 * glassy - 0.04 * brick + 0.07 * metal;
float mull = 0.22 - 0.14 * glassy + 0.08 * brick - 0.12 * metal;
float win = wall * step(lo, band) * (1.0 - step(hi, band)) * step(mull, fract(along / 3.2)) * step(2.2, vWorld.y);
float hot = 0.0;
for (int i = 0; i < 16; i++) { if (uIds[i] > 0.5 && abs(uIds[i] - vBid) < 0.5) hot = 1.0; }
float sel = (uSel > 0.5 && abs(uSel - vBid) < 0.5) ? 1.0 : 0.0;
vec3 wallC = mix(mix(uWall, uBrickWall, brick), uMetalWall, metal);
vec3 roofC = mix(mix(uRoof, uBrickRoof, brick), uMetalRoof, metal);
vec3 glassC = mix(uGlass, uGlassStrong, max(glassy, metal));
vec3 base = mix(wallC, roofC, roof);
base = mix(base, uHi, hot * 0.85);
base = mix(base, uPick, sel * 0.55);
// Windows smaller than a pixel would shimmer: they fade into the wall's average tone.
float px = length(fwidth(vWorld));
float fine = 1.0 - smoothstep(0.35, 0.9, px);
base = mix(base, glassC, mix(wall * (0.18 + 0.3 * glassy), win, fine) * (1.0 - sel * 0.6));
base *= mix(0.84, 1.0, smoothstep(0.4, 6.0, vWorld.y));
vec4 diffuseColor = vec4( base, opacity );`);
  };
  mat.userData.uniforms = uniforms;
  return mat;
}

export function mount(stage, options) {
  const opts = Object.assign({ lang: () => 'ko', t: (k, f) => f, onOpen: () => {}, onFull: null, base: 'data/campus/' }, options || {});
  const BASE = opts.base;
  const pinsLayer = stage.querySelector('.home-map-pins');
  const card = stage.querySelector('.home-map-card');
  const note = stage.parentElement.querySelector('.home-map-note');
  const state = { table: null, model: null, day: null, items: [], groups: [], selected: '', ready: false };
  let renderer = null, scene = null, camera = null, controls = null, buildings = null, buildingMat = null, frame = 0, visible = true;
  let destroyed = false;

  const tables = Promise.all([
    fetch(BASE + 'buildings.json').then((r) => r.json()),
    fetch(BASE + 'model.json').then((r) => r.json()),
  ]).then(([table, model]) => {
    state.table = table;
    state.model = model;
    state.ready = true;
    layoutPins();
  });

  // The poster's camera, for pins before (or without) the live model.
  function posterCamera() {
    const m = state.model.camera;
    const cam = new THREE.PerspectiveCamera(fovFor(m, stage.clientWidth / Math.max(1, stage.clientHeight)),
      stage.clientWidth / Math.max(1, stage.clientHeight), 10, 20000);
    cam.position.fromArray(m.position);
    cam.lookAt(new THREE.Vector3().fromArray(m.target));
    cam.updateMatrixWorld();
    return cam;
  }
  function fovFor(m, aspect) {
    // Blender fits the sensor width to the image width: keep that horizontal field of view.
    const hfov = 2 * Math.atan(m.sensor / 2 / m.lens);
    return THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(hfov / 2) / aspect));
  }

  // ---- the live model ----------------------------------------------------------------------------
  function start() {
    if (!webgl() || destroyed) return;
    const canvas = stage.querySelector('.home-map-canvas');
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    scene = new THREE.Scene();
    const m = state.model;
    const sun = new THREE.DirectionalLight(new THREE.Color().setRGB(...m.sun.color, THREE.SRGBColorSpace), 1.9);
    sun.position.fromArray(m.sun.direction).multiplyScalar(1000);
    scene.add(sun, new THREE.HemisphereLight(0xfff8ee, 0xcbbca6, 2.6));
    camera = posterCamera();
    controls = new OrbitControls(camera, canvas);
    controls.target.fromArray(m.camera.target);
    state.homeDist = camera.position.distanceTo(controls.target);
    controls.enablePan = false;
    controls.enableZoom = false;
    controls.enableDamping = !reduceMotion();
    // Like a map (owner 2026-11-04: "가운데에 고정되어 있다는 점"): drag moves, the right button or
    // Shift + drag turns all the way round and tilts from almost straight down to a low angle, and
    // Ctrl/⌘ + wheel zooms toward the pointer. Phones: one finger moves, two fingers zoom and turn.
    controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE };
    controls.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE };
    controls.screenSpacePanning = false;
    controls.zoomToCursor = true;
    controls.rotateSpeed = 0.5;
    controls.minPolarAngle = 0.22;
    controls.maxPolarAngle = 1.12;
    controls.addEventListener('change', () => { keepOnIsland(); requestRender(); });
    controls.update();
    interaction();
    // Beside the copy a plain wheel scrolls the page: Ctrl/⌘ + wheel (and a trackpad pinch) zooms.
    canvas.addEventListener('pointerenter', (e) => {
      if (state.taught || e.pointerType !== 'mouse') return;
      state.taught = true;
      hint(opts.t('home.map.dragHint', '끌어서 이동 · 오른쪽 끌기로 회전 · Ctrl + 스크롤로 확대'), 2600);
    });
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    canvas.addEventListener('wheel', (e) => {
      if (stage.closest('dialog') || e.ctrlKey || e.metaKey) return;
      e.stopImmediatePropagation();
      hint();
    }, { capture: true });
    tools();

    const draco = new DRACOLoader().setDecoderPath(new URL('./vendor/three-0.186.1/addons/libs/draco/', import.meta.url).href);
    const loader = new GLTFLoader().setDRACOLoader(draco);
    const light = new THREE.TextureLoader().loadAsync(BASE + 'ground-light.webp');
    Promise.all([loader.loadAsync(BASE + 'campus.glb'), light]).then(([gltf, lightTex]) => {
      if (destroyed) return;
      lightTex.colorSpace = THREE.NoColorSpace;      // light amounts, multiplied as they are
      lightTex.flipY = false;
      lightTex.anisotropy = 4;
      const pal = m.palette;
      const groundColor = { base: pal.base_top, paths: pal.path, roads: pal.road };
      const protos = [];
      gltf.scene.traverse((o) => {
        if (!o.isMesh) return;
        const name = (o.name || '').replace(/_\d+$/, '');
        if (o.parent && /^ground/.test(o.parent.name) || /^ground/.test(name)) {
          const key = (o.material && o.material.name) || 'grass';
          const color = groundColor[key] || pal[key] || pal.grass;
          o.material = new THREE.MeshBasicMaterial({ color: srgb(color), map: lightTex });
        } else if (/^island_sides/.test(name)) {
          o.material = new THREE.MeshLambertMaterial({ color: srgb(pal.base_side) });
        } else if (/^buildings/.test(name) || (o.parent && /^buildings/.test(o.parent.name))) {
          // One shader for every part of the buildings mesh (landmark styles split it by material):
          // the day's highlight reaches all of them.
          buildingMat = buildingMat || buildingMaterial(pal);
          o.material = buildingMat;
          buildings = o;
        } else if (/^landmarks/.test(name) || (o.parent && /^landmarks/.test(o.parent.name))) {
          // The gate (stone), the carillon's three ribbons and the fountains, by material name.
          const key = ((o.material && o.material.name) || 'stone').replace(/\.\d+$/, '');
          o.material = new THREE.MeshLambertMaterial({ color: srgb(pal[key] || pal.stone || pal.wall),
                                                       emissive: key === 'jet' ? srgb([0.35, 0.4, 0.45]) : 0x000000 });
        } else if (/^units/.test(name)) {
          o.material = new THREE.MeshLambertMaterial({ color: srgb(pal.unit) });
        } else if (/^tree\d/.test(name) || (o.parent && /^tree\d/.test(o.parent.name))) {
          protos.push(o);
        }
      });
      // Trees: one instanced mesh per shape and part (trunk, crown).
      const byShape = {};
      protos.forEach((o) => {
        const shape = Number(((o.parent && /^tree\d/.test(o.parent.name) ? o.parent.name : o.name).match(/tree(\d)/) || [0, 0])[1]);
        (byShape[shape] = byShape[shape] || []).push(o);
        o.visible = false;
      });
      const mtx = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
      Object.keys(byShape).forEach((shape) => {
        const list = m.trees.filter((t) => t[4] === Number(shape));
        byShape[shape].forEach((part) => {
          const isTrunk = part.material && /trunk/.test(part.material.name);
          const color = isTrunk ? pal.trunk : pal.crown[Number(shape) % pal.crown.length];
          const inst = new THREE.InstancedMesh(part.geometry, new THREE.MeshLambertMaterial({ color: srgb(color), flatShading: !isTrunk }), list.length);
          list.forEach((t, i) => {
            q.setFromAxisAngle(up, t[3]);
            mtx.compose(new THREE.Vector3(t[0], 0.38, t[1]), q, new THREE.Vector3(t[2], t[2], t[2]));
            inst.setMatrixAt(i, mtx);
          });
          scene.add(inst);
        });
      });
      scene.add(gltf.scene);
      highlight();
      resize();
      renderer.render(scene, camera);
      stage.setAttribute('data-state', 'live');
    }).catch(() => stage.setAttribute('data-state', 'poster'));
  }

  function requestRender() {
    if (!renderer || frame || !visible) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (controls.enableDamping && controls.update()) requestRender();
      renderer.render(scene, camera);
      layoutPins();
    });
  }
  // In the full-screen dialog (phones) the map also zooms and pans; beside the copy it only turns.
  function interaction() {
    if (!controls) return;
    const full = !!stage.closest('dialog');
    controls.enableZoom = true;
    controls.screenSpacePanning = false;
    controls.minDistance = 400;
    controls.maxDistance = state.homeDist * (full ? 1.4 : 1.25);
    controls.enablePan = true;
    fit(full);
    const fullButton = stage.querySelector('[data-map-act="full"]');
    if (fullButton) fullButton.hidden = full || !opts.onFull;
  }
  // Wherever it is dragged, the point the camera looks at stays on the island.
  // How far the view may drift from the hero view's centre grows with the zoom: at the hero distance the
  // island hardly moves (80 m), close up up to 450 m (owner 2026-11-04: "맵이 너무 안
  // 벗어나게"). Measured from the hero target, so the island stays in sight.
  function keepOnIsland() {
    const t = controls.target, home = state.model.camera.target;
    const ratio = camera.position.distanceTo(t) / state.homeDist;
    const lim = THREE.MathUtils.clamp(80 + 520 * (1 - ratio), 80, 450);
    // ...and never closer than 180 m to the island's edge (its outline spans x -625…715, z -607…716).
    const cx = THREE.MathUtils.clamp(THREE.MathUtils.clamp(t.x, home[0] - lim, home[0] + lim), -445, 535);
    const cz = THREE.MathUtils.clamp(THREE.MathUtils.clamp(t.z, home[2] - lim, home[2] + lim), -427, 536);
    if (cx !== t.x || cz !== t.z || t.y !== 0) {
      const shift = new THREE.Vector3(cx - t.x, -t.y, cz - t.z);
      t.add(shift);
      camera.position.add(shift);
    }
  }
  // ＋ / − / ⟲: the camera glides along its line to the target (at once with reduced motion).
  let glide = 0;
  function moveTo(position, target) {
    cancelAnimationFrame(glide);
    const p0 = camera.position.clone(), t0 = controls.target.clone(), start = performance.now();
    const step = (now) => {
      const k = reduceMotion() ? 1 : Math.min(1, (now - start) / 260);
      const e = 1 - Math.pow(1 - k, 3);
      camera.position.lerpVectors(p0, position, e);
      controls.target.lerpVectors(t0, target, e);
      controls.update();
      requestRender();
      if (k < 1) glide = requestAnimationFrame(step);
    };
    glide = requestAnimationFrame(step);
  }
  function zoomBy(factor) {
    if (!controls) return;
    const dir = camera.position.clone().sub(controls.target);
    const d = THREE.MathUtils.clamp(dir.length() * factor, controls.minDistance, controls.maxDistance);
    moveTo(controls.target.clone().add(dir.setLength(d)), controls.target.clone());
  }
  function home() {
    state.fitted = false;
    moveTo(new THREE.Vector3().fromArray(state.model.camera.position), new THREE.Vector3().fromArray(state.model.camera.target));
  }
  function tools() {
    if (stage.querySelector('.home-map-tools')) return;
    const box = document.createElement('div');
    box.className = 'home-map-tools';
    box.innerHTML = [['in', 'home.map.zoomIn', '확대', '＋'], ['out', 'home.map.zoomOut', '축소', '−'],
      ['home', 'home.map.reset', '처음 위치', '⟲'], ['full', 'home.map.full', '크게 보기', '⤢']]
      .map(([act, key, fallback, glyph]) => '<button type="button" class="home-map-tool" data-map-act="' + act +
        '" data-key="' + key + '" aria-label="' + esc(opts.t(key, fallback)) + '" title="' + esc(opts.t(key, fallback)) +
        '"><span aria-hidden="true">' + glyph + '</span></button>').join('');
    const tip = document.createElement('p');
    tip.className = 'home-map-hint';
    tip.setAttribute('aria-hidden', 'true');
    tip.hidden = true;
    stage.append(box, tip);
    interaction();
  }
  let hintTimer = 0;
  function hint(text, ms) {
    const tip = stage.querySelector('.home-map-hint');
    if (!tip) return;
    const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
    tip.textContent = (text || (mac ? opts.t('home.map.wheelHintMac', '⌘ + 스크롤로 확대해요')
      : opts.t('home.map.wheelHint', 'Ctrl + 스크롤로 확대해요'))).replace('Ctrl', mac ? '⌘' : 'Ctrl');
    tip.hidden = false;
    clearTimeout(hintTimer);
    hintTimer = setTimeout(() => { tip.hidden = true; }, ms || 1400);
  }
  // The dialog starts close to the day's pins (a phone's tall screen shows the whole island small);
  // back beside the copy, the hero view returns.
  function fit(full) {
    if (full && !state.fitted && state.groups.length) {
      const pts = state.groups.map((g) => row(g.code)).map((r) => new THREE.Vector3(r.at[0], 0, -r.at[1]));
      const centre = pts.reduce((a, q) => a.add(q), new THREE.Vector3()).multiplyScalar(1 / pts.length);
      const spread = Math.max(220, ...pts.map((q) => q.distanceTo(centre)));
      const dir = camera.position.clone().sub(controls.target).normalize();
      controls.target.copy(centre);
      camera.position.copy(centre).add(dir.multiplyScalar(Math.min(state.homeDist, spread * 5.5)));
      controls.update();
      state.fitted = true;
    } else if (!full && state.fitted) {
      camera.position.fromArray(state.model.camera.position);
      controls.target.fromArray(state.model.camera.target);
      controls.update();
      state.fitted = false;
    }
  }
  function resize() {
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    interaction();
    if (renderer) {
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.fov = fovFor(state.model.camera, w / h);
      camera.updateProjectionMatrix();
      requestRender();
    }
    layoutPins();
  }

  // ---- pins ----------------------------------------------------------------------------------------
  // One group per building; on screen, buildings whose pins would overlap share one pin (a cluster),
  // whose card lists each building in turn. Clusters follow the camera.
  const NEAR_X = 58, NEAR_Y = 36;
  function group(items) {
    const byCode = new Map();
    const unplaced = [];
    items.forEach((item) => {
      const where = place(item.ev.location, state.table);
      if (!where.placed) return unplaced.push(item);
      if (!byCode.has(where.code)) byCode.set(where.code, { code: where.code, items: [], others: 0 });
      const g = byCode.get(where.code);
      g.items.push(item);
      g.others = Math.max(g.others, where.others);
    });
    const groups = Array.from(byCode.values());
    groups.sort((a, b) => String(a.items[0].ev.startAt).localeCompare(String(b.items[0].ev.startAt)));
    return { groups, unplaced };
  }
  function row(code) {
    return state.table.buildings.find((r) => r.code === code);
  }
  function buildingName(code) {
    const r = row(code);
    return opts.lang() === 'en' ? r.nameEn : r.name;
  }
  function membersOf(key) {
    return key.split(',').map((code) => state.groups.find((g) => g.code === code)).filter(Boolean);
  }
  function pinLabel(members) {
    const items = members.flatMap((g) => g.items);
    const first = items[0];
    const time = hm(first.ev.startAt);
    const more = items.length > 1 ? ' ' + opts.t('home.map.more', '외 {n}개').replace('{n}', items.length - 1) : '';
    const places = members.map((g) => g.code + ' ' + buildingName(g.code)).join(', ');
    return { time, count: items.length, text: time + ' ' + first.ev.title + more + ', ' + places };
  }
  function renderPins() {
    if (!state.ready || !state.day) return;
    const { groups } = group(state.items);
    state.groups = groups;
    state.sig = '';
    // Only the map data credit (ODbL); events without a place stay in the calendar (owner 2026-11-04:
    // "위치 미정 1개 이거 제거해줘").
    if (note) note.textContent = opts.t('home.map.attribution', '지도 데이터: OpenStreetMap');
    if (!groups.length) pinsLayer.innerHTML = '';
    highlight();
    layoutPins();
  }
  function layoutPins() {
    if (!state.ready || !state.groups.length) return;
    const cam = camera || posterCamera();
    const w = stage.clientWidth, h = stage.clientHeight, v = new THREE.Vector3();
    const spots = state.groups.map((g) => {
      const r = row(g.code);
      v.set(r.at[0], r.top + PIN_LIFT, -r.at[1]).project(cam);
      return { g, x: (v.x + 1) / 2 * w, y: (1 - v.y) / 2 * h, front: v.z < 1 };
    });
    const clusters = [];
    spots.forEach((s) => {
      const near = clusters.find((c) => Math.abs(c.x - s.x) < NEAR_X && Math.abs(c.y - s.y) < NEAR_Y);
      if (near) near.members.push(s.g);
      else clusters.push({ x: s.x, y: s.y, front: s.front, members: [s.g] });
    });
    const sig = clusters.map((c) => c.members.map((g) => g.code).join(',')).join('|') + '/' + opts.lang();
    if (sig !== state.sig) {
      state.sig = sig;
      const focused = document.activeElement && pinsLayer.contains(document.activeElement)
        ? document.activeElement.getAttribute('data-codes') : '';
      pinsLayer.innerHTML = clusters.map((c) => {
        const key = c.members.map((g) => g.code).join(',');
        const l = pinLabel(c.members);
        const live = c.members.some((g) => g.items.some((it) => it.active));
        return '<button type="button" class="home-map-pin' + (live ? '' : ' is-past') + '" data-codes="' + esc(key) +
          '" aria-label="' + esc(l.text) + '" aria-expanded="' + (key === state.selected) + '" aria-controls="homeMapCard">' +
          '<span class="home-map-pin-time">' + esc(l.time) + '</span>' +
          (l.count > 1 ? '<span class="home-map-pin-count">' + l.count + '</span>' : '') + '</button>';
      }).join('');
      if (state.selected && !clusters.some((c) => c.members.map((g) => g.code).join(',') === state.selected)) closeCard();
      const back = focused && pinsLayer.querySelector('[data-codes^="' + focused.split(',')[0] + '"]');
      if (back) back.focus({ preventScroll: true });
    }
    // A building dragged off the map (or behind the camera) takes its pin with it: hidden, out of the
    // tab order, and its card closed (owner 2026-11-04: pins ran out over the calendar).
    clusters.forEach((c, i) => {
      const pin = pinsLayer.children[i];
      const inside = c.front && c.x >= 8 && c.x <= w - 8 && c.y >= 30 && c.y <= h - 4;
      pin.hidden = !inside;
      pin.style.setProperty('--x', c.x.toFixed(1) + 'px');
      pin.style.setProperty('--y', c.y.toFixed(1) + 'px');
      if (!inside && pin.getAttribute('data-codes') === state.selected) select('');
    });
    if (state.selected) placeCard();
  }
  function idOf(code) {
    return state.table.buildings.findIndex((r) => r.code === code) + 1;
  }
  function highlight() {
    if (!buildings) return requestRender();
    const u = buildings.material.userData.uniforms;
    u.uIds.value.fill(0);
    state.groups.slice(0, 16).forEach((g, i) => { u.uIds.value[i] = idOf(g.code); });
    u.uSel.value = state.selected ? idOf(state.selected.split(',')[0]) : 0;
    requestRender();
  }

  // ---- the card ------------------------------------------------------------------------------------
  function eventHtml(item) {
    const ev = item.ev;
    // The dish in a word or two, in the page's language (2026-11-05: the raw description put a
    // bilingual mail's English sentence on the Korean card), and the sign-up link by the shared rule
    // (a meeting link is not a sign-up), http(s) only.
    const F = window.BabdodukFreeFood;
    const food = F && F.hasFood(ev) ? F.dishLabel(ev, opts.t) : '';
    const url = F ? F.signUp(ev).url : '';
    const reg = /^https?:\/\//i.test(url) ? url : '';
    return '<li class="home-map-card-ev">' +
      '<p class="home-map-card-title">' + esc(ev.title) + '</p>' +
      '<p class="home-map-card-meta">' + esc(hm(ev.startAt)) + (ev.location && ev.location.room ? ' · ' + esc(ev.location.room) : '') +
      (food ? ' · ' + esc(food) : '') + '</p>' +
      '<p class="home-map-card-actions">' +
      (reg ? '<a class="home-map-card-link" href="' + esc(reg) + '" target="_blank" rel="noopener noreferrer">' + esc(opts.t('home.map.register', '신청하기')) + ' ↗</a>' : '') +
      '<button type="button" class="home-map-card-open" data-ev="' + esc(ev.id) + '">' + esc(opts.t('home.map.open', '일정에서 보기')) + '</button></p></li>';
  }
  function placeHtml(g) {
    return '<p class="home-map-card-place"><span class="home-map-card-code">' + esc(g.code) + '</span> ' + esc(buildingName(g.code)) +
      (g.others ? ' <span class="home-map-card-more">' + esc(opts.t('home.map.otherPlaces', '외 {n}곳').replace('{n}', g.others)) + '</span>' : '') + '</p>';
  }
  // The head (the first place and ×) stays put; below it every listing is set off by a line and the
  // body scrolls when there are many (owner 2026-11-05: "이벤트끼리 분리해서 보이기 쉽게 … 한줄정도 선으로
  // 표시하거나 많으면 밑으로 스크롤"). A further place starts its own group under the same kind of line.
  function cardHtml(members) {
    const close = '<button type="button" class="home-map-card-close" aria-label="' + esc(opts.t('home.map.close', '닫기')) + '">×</button>';
    return '<div class="home-map-card-head">' + placeHtml(members[0]) + close + '</div>' +
      '<div class="home-map-card-body">' +
      members.map((g, i) => '<div class="home-map-card-group">' + (i ? placeHtml(g) : '') +
        '<ul class="home-map-card-list">' + g.items.map(eventHtml).join('') + '</ul></div>').join('') + '</div>';
  }
  // Above its pin, or below it near the top edge; never past the map's sides.
  function placeCard() {
    const pin = pinsLayer.querySelector('[data-codes="' + state.selected + '"]');
    if (!pin || card.hidden) return;
    const x = parseFloat(pin.style.getPropertyValue('--x')), y = parseFloat(pin.style.getPropertyValue('--y'));
    const w = stage.clientWidth, h = stage.clientHeight, cw = card.offsetWidth, ch = card.offsetHeight;
    const left = Math.max(6, Math.min(w - cw - 6, x - cw / 2));
    // Inside the map: above the pin when it fits, else below it, else as low as the map allows.
    const top = y - 56 - ch >= 6 ? y - 56 - ch : Math.max(6, Math.min(y + 10, h - ch - 6));
    card.style.left = left.toFixed(1) + 'px';
    card.style.top = top.toFixed(1) + 'px';
  }
  function closeCard() {
    state.selected = '';
    card.hidden = true;
    card.innerHTML = '';
  }
  function select(key, focusCard) {
    const members = key ? membersOf(key) : [];
    if (!members.length) closeCard();
    else {
      state.selected = key;
      card.innerHTML = cardHtml(members);
      card.hidden = false;
      placeCard();
      if (focusCard) card.querySelector('.home-map-card-close').focus();
    }
    Array.prototype.forEach.call(pinsLayer.children, (pin) => {
      pin.setAttribute('aria-expanded', String(pin.getAttribute('data-codes') === state.selected));
    });
    highlight();
  }

  function onClick(e) {
    const pin = e.target.closest('.home-map-pin');
    if (pin) return select(pin.getAttribute('data-codes') === state.selected ? '' : pin.getAttribute('data-codes'), false);
    if (e.target.closest('.home-map-card-close')) return closeAndReturn();
    const open = e.target.closest('.home-map-card-open');
    if (open) return opts.onOpen(open.getAttribute('data-ev'));
    const tool = e.target.closest('[data-map-act]');
    if (!tool) return;
    const act = tool.getAttribute('data-map-act');
    if (act === 'in') zoomBy(0.65);
    else if (act === 'out') zoomBy(1 / 0.65);
    else if (act === 'home') home();
    else if (act === 'full' && opts.onFull) opts.onFull();
  }
  function closeAndReturn() {
    const key = state.selected;
    select('');
    const back = pinsLayer.querySelector('[data-codes="' + key + '"]');
    if (back) back.focus();
  }
  function onKey(e) {
    if (e.key !== 'Escape' || !state.selected) return;
    e.stopPropagation();          // in the phone dialog, Esc closes the card first, then the dialog
    e.preventDefault();
    closeAndReturn();
  }
  stage.addEventListener('click', onClick);
  stage.addEventListener('keydown', onKey);
  const ro = new ResizeObserver(resize);
  ro.observe(stage);
  const io = new IntersectionObserver((entries) => {
    visible = entries.some((en) => en.isIntersecting);
    if (visible) requestRender();
  });
  io.observe(stage);

  tables.then(() => {
    renderPins();
    // The live model only where it can run and is wanted: never on Save-Data.
    const saveData = navigator.connection && navigator.connection.saveData;
    if (!saveData) (window.requestIdleCallback || ((f) => setTimeout(f, 300)))(start);
  });

  return {
    show(detail) {
      state.day = detail.day;
      state.items = (detail.items || []).filter((it) => it.food || (it.ev && it.ev.giveaway));
      closeCard();
      if (state.ready) renderPins();
    },
    relabel() {
      if (!state.ready) return;
      stage.querySelectorAll('[data-map-act]').forEach((b) => {
        const label = opts.t(b.getAttribute('data-key'), b.getAttribute('aria-label'));
        b.setAttribute('aria-label', label);
        b.setAttribute('title', label);
      });
      const key = state.selected;
      renderPins();
      if (key) select(key, false);
    },
    destroy() {
      destroyed = true;
      ro.disconnect();
      io.disconnect();
      stage.removeEventListener('click', onClick);
      stage.removeEventListener('keydown', onKey);
      if (renderer) renderer.dispose();
    },
  };
}
