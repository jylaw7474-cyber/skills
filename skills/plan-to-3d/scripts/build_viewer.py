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
    <label>שכבות</label>
    <div class="tog on"><input type="checkbox" id="tWall" checked><span>קירות</span></div>
    <div class="tog on"><input type="checkbox" id="tGlass" checked><span>זיגוג</span></div>
    <div class="tog"><input type="checkbox" id="tFurn"><span>ריהוט לפי התוכנית</span></div>
    <div class="tog"><input type="checkbox" id="tCeil"><span>תקרה</span></div>
    <div class="tog on"><input type="checkbox" id="tRooms" checked><span>צביעת חללים</span></div>
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
const WH = MODEL.wall_height, SILL = MODEL.sill, HEAD = MODEL.head, SLAB = MODEL.slab;

/* ---------------------------------------------------------------- scene --- */
const renderer = new THREE.WebGLRenderer({antialias:true, alpha:false});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputEncoding = THREE.sRGBEncoding;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.92;
renderer.localClippingEnabled = true;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d0f12);
scene.fog = new THREE.Fog(0x0d0f12, 60, 190);

const camera = new THREE.PerspectiveCamera(45, 1, 0.05, 600);
const walkCam = new THREE.PerspectiveCamera(68, 1, 0.02, 300);
const lamp = new THREE.PointLight(0xffe9cc, 0.0, 16, 2.0);
walkCam.add(lamp); scene.add(walkCam);

const hemi = new THREE.HemisphereLight(0xdde6f2, 0x30291f, 0.55);
scene.add(hemi);
const key = new THREE.DirectionalLight(0xfff2e0, 1.55);
key.castShadow = true;
key.shadow.mapSize.set(4096, 4096);
key.shadow.bias = -0.00015;
key.shadow.normalBias = 0.08;
scene.add(key, key.target);
const fill = new THREE.DirectionalLight(0xc3d6f2, 0.32);
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
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(scale, scale);
  t.anisotropy = renderer.capabilities.getMaxAnisotropy();
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.magFilter = THREE.LinearFilter;
  return t;
}

const MAT = {
  wall:  new THREE.MeshStandardMaterial({color:0xeae3d8, roughness:0.9, metalness:0.0,
                                         envMapIntensity:0.35, map:grain('#eae3d8', 6, 0.9)}),
  slab:  new THREE.MeshStandardMaterial({color:0x7d786f, roughness:0.95, envMapIntensity:0.2}),
  floor: new THREE.MeshStandardMaterial({color:0xb9a88f, roughness:0.42, metalness:0.03,
                                         envMapIntensity:0.7, map:grain('#b9a88f', 10, 1.6)}),
  glass: new THREE.MeshPhysicalMaterial({color:0xaecfe2, roughness:0.04, metalness:0.0,
                                         transparent:true, opacity:0.22, envMapIntensity:1.4,
                                         side:THREE.DoubleSide}),
  furn:  new THREE.MeshStandardMaterial({color:0x9a8a74, roughness:0.8}),
  ceil:  new THREE.MeshStandardMaterial({color:0xd7cfc2, roughness:1.0, envMapIntensity:0.1,
                                        side:THREE.DoubleSide})
};
const ROOM_COLORS = [0xb8935f,0x7190ab,0x86a677,0xbb9a5c,0x8a7ea8,0x639dab,0xb2798a,
                     0x99a862,0xae7a70,0x7387b5,0xa89658,0x77a894];

