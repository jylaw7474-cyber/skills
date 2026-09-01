#!/usr/bin/env python3
"""
Stage 3 - build_viewer.py
Wrap a model.json in a self-contained 3D viewer (one HTML file, no build step).

    python build_viewer.py model.json --out apartments.html --title "..."

The page carries the model inline, so it works offline and can be published as
an artifact, mailed, or opened from disk.
"""
import argparse, json, os, re

HTML = r"""<title>__TITLE__</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Frank+Ruhl+Libre:wght@500;700&family=Heebo:wght@300;400;500;700&display=swap">
<style>
:root{
  --bg:#0d0f12; --panel:#15181d; --line:#262b33; --ink:#e8e6e1; --dim:#9aa1ab;
  --accent:#c8a26a; --accent-soft:#3a3226;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:400 13px/1.6 Heebo,"Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif;
     direction:rtl;overflow:hidden;-webkit-font-smoothing:antialiased}
canvas{display:block}
#ui{position:fixed;inset-inline-start:0;top:0;bottom:0;width:296px;background:var(--panel);
    border-inline-end:1px solid var(--line);overflow-y:auto;padding:16px 16px 60px;z-index:5}
#ui h1{margin:0 0 3px;font:700 19px/1.25 "Frank Ruhl Libre",Georgia,"Times New Roman",serif;
       letter-spacing:0}
#ui .sub{color:var(--dim);font-size:11px;margin-bottom:16px}
.sec{margin:0 0 18px}
.sec>label{display:block;font-size:10.5px;letter-spacing:.14em;color:var(--dim);
           text-transform:uppercase;margin-bottom:7px}
select,button{font:inherit;color:var(--ink);background:#1c2027;border:1px solid var(--line);
              border-radius:7px;padding:7px 9px;width:100%}
select:focus,button:focus{outline:1px solid var(--accent)}
.row{display:flex;gap:6px}
.row button{flex:1;cursor:pointer}
button.on{background:var(--accent-soft);border-color:var(--accent);color:#f3e6d2}
button:hover{border-color:#3d4552}
.tog{display:flex;align-items:center;gap:8px;padding:5px 2px;cursor:pointer;color:var(--dim)}
.tog input{accent-color:var(--accent);width:14px;height:14px}
.tog.on{color:var(--ink)}
table{width:100%;border-collapse:collapse;font-size:12px}
td{padding:4.5px 2px;border-bottom:1px solid #1e222a}
td.n{color:var(--dim);text-align:start;font-variant-numeric:tabular-nums;
     font-weight:500;letter-spacing:.01em}
tr.pick{cursor:pointer}
tr.pick:hover td{color:var(--accent)}
tr.sel td{color:var(--accent)}
.swatch{display:inline-block;width:9px;height:9px;border-radius:2px;margin-inline-start:6px;
        vertical-align:-1px}
.big{font-size:22px;font-weight:600;letter-spacing:-.4px}
.note{color:var(--dim);font-size:11px;line-height:1.5}
#hud b{font:700 14px/1.3 "Frank Ruhl Libre",Georgia,serif}
#hud{position:fixed;inset-inline-end:14px;top:14px;background:rgba(16,18,22,.82);
     border:1px solid var(--line);border-radius:9px;padding:9px 12px;font-size:11.5px;
     color:var(--dim);z-index:5;backdrop-filter:blur(6px);max-width:290px}
#hud b{color:var(--ink)}
kbd{background:#222731;border:1px solid #333a45;border-bottom-width:2px;border-radius:4px;
    padding:0 5px;font:11px ui-monospace,Menlo,Consolas,monospace;color:#cfd4dc}
#tip{position:fixed;inset-inline-end:14px;bottom:14px;color:#6e7681;font-size:11px;z-index:5}
#slider{width:100%;accent-color:var(--accent)}
@media (max-width:760px){#ui{width:100%;height:44vh;bottom:auto;border-inline-end:0;
  border-bottom:1px solid var(--line)}#hud{display:none}}
</style>

<div id="ui">
  <h1>__TITLE__</h1>
  <div class="sub">__SUB__</div>

  <div class="sec">
    <label>קומה</label>
    <select id="floor"></select>
  </div>

  <div class="sec">
    <label>מצב תצוגה</label>
    <div class="row">
      <button id="bOrbit" class="on">בית בובות</button>
      <button id="bWalk">הליכה</button>
      <button id="bPlan">תוכנית</button>
    </div>
  </div>

  <div class="sec">
    <label>גובה חתך</label>
    <input id="slider" type="range" min="0.2" max="3.2" step="0.05" value="3.2">
  </div>

  <div class="sec">
    <label>צביעת רצפה</label>
    <div class="row">
      <button id="cZone" class="on">לפי שטח</button>
      <button id="cSpace">לפי חלל</button>
      <button id="cPlain">אחיד</button>
    </div>
  </div>

  <div class="sec">
    <label>שכבות</label>
    <div class="tog on"><input type="checkbox" id="tWall" checked><span>קירות</span></div>
    <div class="tog on"><input type="checkbox" id="tGlass" checked><span>זיגוג</span></div>
    <div class="tog on"><input type="checkbox" id="tFurn" checked><span>ריהוט</span></div>
    <div class="tog"><input type="checkbox" id="tCeil"><span>תקרה</span></div>
    <div class="tog on"><input type="checkbox" id="tLabels" checked><span>תוויות שטח</span></div>
    <div class="tog on"><input type="checkbox" id="tZones" checked><span>שכבות שטח</span></div>
    <div class="tog on"><input type="checkbox" id="tRooms" checked><span>חללים</span></div>
  </div>

  <div class="sec">
    <label>שטחים לפי התוכנית</label>
    <table id="zones"></table>
    <div class="note" id="zonenote"></div>
  </div>

  <div class="sec">
    <label>חללים שזוהו</label>
    <table id="spaces"></table>
  </div>

  <div class="sec">
    <label>על המודל</label>
    <div class="note">
      נבנה ישירות מקובץ ה־DWFx: קנה מידה __SCALE__, יחידת שרטוט __UNIT__ מ״מ.
      גובה קיר __WH__ מ׳, סף חלון __SILL__ מ׳, משקוף __HEAD__ מ׳.
      כל מישור מקורו בגיאומטריה המשורטטת — לא נוספו ולא הושמטו שטחים.
    </div>
  </div>
</div>

<div id="hud"><b id="hudTitle"></b><div id="hudBody"></div></div>
<div id="tip" id="tip"></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script id="model" type="application/json">__MODEL__</script>
<script>
const MODEL = JSON.parse(document.getElementById('model').textContent);

/* three r128 predates colour management, so every authored colour and texture
   has to be handed over in linear space or the whole model renders washed out. */
const col = h => new THREE.Color(h).convertSRGBToLinear();

/* The sheet's legend colours are printing pastels; on a lit model they all melt
   into cream.  Boosting saturation keeps each category's hue identity while
   making the separation between area types readable at a glance. */
function vividHex(hex){
  // ACES tone mapping desaturates hard, so the authored colour has to be
  // pushed well past where it should land on screen.
  const c = new THREE.Color(hex), hsl = {h:0, s:0, l:0};
  c.getHSL(hsl);
  if (hsl.s > 0.05) c.setHSL(hsl.h, Math.min(0.85, Math.max(0.6, hsl.s * 2.6)), 0.56);
  else c.setHSL(hsl.h, 0.04, Math.min(0.6, hsl.l));
  return c;
}
const vivid = hex => vividHex(hex).convertSRGBToLinear();
const vividCss = hex => '#' + vividHex(hex).getHexString();
const WH = MODEL.wall_height, SILL = MODEL.sill, HEAD = MODEL.head, SLAB = MODEL.slab;

/* ---------------------------------------------------------------- scene --- */
const renderer = new THREE.WebGLRenderer({antialias:true, alpha:false});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputEncoding = THREE.sRGBEncoding;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.85;
renderer.localClippingEnabled = true;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d0f12);
scene.fog = new THREE.Fog(0x0d0f12, 60, 190);

const camera = new THREE.PerspectiveCamera(45, 1, 0.05, 600);
const walkCam = new THREE.PerspectiveCamera(68, 1, 0.02, 300);
const lamp = new THREE.PointLight(0xffe9cc, 0.0, 16, 2.0);
walkCam.add(lamp); scene.add(walkCam);

const hemi = new THREE.HemisphereLight(0xe4e9f0, 0x3a332a, 0.52);
scene.add(hemi);
const key = new THREE.DirectionalLight(0xfff2e0, 1.15);
key.castShadow = true;
key.shadow.mapSize.set(4096, 4096);
key.shadow.bias = -0.00015;
key.shadow.normalBias = 0.08;
scene.add(key, key.target);
const fill = new THREE.DirectionalLight(0xc3d6f2, 0.25);
fill.position.set(-40, 30, -25);
scene.add(fill);

/* A small gradient environment gives the surfaces something to reflect, which
   is most of the difference between a massing study and a room you believe. */
(function(){
  const c = document.createElement('canvas'); c.width = 32; c.height = 128;
  const g = c.getContext('2d').createLinearGradient(0, 0, 0, 128);
  g.addColorStop(0.00, '#b9cee6');
  g.addColorStop(0.45, '#e9eef4');
  g.addColorStop(0.55, '#efe6d8');
  g.addColorStop(1.00, '#6d6459');
  const x = c.getContext('2d'); x.fillStyle = g; x.fillRect(0, 0, 32, 128);
  const t = new THREE.CanvasTexture(c);
  t.encoding = THREE.sRGBEncoding;
  t.mapping = THREE.EquirectangularReflectionMapping;
  const pm = new THREE.PMREMGenerator(renderer);
  pm.compileEquirectangularShader();
  scene.environment = pm.fromEquirectangular(t).texture;
  pm.dispose(); t.dispose();
})();

/* --------------------------------------------------------------- helpers -- */
function solidGeom(sol, z0, z1, opts){
  opts = opts || {};
  const pos = [], nor = [], uv = [];
  const push = (x,y,z,nx,ny,nz,u,v) => { pos.push(x,y,z); nor.push(nx,ny,nz); uv.push(u,v); };
  const quad = (a,b,c,d,n) => {
    for (const p of [a,b,c, a,c,d]) push(p[0],p[1],p[2], n[0],n[1],n[2],
                                        (p[0]+p[2])*0.5, p[1]*0.5 + (p[0]-p[2])*0.25);
  };
  // horizontal caps
  for (const r of sol.r){
    const x0=r[0], z0r=r[1], x1=r[0]+r[2], z1r=r[1]+r[3];
    if (opts.top !== false)
      quad([x0,z1,z0r],[x1,z1,z0r],[x1,z1,z1r],[x0,z1,z1r],[0,1,0]);
    if (opts.bottom !== false)
      quad([x0,z0,z1r],[x1,z0,z1r],[x1,z0,z0r],[x0,z0,z0r],[0,-1,0]);
  }
  // exposed vertical faces only
  for (const f of sol.f){
    const x=f[0], z=f[1], L=f[2], axis=f[3], s=f[4];
    if (axis === 0){
      const n=[s,0,0];
      if (s > 0) quad([x,z0,z],[x,z0,z+L],[x,z1,z+L],[x,z1,z],n);
      else       quad([x,z0,z+L],[x,z0,z],[x,z1,z],[x,z1,z+L],n);
    } else {
      const n=[0,0,s];
      if (s > 0) quad([x+L,z0,z],[x,z0,z],[x,z1,z],[x+L,z1,z],n);
      else       quad([x,z0,z],[x+L,z0,z],[x+L,z1,z],[x,z1,z],n);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  return g;
}

function rectGeom(rects, z0, z1){
  return solidGeom({r:rects, f:[]}, z0, z1);
}

function grain(base, contrast, scale){
  // Low-frequency mottling only: fine noise sparkles under a moving camera.
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const x = c.getContext('2d');
  x.fillStyle = base; x.fillRect(0,0,64,64);
  const img = x.getImageData(0,0,64,64), d = img.data;
  for (let i=0;i<d.length;i+=4){
    const n = (Math.random()-0.5)*contrast;
    d[i]+=n; d[i+1]+=n; d[i+2]+=n;
  }
  x.putImageData(img,0,0);
  const t = new THREE.CanvasTexture(c);
  t.encoding = THREE.sRGBEncoding;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(scale, scale);
  t.anisotropy = renderer.capabilities.getMaxAnisotropy();
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.magFilter = THREE.LinearFilter;
  return t;
}

const MAT = {
  wall:  new THREE.MeshStandardMaterial({color:col(0xeae3d8), roughness:0.9, metalness:0.0,
                                         envMapIntensity:0.35, map:grain('#eae3d8', 6, 0.9)}),
  slab:  new THREE.MeshStandardMaterial({color:col(0x7d786f), roughness:0.95, envMapIntensity:0.2}),
  floor: new THREE.MeshStandardMaterial({color:col(0xb9a88f), roughness:0.42, metalness:0.03,
                                         envMapIntensity:0.7, map:grain('#b9a88f', 10, 1.6)}),
  glass: new THREE.MeshPhysicalMaterial({color:col(0x7fc4e8), roughness:0.03, metalness:0.0,
                                         transparent:true, opacity:0.26, envMapIntensity:1.8,
                                         depthWrite:false, side:THREE.DoubleSide}),
  frame: new THREE.MeshStandardMaterial({color:col(0x4c5258), roughness:0.4, metalness:0.45}),
  wallTop: new THREE.MeshStandardMaterial({color:col(0x3c4046), roughness:0.85}),
  furn: {
    0.45: new THREE.MeshStandardMaterial({color:col(0x9b9285), roughness:0.85}),
    0.55: new THREE.MeshStandardMaterial({color:col(0xd8cdbb), roughness:0.9}),
    0.72: new THREE.MeshStandardMaterial({color:col(0xa8875f), roughness:0.55,
                                          envMapIntensity:0.5}),
    0.9:  new THREE.MeshStandardMaterial({color:col(0x8a7357), roughness:0.5,
                                          envMapIntensity:0.6})
  },
  ceil:  new THREE.MeshStandardMaterial({color:col(0xd7cfc2), roughness:1.0, envMapIntensity:0.1,
                                        side:THREE.DoubleSide})
};
// A tinted floor slab needs a neutral grain, otherwise the timber base colour
// of the plate texture drags every room colour towards mud.
MAT.tint = grain('#ffffff', 9, 1.6);
// balcony decking: board stripes, tinted by the balcony colour underneath
MAT.deck = (function(){
  const c = document.createElement('canvas'); c.width = 64; c.height = 64;
  const x = c.getContext('2d');
  x.fillStyle = '#ffffff'; x.fillRect(0, 0, 64, 64);
  x.fillStyle = '#c9c9c9';
  for (let i = 0; i < 64; i += 8) x.fillRect(i, 0, 2, 64);
  const t = new THREE.CanvasTexture(c);
  t.encoding = THREE.sRGBEncoding;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(3.3, 3.3);
  t.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return t;
})();
const ROOM_COLORS = [0xd9a06b,0x76a8d8,0x7fc08b,0xe2bd62,0xa591d4,0x5fbfc4,0xd889a8,
                     0xb3c765,0xd8886d,0x86a0dd,0xc9ab5e,0x64c0a4];

let group = new THREE.Group(); scene.add(group);
let zoneMeshes = [], outdoor = {}, colorMode = 'zone';
const OUTDOOR_COLOR = 0x6f9e86;

function outKey(fl){ return 'outdoor:' + (MODEL.source || '') + ':' + fl.index; }
function loadOutdoor(fl){
  const o = {};
  fl.spaces.forEach((sp, i) => { if (sp.outdoor) o[i] = true; });
  try {
    const raw = localStorage.getItem(outKey(fl));
    if (raw) Object.assign(o, JSON.parse(raw));
  } catch (e) {}
  return o;
}
function saveOutdoor(){
  try { localStorage.setItem(outKey(current), JSON.stringify(outdoor)); } catch (e) {}
}
function isOutdoor(sp, i){ return !!outdoor[i]; }
function mainZone(){
  // The general residential category covers most of the floor; the type
  // separation the eye needs is everything that is NOT it.
  let best = null, size = -1;
  Object.entries(current && current.zones || {}).forEach(([hex, z]) => {
    if (z.name && z.area > size){ best = hex; size = z.area; }
  });
  return best;
}
function spaceColor(sp, i){
  if (isOutdoor(sp, i)) return sp.zone ? vivid(sp.zone) : col(OUTDOOR_COLOR);
  if (colorMode === 'zone' && sp.zone){
    // rooms inside the general category keep their own palette, so both kinds
    // of separation survive: room from room, and area type from area type
    if (sp.zone === mainZone() || !(current.zones[sp.zone] || {}).name)
      return col(ROOM_COLORS[i % ROOM_COLORS.length]);
    return vivid(sp.zone);
  }
  if (colorMode === 'plain') return col(0xc4b7a3);
  return col(ROOM_COLORS[i % ROOM_COLORS.length]);
}
function recolorSpaces(){
  spaceMeshes.forEach((m, i) => {
    m.material.color = spaceColor(m.userData.space, m.userData.index);
    m.material.needsUpdate = true;
  });
}
let clip = new THREE.Plane(new THREE.Vector3(0,-1,0), WH);
let current = null, spaceMeshes = [], picked = -1;

function addMesh(geom, mat, cast, receive, layerName){
  const m = new THREE.Mesh(geom, mat);
  m.castShadow = !!cast; m.receiveShadow = !!receive;
  m.userData.layer = layerName;
  group.add(m);
  return m;
}

function buildFloor(fl){
  current = fl;
  while (group.children.length) group.remove(group.children[0]);
  spaceMeshes = []; zoneMeshes = []; picked = -1;
  const W = fl.size[0], D = fl.size[1];
  outdoor = loadOutdoor(fl);

  addMesh(solidGeom(fl.plate, -SLAB, 0.0), MAT.slab, true, true, 'slab');
  addMesh(solidGeom(fl.plate, 0.0, 0.02, {bottom:false}), MAT.floor, false, true, 'floor');

  // One floor layer per hatch colour, in the colour the drawing itself uses -
  // so a category that the sheet separates stays separated here.
  // The named categories partition the floor; the anonymous hatches are the
  // gross-area calculations layered over everything, so they start switched
  // off - shown together they hide exactly the separation being asked for.
  Object.entries(fl.zones || {}).forEach(([hex, z]) => {
    const named = !!z.name;
    const mat = new THREE.MeshStandardMaterial({
      color: named ? vivid(hex) : col(hex), roughness:0.9, metalness:0.0,
      envMapIntensity:0.22, map: MAT.tint });
    const m = addMesh(rectGeom(z.rects, 0.018, 0.05), mat, false, true, 'zones');
    m.userData.zone = hex; m.userData.zoneArea = z.area;
    m.visible = named;
    zoneMeshes.push(m);
  });

  fl.spaces.forEach((sp, i) => {
    const mat = new THREE.MeshStandardMaterial({
      color: spaceColor(sp, i), roughness:0.85, metalness:0.0,
      envMapIntensity:0.22, map: isOutdoor(sp, i) ? MAT.deck : MAT.tint });
    const m = addMesh(rectGeom(sp.rects, 0.052, 0.086), mat, false, true, 'rooms');
    m.userData.space = sp; m.userData.index = i;
    spaceMeshes.push(m);
  });
  buildLabels(fl);

  const wallMats = [MAT.wall.clone(), MAT.wall.clone(), MAT.wall.clone()];
  wallMats.forEach(m => { m.clippingPlanes = [clip]; m.clipShadows = true; });
  addMesh(solidGeom(fl.wall, 0.0, WH), wallMats[0], true, true, 'wall');
  addMesh(solidGeom(fl.wall_under, 0.0, SILL), wallMats[1], true, true, 'wall');
  addMesh(solidGeom(fl.wall_over, HEAD, WH), wallMats[2], true, true, 'wall');
  // dark caps read as the cut in a dollhouse view, the way a plan pochees its
  // walls - it is what separates wall from floor at a glance from above
  addMesh(rectGeom(fl.wall.r, WH, WH + 0.02), MAT.wallTop, false, false, 'wall');
  addMesh(rectGeom(fl.wall_over.r, WH, WH + 0.02), MAT.wallTop, false, false, 'wall');
  addMesh(rectGeom(fl.wall_under.r, SILL, SILL + 0.02), MAT.wallTop, false, false, 'wall');
  if (fl.parapet){
    const pm = MAT.wall.clone(); pm.clippingPlanes = [clip]; pm.clipShadows = true;
    const ph = MODEL.parapet || 1.1;
    addMesh(solidGeom(fl.parapet, 0.0, ph), pm, true, true, 'wall');
    addMesh(rectGeom(fl.parapet.r, ph, ph + 0.02), MAT.wallTop, false, false, 'wall');
  }

  const fm = MAT.frame.clone(); fm.clippingPlanes = [clip];
  addMesh(solidGeom(fl.glass, SILL, SILL + 0.05), fm, false, false, 'glass');
  addMesh(solidGeom(fl.glass, HEAD - 0.05, HEAD), fm, false, false, 'glass');
  const gm = MAT.glass.clone(); gm.clippingPlanes = [clip];
  addMesh(solidGeom(fl.glass, SILL + 0.05, HEAD - 0.05), gm, false, false, 'glass');

  (fl.furniture || []).forEach(piece => {
    const mat = MAT.furn[piece.h] || MAT.furn[0.72];
    addMesh(solidGeom(piece.solid, 0.05, piece.h), mat, true, true, 'furn');
  });

  buildCeiling(fl);

  group.position.set(-W/2, 0, -D/2);
  key.position.set(W*0.30, Math.max(W, D)*0.42 + 26, -D*0.85);
  key.target.position.set(0,0,0);
  key.shadow.camera.left = -W*0.75; key.shadow.camera.right = W*0.75;
  key.shadow.camera.top = D*1.6; key.shadow.camera.bottom = -D*1.6;
  key.shadow.camera.far = Math.max(W,D)*3 + 80;
  key.shadow.camera.updateProjectionMatrix();

  current = fl;
  applyLayers();
  frameAll();
  fillTables(fl);
}

/* Floating labels: every meaningful space carries its identity and area, so
   the areas are readable straight off the model, not only from the side table. */
let labelSprites = [];
function labelSprite(line1, line2, accent){
  const c = document.createElement('canvas');
  const W = 512, H = 224; c.width = W; c.height = H;
  const x = c.getContext('2d');
  x.textAlign = 'center'; x.direction = 'rtl';
  const r = 34, w = W - 16, h = H - 46, x0 = 8, y0 = 8;
  x.fillStyle = 'rgba(17,19,23,0.88)';
  x.beginPath(); x.moveTo(x0 + r, y0);
  x.arcTo(x0 + w, y0, x0 + w, y0 + h, r); x.arcTo(x0 + w, y0 + h, x0, y0 + h, r);
  x.arcTo(x0, y0 + h, x0, y0, r); x.arcTo(x0, y0, x0 + w, y0, r);
  x.closePath(); x.fill();
  x.beginPath(); x.moveTo(W/2 - 18, y0 + h); x.lineTo(W/2 + 18, y0 + h);
  x.lineTo(W/2, H - 8); x.closePath(); x.fill();
  if (accent){ x.fillStyle = accent; x.fillRect(x0 + 14, y0 + 16, 10, h - 32); }
  x.fillStyle = '#f2efe9';
  x.font = '600 58px Heebo, "Segoe UI", sans-serif';
  x.fillText(line1, W/2, y0 + 74);
  x.fillStyle = '#c8a26a';
  x.font = '500 52px Heebo, "Segoe UI", sans-serif';
  x.fillText(line2, W/2, y0 + 142);
  const t = new THREE.CanvasTexture(c);
  t.encoding = THREE.sRGBEncoding; t.anisotropy = 4;
  const m = new THREE.Sprite(new THREE.SpriteMaterial({map:t, depthTest:false,
                                                       transparent:true}));
  m.center.set(0.5, 0);
  return m;
}
function buildLabels(fl){
  labelSprites = [];
  fl.spaces.forEach((sp, i) => {
    if (sp.area < (isOutdoor(sp, i) ? 3 : 6)) return;
    const zname = sp.zone && (fl.zones[sp.zone] || {}).name;
    const name = isOutdoor(sp, i) ? 'מרפסת' : (zname && sp.zone !== mainZone() ? zname : 'חלל ' + sp.id);
    const spr = labelSprite(name, fmt(sp.area) + ' מ״ר',
                            sp.zone ? vividCss(sp.zone) : null);
    const [px, pz] = spawnPoint(sp);
    spr.position.set(px + fl.size[0]/2, WH + 0.55, pz + fl.size[1]/2);
    const s = Math.max(1.6, Math.min(3.4, Math.sqrt(sp.area) * 0.55));
    spr.scale.set(s, s * 224/512, 1);
    spr.userData.layer = 'labels';
    group.add(spr);
    labelSprites.push(spr);
  });
}

/* A balcony is open to the sky, so the ceiling is assembled from the indoor
   spaces and the walls instead of from the whole floor plate. */
function buildCeiling(fl){
  const old = group.children.filter(m => m.userData.layer === 'ceil');
  old.forEach(m => group.remove(m));
  const rects = fl.wall_rects.slice();
  fl.spaces.forEach((sp, i) => { if (!isOutdoor(sp, i)) rects.push.apply(rects, sp.rects); });
  const cm = MAT.ceil.clone(); cm.clippingPlanes = [clip];
  const m = addMesh(rectGeom(rects, WH, WH + 0.12), cm, false, false, 'ceil');
  m.visible = $('#tCeil').checked;
}

function spawnPoint(sp){
  // the centre of a space's biggest rectangle is guaranteed to be inside it,
  // which the centre of its bounding box is not
  let best = sp.rects[0], a = -1;
  for (const r of sp.rects) if (r[2]*r[3] > a){ a = r[2]*r[3]; best = r; }
  return [best[0] + best[2]/2 - current.size[0]/2,
          best[1] + best[3]/2 - current.size[1]/2, best];
}

function frameAll(){
  const W = current.size[0], D = current.size[1];
  const r = Math.max(W, D);
  camera.position.set(r*0.18, r*0.42, D*0.55 + r*0.30);
  orbit.target.set(0, 0, 0);
  orbit.dist = camera.position.length();
  orbit.theta = Math.atan2(camera.position.x, camera.position.z);
  orbit.phi = Math.acos(camera.position.y / orbit.dist);
  walkCam.position.set(0, 1.65, 0);
}

/* -------------------------------------------------------------- controls -- */
const orbit = {theta:0.5, phi:0.95, dist:60, target:new THREE.Vector3(), drag:null};
const el = renderer.domElement;

/* Walking drives like a street view: grab the world to look around, click a
   spot on the floor to glide to it, roll the wheel to step forward and back. */
let walkTo = null;
const marker = (function(){
  const g = new THREE.Group();
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.20, 0.30, 40),
      new THREE.MeshBasicMaterial({color:0xffffff, transparent:true, opacity:0.85,
                                   depthTest:false, side:THREE.DoubleSide}));
  const dot = new THREE.Mesh(new THREE.CircleGeometry(0.06, 24),
      new THREE.MeshBasicMaterial({color:0xffffff, transparent:true, opacity:0.9,
                                   depthTest:false}));
  ring.rotation.x = dot.rotation.x = -Math.PI/2;
  g.add(ring, dot); g.visible = false; g.renderOrder = 999;
  scene.add(g);
  return g;
})();

function groundHit(e){
  const r = el.getBoundingClientRect();
  ndc.x = ((e.clientX - r.left)/r.width)*2 - 1;
  ndc.y = -((e.clientY - r.top)/r.height)*2 + 1;
  ray.setFromCamera(ndc, mode === 'walk' ? walkCam : camera);
  const targets = group.children.filter(m =>
    ['rooms','zones','floor','slab'].includes(m.userData.layer) && m.visible);
  const hit = ray.intersectObjects(targets, false)[0];
  return hit ? hit.point : null;
}

el.addEventListener('pointerdown', e => {
  orbit.drag = {x:e.clientX, y:e.clientY, b:e.button, moved:0};
  el.setPointerCapture(e.pointerId);
});
el.addEventListener('pointermove', e => {
  if (mode === 'walk' && !orbit.drag){
    const p = groundHit(e);
    if (p){ marker.position.set(p.x, 0.1, p.z); marker.visible = true; }
    else marker.visible = false;
    return;
  }
  if (!orbit.drag) return;
  const dx = e.clientX - orbit.drag.x, dy = e.clientY - orbit.drag.y;
  orbit.drag.x = e.clientX; orbit.drag.y = e.clientY;
  orbit.drag.moved += Math.abs(dx) + Math.abs(dy);
  if (mode === 'walk'){
    yaw += dx * 0.0042; pitch += dy * 0.0042;
    pitch = Math.max(-1.35, Math.min(1.35, pitch));
    return;
  }
  if (orbit.drag.b === 0){
    orbit.theta -= dx*0.005;
    orbit.phi = Math.max(0.08, Math.min(1.52, orbit.phi - dy*0.005));
  } else {
    const s = orbit.dist * 0.0012;
    const rt = new THREE.Vector3(Math.cos(orbit.theta), 0, -Math.sin(orbit.theta));
    const up = new THREE.Vector3(-Math.sin(orbit.theta)*Math.cos(orbit.phi), Math.sin(orbit.phi),
                                 -Math.cos(orbit.theta)*Math.cos(orbit.phi));
    orbit.target.addScaledVector(rt, -dx*s).addScaledVector(up, dy*s);
  }
});
el.addEventListener('pointerup', e => {
  const clicked = orbit.drag && orbit.drag.moved < 6;
  orbit.drag = null;
  if (!clicked) return;
  if (mode === 'walk'){
    const p = groundHit(e);
    if (p) walkTo = new THREE.Vector3(p.x, 1.65, p.z);
  } else pick(e);
});
el.addEventListener('wheel', e => {
  e.preventDefault();
  if (mode === 'walk'){
    const step = -Math.sign(e.deltaY) * 0.9;
    const dx = -Math.sin(yaw) * step, dz = -Math.cos(yaw) * step;
    const p = walkCam.position;
    walkTo = null;
    if (!blocked(p.x + dx, p.z)) p.x += dx;
    if (!blocked(p.x, p.z + dz)) p.z += dz;
    return;
  }
  orbit.dist = Math.max(3, Math.min(400, orbit.dist * (1 + Math.sign(e.deltaY)*0.11)));
}, {passive:false});

let yaw = 0, pitch = 0, mode = 'orbit';
const keys = {};
addEventListener('keydown', e => { keys[e.code] = true;
  if (e.code === 'Space') e.preventDefault(); });
addEventListener('keyup', e => { keys[e.code] = false; });

function blocked(x, z){
  if (!current) return false;
  const px = x + current.size[0]/2, pz = z + current.size[1]/2;
  const bars = current.parapet ? current.wall_rects.concat(current.parapet.r)
                               : current.wall_rects;
  for (const r of bars)
    if (px > r[0]-0.28 && px < r[0]+r[2]+0.28 && pz > r[1]-0.28 && pz < r[1]+r[3]+0.28) return true;
  return false;
}

function walkStep(dt){
  const p = walkCam.position;
  if (walkTo){
    const d = new THREE.Vector3().subVectors(walkTo, p); d.y = 0;
    const dist = d.length();
    if (dist < 0.08){ walkTo = null; }
    else {
      d.normalize();
      const step = Math.min(dist, 4.2 * dt);
      const nx = p.x + d.x * step, nz = p.z + d.z * step;
      let moved = false;
      if (!blocked(nx, p.z)){ p.x = nx; moved = true; }
      if (!blocked(p.x, nz)){ p.z = nz; moved = true; }
      if (!moved) walkTo = null;      // a wall is a wall, even for a glide
    }
  }
  const sp = (keys.ShiftLeft || keys.ShiftRight ? 5.4 : 2.3) * dt;
  let fx = 0, fz = 0;
  if (keys.KeyW || keys.ArrowUp) fz -= 1;
  if (keys.KeyS || keys.ArrowDown) fz += 1;
  if (keys.KeyA || keys.ArrowLeft) fx -= 1;
  if (keys.KeyD || keys.ArrowRight) fx += 1;
  if (!fx && !fz) return;
  walkTo = null;
  const l = Math.hypot(fx, fz); fx /= l; fz /= l;
  const s = Math.sin(yaw), c = Math.cos(yaw);
  const dx = (fx*c - fz*s) * sp, dz = (fx*s + fz*c) * sp;
  if (!blocked(p.x + dx, p.z)) p.x += dx;
  if (!blocked(p.x, p.z + dz)) p.z += dz;
}

/* ------------------------------------------------------------------ pick -- */
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
function pick(e){
  const r = el.getBoundingClientRect();
  ndc.x = ((e.clientX - r.left)/r.width)*2 - 1;
  ndc.y = -((e.clientY - r.top)/r.height)*2 + 1;
  ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObjects(spaceMeshes, false)[0];
  select(hit ? spaceMeshes.indexOf(hit.object) : -1);
}
function select(i){
  picked = i;
  spaceMeshes.forEach((m, k) => {
    m.material.emissive = col(k === i ? 0x53401f : 0x000000);
    m.material.needsUpdate = true;
  });
  document.querySelectorAll('#spaces tr').forEach((tr, k) =>
    tr.classList.toggle('sel', k === i));
  hud();
}

/* -------------------------------------------------------------------- ui -- */
const $ = s => document.querySelector(s);
const sel = $('#floor');
MODEL.floors.forEach((f, i) => {
  const o = document.createElement('option');
  o.value = i; o.textContent = (f.title || ('מסגרת ' + f.index));
  sel.appendChild(o);
});
sel.onchange = () => buildFloor(MODEL.floors[+sel.value]);

function zoneName(hex){
  const z = current && current.zones && current.zones[hex];
  return (z && z.name) || (MODEL.zone_names || {})[hex] || hex;
}
function fmt(n){ return n.toLocaleString('he-IL', {minimumFractionDigits:1, maximumFractionDigits:1}); }

function fillTables(fl){
  const z = $('#zones'); z.innerHTML = '';
  let tot = 0;
  Object.entries(fl.zones || {}).sort((a,b)=>b[1].area-a[1].area).forEach(([c, v]) => {
    tot += v.area;
    const sw = v.name ? vividCss(c) : c;
    z.insertAdjacentHTML('beforeend',
      `<tr class="pick" data-z="${c}" ${v.name ? '' : 'style="opacity:.45"'}>
           <td><span class="swatch" style="background:${sw}"></span>
           ${v.name || c}</td><td class="n">${fmt(v.area)} מ״ר</td></tr>`);
  });
  z.insertAdjacentHTML('beforeend',
    `<tr><td>סכום הקודים</td><td class="n">${fmt(tot)} מ״ר</td></tr>` +
    `<tr><td><b>שטח הרצפה</b></td><td class="n"><b>${fmt(fl.plate_area_m2)} מ״ר</b></td></tr>`);
  z.querySelectorAll('tr[data-z]').forEach(tr => tr.onclick = () => {
    const hex = tr.dataset.z;
    const m = zoneMeshes.find(m => m.userData.zone === hex);
    if (!m) return;
    m.visible = !m.visible;
    tr.style.opacity = m.visible ? '' : '.45';
  });
  $('#zonenote').textContent =
    'שטח לכל גוון הצללה, מגיאומטריית ההצללה שבתוכנית עצמה. קודי שטח חופפים זה על זה, ' +
    'ולכן סכום הקודים גדול משטח הרצפה בפועל. לחיצה על שורה מכבה את השכבה.';

  const s = $('#spaces'); s.innerHTML = '';
  fl.spaces.slice().sort((a,b)=>b.area-a.area).forEach((sp) => {
    const i = fl.spaces.indexOf(sp);
    s.insertAdjacentHTML('beforeend',
      `<tr class="pick" data-i="${i}"><td>${isOutdoor(sp,i) ? 'מרפסת' : 'חלל'} ${sp.id}
           <span class="swatch" style="background:${sp.zone||'#666'}"></span></td>
           <td class="n">${fmt(sp.area)} מ״ר</td></tr>`);
  });
  s.querySelectorAll('tr').forEach(tr => tr.onclick = () => {
    const i = +tr.dataset.i;
    select(spaceMeshes.findIndex(m => m.userData.space === fl.spaces[i]));
    const sp = fl.spaces[i];
    orbit.target.set((sp.bbox[0]+sp.bbox[2])/2 - fl.size[0]/2, 0,
                     (sp.bbox[1]+sp.bbox[3])/2 - fl.size[1]/2);
    orbit.dist = Math.max(9, Math.hypot(sp.bbox[2]-sp.bbox[0], sp.bbox[3]-sp.bbox[1]) * 1.5);
    if (mode === 'walk'){
      const [px, pz] = spawnPoint(sp);
      walkCam.position.set(px, 1.65, pz);
    }
  });
  hud();
}

function hud(){
  $('#hudTitle').textContent = current ? (current.title || '') : '';
  const sp = picked >= 0 ? spaceMeshes[picked].userData.space : null;
  if (sp){
    const i = spaceMeshes[picked].userData.index;
    $('#hudBody').innerHTML =
      `${isOutdoor(sp,i) ? 'מרפסת' : 'חלל'} ${sp.id} · <b>${fmt(sp.area)} מ״ר</b><br>` +
      `${fmt(sp.bbox[2]-sp.bbox[0])} × ${fmt(sp.bbox[3]-sp.bbox[1])} מ׳` +
      (sp.zone ? ` · ${zoneName(sp.zone)} <span class="swatch" style="background:${sp.zone}"></span>` : '') +
      `<div style="margin-top:7px"><button id="bOut">${isOutdoor(sp,i)
        ? 'החזר לחלל סגור' : 'סמן כמרפסת'}</button></div>`;
    $('#bOut').onclick = () => {
      outdoor[i] = !outdoor[i];
      if (!outdoor[i]) delete outdoor[i];
      saveOutdoor(); recolorSpaces(); buildCeiling(current);
      labelSprites.forEach(l => group.remove(l)); buildLabels(current); applyLayers();
      fillTables(current); hud();
    };
  } else {
    $('#hudBody').innerHTML = (mode === 'walk'
        ? 'גרירה להביט סביב · לחיצה על הרצפה כדי ללכת לשם · גלגלת לצעוד · גם <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd>'
        : 'לחיצה על חלל מציגה את שטחו · גרירה לסיבוב · גלגלת לזום');
  }
}

function applyLayers(){
  const on = {wall:$('#tWall').checked, glass:$('#tGlass').checked, furn:$('#tFurn').checked,
              ceil:$('#tCeil').checked, rooms:$('#tRooms').checked, zones:$('#tZones').checked,
              labels:$('#tLabels').checked && mode !== 'walk'};
  group.children.forEach(m => {
    const l = m.userData.layer;
    if (l in on) m.visible = on[l];
  });
  document.querySelectorAll('.tog').forEach(t =>
    t.classList.toggle('on', t.querySelector('input').checked));
}
['tWall','tGlass','tFurn','tCeil','tRooms','tZones','tLabels'].forEach(id => $('#'+id).onchange = applyLayers);

function setColorMode(m){
  colorMode = m;
  [['cZone','zone'],['cSpace','space'],['cPlain','plain']].forEach(([b, k]) =>
    $('#'+b).classList.toggle('on', k === m));
  recolorSpaces();
  select(picked);
}
$('#cZone').onclick  = () => setColorMode('zone');
$('#cSpace').onclick = () => setColorMode('space');
$('#cPlain').onclick = () => setColorMode('plain');

$('#slider').oninput = e => { clip.constant = +e.target.value; };

function setMode(m){
  mode = m;
  ['bOrbit','bWalk','bPlan'].forEach((b,i) =>
    $('#'+b).classList.toggle('on', ['orbit','walk','plan'][i] === m));
  if (m === 'plan'){
    orbit.phi = 0.001; orbit.theta = 0;
    orbit.dist = Math.max(current.size[0], current.size[1]) * 1.15;
    orbit.target.set(0,0,0);
    $('#slider').value = 1.2; clip.constant = 1.2;
    key.position.set(current.size[0]*0.05, Math.max(current.size[0], current.size[1]),
                     -current.size[1]*0.05);
    key.castShadow = false; key.intensity = 1.0; key.color.set(0xffffff);
    hemi.intensity = 0.7; renderer.toneMappingExposure = 0.95;
  } else if (current){
    key.castShadow = true;
    key.position.set(current.size[0]*0.30,
                     Math.max(current.size[0], current.size[1])*0.42 + 26,
                     -current.size[1]*0.85);
  }
  if (m === 'walk'){
    $('#tCeil').checked = true; $('#slider').value = 3.2; clip.constant = 3.2; applyLayers();
    const sp = current.spaces.slice().sort((a,b)=>b.area-a.area)[0];
    if (sp){
      const [px, pz, r] = spawnPoint(sp);
      walkCam.position.set(px, 1.65, pz);
      yaw = r[2] > r[3] ? Math.PI/2 : 0;
      pitch = 0;
    }
    lamp.intensity = 1.5; key.intensity = 0.5; hemi.intensity = 0.3;
    renderer.toneMappingExposure = 0.86;
  } else {
    lamp.intensity = 0.0;
    if (m !== 'plan'){ key.intensity = 1.55; hemi.intensity = 0.55;
                       renderer.toneMappingExposure = 0.85; }
    if (document.pointerLockElement) document.exitPointerLock();
  }
  hud();
}
$('#bOrbit').onclick = () => setMode('orbit');
$('#bWalk').onclick  = () => setMode('walk');
$('#bPlan').onclick  = () => setMode('plan');

/* ------------------------------------------------------------------ loop -- */
function resize(){
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h);
  camera.aspect = walkCam.aspect = w/h;
  camera.updateProjectionMatrix(); walkCam.updateProjectionMatrix();
}
addEventListener('resize', resize);

let last = performance.now();
function tick(t){
  const dt = Math.min(0.05, (t - last)/1000); last = t;
  if (mode === 'walk'){
    walkStep(dt);
    walkCam.rotation.set(pitch, yaw, 0, 'YXZ');
    renderer.render(scene, walkCam);
  } else {
    const sp = Math.sin(orbit.phi);
    camera.position.set(orbit.target.x + orbit.dist*sp*Math.sin(orbit.theta),
                        orbit.target.y + orbit.dist*Math.cos(orbit.phi),
                        orbit.target.z + orbit.dist*sp*Math.cos(orbit.theta));
    camera.lookAt(orbit.target);
    renderer.render(scene, camera);
  }
  requestAnimationFrame(tick);
}
resize();
buildFloor(MODEL.floors[__START__]);
sel.value = __START__;
requestAnimationFrame(tick);
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('model')
    ap.add_argument('--out', default='viewer.html')
    ap.add_argument('--title', default='הדמיית דירות מהתוכנית')
    ap.add_argument('--sub', default='')
    ap.add_argument('--start', type=int, default=-1,
                    help='floor shown first; -1 picks the one with the most spaces')
    a = ap.parse_args()
    m = json.load(open(a.model, encoding='utf-8'))
    start = a.start
    if start < 0:
        start = max(range(len(m['floors'])), key=lambda i: len(m['floors'][i]['spaces']))
    sub = a.sub or (f"{m.get('source','')} · {len(m['floors'])} תוכניות")
    html = (HTML
            .replace('__MODEL__', json.dumps(m, ensure_ascii=False, separators=(',', ':')))
            .replace('__TITLE__', a.title)
            .replace('__SUB__', sub)
            .replace('__SCALE__', '1:%s' % m.get('plot_scale', '?'))
            .replace('__UNIT__', '%.4f' % m.get('unit_mm', 0))
            .replace('__WH__', '%.2f' % m['wall_height'])
            .replace('__SILL__', '%.2f' % m['sill'])
            .replace('__HEAD__', '%.2f' % m['head'])
            .replace('__START__', str(start)))
    open(a.out, 'w', encoding='utf-8').write(html)
    print('wrote', a.out, os.path.getsize(a.out) // 1024, 'KB')


if __name__ == '__main__':
    main()