let group = new THREE.Group(); scene.add(group);
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
  while (group.children.length) group.remove(group.children[0]);
  spaceMeshes = []; picked = -1;
  const W = fl.size[0], D = fl.size[1];

  addMesh(solidGeom(fl.plate, -SLAB, 0.0), MAT.slab, true, true, 'slab');
  addMesh(solidGeom(fl.plate, 0.0, 0.02, {bottom:false}), MAT.floor, false, true, 'floor');

  fl.spaces.forEach((sp, i) => {
    const mat = new THREE.MeshStandardMaterial({
      color: ROOM_COLORS[i % ROOM_COLORS.length], roughness:0.45, metalness:0.03,
      envMapIntensity:0.6, map: MAT.floor.map });
    const m = addMesh(rectGeom(sp.rects, 0.018, 0.055), mat, false, true, 'rooms');
    m.userData.space = sp; m.userData.baseColor = mat.color.clone();
    spaceMeshes.push(m);
  });

  const wallMats = [MAT.wall.clone(), MAT.wall.clone(), MAT.wall.clone()];
  wallMats.forEach(m => { m.clippingPlanes = [clip]; m.clipShadows = true; });
  addMesh(solidGeom(fl.wall, 0.0, WH), wallMats[0], true, true, 'wall');
  addMesh(solidGeom(fl.wall_under, 0.0, SILL), wallMats[1], true, true, 'wall');
  addMesh(solidGeom(fl.wall_over, HEAD, WH), wallMats[2], true, true, 'wall');

  const gm = MAT.glass.clone(); gm.clippingPlanes = [clip];
  addMesh(solidGeom(fl.glass, SILL, HEAD), gm, false, false, 'glass');

  addMesh(solidGeom(fl.furniture, 0.056, 0.17), MAT.furn, true, true, 'furn');

  const cm = MAT.ceil.clone(); cm.clippingPlanes = [clip];
  addMesh(solidGeom(fl.plate, WH, WH + 0.12), cm, false, false, 'ceil');

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
el.addEventListener('pointerdown', e => {
  if (mode === 'walk') { el.requestPointerLock(); return; }
  orbit.drag = {x:e.clientX, y:e.clientY, b:e.button, moved:0};
  el.setPointerCapture(e.pointerId);
});
el.addEventListener('pointermove', e => {
  if (mode === 'walk'){
    if (document.pointerLockElement === el){
      yaw -= e.movementX * 0.0022; pitch -= e.movementY * 0.0022;
      pitch = Math.max(-1.35, Math.min(1.35, pitch));
    }
    return;
  }
  if (!orbit.drag) return;
  const dx = e.clientX - orbit.drag.x, dy = e.clientY - orbit.drag.y;
  orbit.drag.x = e.clientX; orbit.drag.y = e.clientY;
  orbit.drag.moved += Math.abs(dx) + Math.abs(dy);
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
  if (orbit.drag && orbit.drag.moved < 5 && mode !== 'walk') pick(e);
  orbit.drag = null;
});
el.addEventListener('wheel', e => {
  e.preventDefault();
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
  for (const r of current.wall_rects)
    if (px > r[0]-0.28 && px < r[0]+r[2]+0.28 && pz > r[1]-0.28 && pz < r[1]+r[3]+0.28) return true;
  return false;
}

function walkStep(dt){
  const sp = (keys.ShiftLeft || keys.ShiftRight ? 5.4 : 2.3) * dt;
  let fx = 0, fz = 0;
  if (keys.KeyW || keys.ArrowUp) fz -= 1;
  if (keys.KeyS || keys.ArrowDown) fz += 1;
  if (keys.KeyA || keys.ArrowLeft) fx -= 1;
  if (keys.KeyD || keys.ArrowRight) fx += 1;
  if (!fx && !fz) return;
  const l = Math.hypot(fx, fz); fx /= l; fz /= l;
  const s = Math.sin(yaw), c = Math.cos(yaw);
  const dx = (fx*c - fz*s) * sp, dz = (fx*s + fz*c) * sp;
  const p = walkCam.position;
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
    m.material.emissive = new THREE.Color(k === i ? 0x4a3a1e : 0x000000);
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

function fmt(n){ return n.toLocaleString('he-IL', {minimumFractionDigits:1, maximumFractionDigits:1}); }

function fillTables(fl){
  const z = $('#zones'); z.innerHTML = '';
  let tot = 0;
  Object.entries(fl.exact_area_m2).sort((a,b)=>b[1]-a[1]).forEach(([c,a]) => {
    tot += a;
    z.insertAdjacentHTML('beforeend',
      `<tr><td>גוון <span class="swatch" style="background:${c}"></span></td>
           <td class="n">${fmt(a)} מ״ר</td></tr>`);
  });
  z.insertAdjacentHTML('beforeend',
    `<tr><td><b>סה״כ</b></td><td class="n"><b>${fmt(tot)} מ״ר</b></td></tr>`);
  $('#zonenote').textContent =
    'שטחים מחושבים מגיאומטריית ההצללה שבתוכנית עצמה, לא מהרסטר.';

  const s = $('#spaces'); s.innerHTML = '';
  fl.spaces.slice().sort((a,b)=>b.area-a.area).forEach((sp) => {
    const i = fl.spaces.indexOf(sp);
    s.insertAdjacentHTML('beforeend',
      `<tr class="pick" data-i="${i}"><td>חלל ${sp.id}</td>
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
      walkCam.position.set(orbit.target.x, 1.65, orbit.target.z);
    }
  });
  hud();
}

function hud(){
  $('#hudTitle').textContent = current ? (current.title || '') : '';
  const sp = picked >= 0 ? spaceMeshes[picked].userData.space : null;
  $('#hudBody').innerHTML = sp
    ? `חלל ${sp.id} · <b>${fmt(sp.area)} מ״ר</b><br>` +
      `${fmt(sp.bbox[2]-sp.bbox[0])} × ${fmt(sp.bbox[3]-sp.bbox[1])} מ׳`
    : (mode === 'walk'
        ? 'תנועה <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> · ריצה <kbd>Shift</kbd> · מבט בעכבר'
        : 'לחיצה על חלל מציגה את שטחו · גרירה לסיבוב · גלגלת לזום');
}

function applyLayers(){
  const on = {wall:$('#tWall').checked, glass:$('#tGlass').checked, furn:$('#tFurn').checked,
              ceil:$('#tCeil').checked, rooms:$('#tRooms').checked};
  group.children.forEach(m => {
    const l = m.userData.layer;
    if (l in on) m.visible = on[l];
  });
  document.querySelectorAll('.tog').forEach(t =>
    t.classList.toggle('on', t.querySelector('input').checked));
}
['tWall','tGlass','tFurn','tCeil','tRooms'].forEach(id => $('#'+id).onchange = applyLayers);

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
  }
  if (m === 'walk'){
    $('#tCeil').checked = true; $('#slider').value = 3.2; clip.constant = 3.2; applyLayers();
    const sp = current.spaces.slice().sort((a,b)=>b.area-a.area)[0];
    if (sp){
      walkCam.position.set((sp.bbox[0]+sp.bbox[2])/2 - current.size[0]/2, 1.65,
                           (sp.bbox[1]+sp.bbox[3])/2 - current.size[1]/2);
      yaw = (sp.bbox[2]-sp.bbox[0]) > (sp.bbox[3]-sp.bbox[1]) ? Math.PI/2 : 0;
      pitch = 0;
    }
    lamp.intensity = 1.5; key.intensity = 0.5; hemi.intensity = 0.3;
    renderer.toneMappingExposure = 0.86;
  } else {
    lamp.intensity = 0.0; key.intensity = 1.55; hemi.intensity = 0.55;
    renderer.toneMappingExposure = 0.92;
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
