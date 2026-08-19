/* ===== Kertas Fenomena v2 — GFS (SST / Anomali / Klimatologi / Indeks) ===== */
"use strict";

const DATA = "data/output/climate.json";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
const MONTHS_FULL = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"];
const nlng = (l) => ((l % 360) + 360) % 360;
const $ = (id) => document.getElementById(id);
const toWIB = (iso) => new Date(new Date(iso).getTime() + 7 * 3600e3);

const VIEW_CORE = L.latLngBounds([-30, 80], [30, 210]);
const NINO_COLORS = { nino12: "#f76707", nino3: "#f2c037", nino34: "#7048e8", nino4: "#22b8cf" };
const NINO_LABEL = { nino12: "NINO 1+2", nino3: "NINO 3", nino34: "NINO 3.4", nino4: "NINO 4" };
const NINO_ORDER = ["nino12", "nino3", "nino34", "nino4"];

/* Legenda per layer (cocok gradasi kontinu process.py). */
const SST_CELLS = [["0", "#08036b", 1], ["4", "#1e5ba5", 1], ["8", "#3885bc", 1], ["12", "#3cadb6", 0],
  ["16", "#4ecc8b", 0], ["20", "#95d245", 0], ["24", "#ecc317", 0], ["28", "#ef780d", 1], ["32", "#a50026", 1]];
// Anomali: palet SEISMIC (cocok render_anom_png backend), -3..+3 degC; basemap gelap saat anom aktif
const ANOM_CELLS = [["-3", "#00004c", 1], ["-2", "#0000c2", 1], ["-1", "#5555ff", 1], ["-0.5", "#a9a9ff", 0],
  ["0", "#fffdfd", 0], ["+0.5", "#ffa9a9", 0], ["+1", "#ff5555", 1], ["+2", "#d30000", 1], ["+3", "#800000", 1]];
// Arus: palet OCEAN (cocok render_speed_png backend), 0..2 m/s
const SPEED_CELLS = [["0", "#008000", 1], ["0.25", "#005020", 1], ["0.5", "#002040", 1], ["0.75", "#001060", 1],
  ["1", "#004080", 1], ["1.5", "#42a0c0", 1], ["2", "#ffffff", 0]];
// Salinitas: palet HALINE (cocok render_salinity_png backend), 30..38 PSU
const SAL_CELLS = [["30", "#111854", 1], ["31", "#1b397d", 1], ["32", "#1d5c91", 1], ["33", "#197f94", 1],
  ["34", "#1e9c8a", 1], ["35", "#53b670", 0], ["36", "#95cc5b", 0], ["37", "#d4e06f", 0], ["38", "#f5f2aa", 0]];
const LAYER_LEGEND = {
  sst: { head: "°C", cells: SST_CELLS }, anom: { head: "°C", cells: ANOM_CELLS },
  clim: { head: "°C", cells: SST_CELLS }, index: { head: "°C", cells: ANOM_CELLS },
  current: { head: "m/s", cells: SPEED_CELLS }, sal: { head: "PSU", cells: SAL_CELLS },
  subt: { head: "°C", cells: SST_CELLS },
};
/* Layer -> frame-source di state.layers (current diambil dari state.currents.frames) */
const FRAME_SRC = { sst: "sst", anom: "anom", clim: "clim", index: "anom", sal: "sal" };

let state = null;
let activeLayer = "sst";
let lastLayer = "sst";   // layer parameter terakhir sebelum masuk mode Indeks (buat tombol matikan)
let frames = [];
let frameIdx = 0;
let overlay = null;
let zoneLayer = null;
let zonesLayer = null, zonesOn = false;
let dataBounds = null;
let playing = false, playTimer = null;
let selectedIndex = "nino34";
let selectedDepth = 0;   // indeks kedalaman aktif untuk layer Suhu Bawah Permukaan

/* ---- Peta (tanpa basemap, latar gelap; SST melayang di atas laut) ---- */
const map = L.map("map", {
  zoomControl: false, attributionControl: false,
  minZoom: 2, maxZoom: 9, zoomSnap: 0.25, worldCopyJump: false,
  maxBoundsViscosity: 1.0,   // batas KAKU: tak bisa di-drag ke luar domain data (kiri/kanan/atas/bawah)
}).setView([0, 150], 3);
map.createPane("basemap"); map.getPane("basemap").style.zIndex = 380;
map.createPane("sst"); map.getPane("sst").style.zIndex = 390;   // DI BAWAH overlayPane(400): partikel velocity (leaflet-velocity taruh di overlayPane) muncul di ATAS data
map.createPane("boxes"); map.getPane("boxes").style.zIndex = 460; map.getPane("boxes").style.pointerEvents = "none";
map.createPane("zones"); map.getPane("zones").style.zIndex = 462;   // zona indeks yang bisa diklik (pointerEvents default: auto)

// Basemap di lapisan BAWAH: cuma kelihatan di DARAT (laut ketutup data transparan di pantai).
// Terang (OSM) untuk kebanyakan layer; GELAP (CARTO dark) KHUSUS anomali (palet seismic pusat putih).
const BASE_LIGHT = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const BASE_DARK = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png";
L.control.attribution({ prefix: false, position: "bottomright" }).addTo(map);
const baseTile = L.tileLayer(BASE_LIGHT, {
  pane: "basemap", subdomains: "abc", crossOrigin: true, maxZoom: 19,
  attribution: "© OpenStreetMap contributors, © CARTO",
}).addTo(map);
function applyBasemap() {
  const url = activeLayer === "anom" ? BASE_DARK : BASE_LIGHT;   // basemap gelap hanya untuk layer anomali
  if (baseTile._url !== url) baseTile.setUrl(url);
}

function frameRegion() {
  if (!dataBounds || zonesOn || activeLayer === "index") return;   // mode Zona/Indeks: jangan reset view (zoomZone yg atur)
  const crs = map.options.crs;
  const sw = crs.project(VIEW_CORE.getSouthWest()), ne = crs.project(VIEW_CORE.getNorthEast());
  const cx = (sw.x + ne.x) / 2, cy = (sw.y + ne.y) / 2;
  let halfW = Math.abs(ne.x - sw.x) / 2, halfH = Math.abs(ne.y - sw.y) / 2;
  const size = map.getSize(), sr = size.x / size.y;
  if (sr > halfW / halfH) halfW = halfH * sr;
  else {
    halfH = halfW / sr;
    const dsw = crs.project(dataBounds.getSouthWest()), dne = crs.project(dataBounds.getNorthEast());
    const dHalfH = Math.abs(dne.y - dsw.y) / 2;
    if (halfH > dHalfH) { halfH = dHalfH; halfW = halfH * sr; }
  }
  const box = L.latLngBounds(crs.unproject(L.point(cx - halfW, cy - halfH)), crs.unproject(L.point(cx + halfW, cy + halfH)));
  const z = map.getBoundsZoom(box);
  map.setMinZoom(z);
  map.setMaxBounds(dataBounds);   // pas ke batas data (tak bisa geser ke luar data)
  map.setView(crs.unproject(L.point(cx, cy)), z, { animate: false });
}

/* ---- Legenda ---- */
function renderLegend(layer) {
  const def = LAYER_LEGEND[layer];
  $("legend-head").textContent = def.head;
  $("legend-cells").innerHTML = def.cells.map(([label, bg, dark]) =>
    `<div class="legend-cell${dark ? " dark" : ""}" style="background:${bg}">${label}</div>`).join("");
}

/* ---- Kotak zona (hanya yang dipilih, mode Indeks) ---- */
function boxRect(b, opts) { return L.rectangle([[b[0], b[2]], [b[1], b[3]]], opts); }
function lblMarker(txt, la, lo, c) {
  return L.marker([la, nlng(lo)], { interactive: false, pane: "boxes",
    icon: L.divIcon({ className: "box-lbl", html: `<span style="color:${c}">${txt}</span>`, iconSize: [64, 14] }) });
}
function clearZone() { if (zoneLayer) { map.removeLayer(zoneLayer); zoneLayer = null; } }
function showZone(key) {
  clearZone();
  const items = [];
  if (key === "iod") {
    const o = { color: "#e64980", weight: 3, fill: true, fillColor: "#e64980", fillOpacity: 0.12, interactive: false, pane: "boxes" };
    items.push(boxRect(state.boxes.iod_west, o), boxRect(state.boxes.iod_east, o),
      lblMarker("IOD BARAT", 12, 60, "#e64980"), lblMarker("IOD TIMUR", 2, 100, "#e64980"));
  } else {
    const c = NINO_COLORS[key], z = state.boxes[key];
    items.push(boxRect(z, { color: c, weight: 3, fill: true, fillColor: c, fillOpacity: 0.16, interactive: false, pane: "boxes" }),
      lblMarker(NINO_LABEL[key], z[1] + 3, (z[2] + z[3]) / 2, c));
  }
  zoneLayer = L.layerGroup(items).addTo(map);
}
function zoomZone(key) {
  // Center di titik-tengah zona, zoom = MAX(zoom yang memuat kotak, zoom yang bikin center TAK ke-clamp batas data).
  let clat, clon, halfLat, halfLon;
  if (key === "iod") { clat = 0; clon = 80; halfLat = 12; halfLon = 32; }   // gabungan 2 kotak IOD
  else { const z = state.boxes[key]; clat = (z[0] + z[1]) / 2; clon = (z[2] + z[3]) / 2; halfLat = (z[1] - z[0]) / 2 + 6; halfLon = (z[3] - z[2]) / 2 + 6; }
  const d = state.domain, sz = map.getSize();
  const eLon = Math.max(2, Math.min(clon - d.lonW, d.lonE - clon));   // jarak ke tepi bujur terdekat
  const eLat = Math.max(2, Math.min(clat - d.latS, d.latN - clat));
  const zFit = map.getBoundsZoom([[clat - halfLat, clon - halfLon], [clat + halfLat, clon + halfLon]], false);
  const zCtr = Math.max(Math.log2(sz.x * 180 / (256 * eLon)), Math.log2(sz.y * 180 / (256 * eLat)));   // setengah-lebar <= jarak tepi
  map.setView([clat, nlng(clon)], Math.max(2, Math.min(9, Math.max(zFit, zCtr))), { animate: true });
}

/* ---- Semua zona indeks (toggle): tiap zona diklik -> buka sidebar indeks (= selectIndex) ---- */
// Urutan penting: nino34 digambar TERAKHIR -> paling atas di area tumpang-tindih dengan nino3/nino4.
const ZONE_DEFS = [
  { key: "nino12", label: "Niño 1+2", boxes: ["nino12"] },
  { key: "nino4",  label: "Niño 4",   boxes: ["nino4"] },
  { key: "nino3",  label: "Niño 3",   boxes: ["nino3"] },
  { key: "nino34", label: "Niño 3.4", boxes: ["nino34"] },
  { key: "dmi",    label: "IOD",      boxes: ["iod_west", "iod_east"] },
];
function zoneColorOf(key) { return key === "dmi" ? "#e64980" : NINO_COLORS[key]; }
function clearZones() { if (zonesLayer) { map.removeLayer(zonesLayer); zonesLayer = null; } }
function drawZones() {
  clearZones();
  const items = [];
  for (const def of ZONE_DEFS) {
    const c = zoneColorOf(def.key);
    for (const bk of def.boxes) {
      const b = state.boxes[bk];
      const rect = L.rectangle([[b[0], b[2]], [b[1], b[3]]], { color: c, weight: 2.5, fill: true, fillColor: c, fillOpacity: 0.14, interactive: true, pane: "zones", className: "zone-rect" });
      rect.on("click", (e) => { L.DomEvent.stopPropagation(e); pickZone(def.key); });
      items.push(rect);
    }
    // label chip = target klik yang PASTI (posisi tiap zona berbeda, tak tumpang-tindih)
    const b0 = state.boxes[def.boxes[0]];
    const lbl = L.marker([(b0[0] + b0[1]) / 2, nlng((b0[2] + b0[3]) / 2)], {
      interactive: true, pane: "zones", riseOnHover: true,
      icon: L.divIcon({ className: "zone-lbl", html: `<span style="border-color:${c}">${def.label}</span>`, iconSize: [0, 0] }),
    });
    lbl.on("click", (e) => { L.DomEvent.stopPropagation(e); pickZone(def.key); });
    items.push(lbl);
  }
  zonesLayer = L.layerGroup(items).addTo(map);
}
function pickZone(key) { setZones(false); selectIndex(key); }   // klik zona -> sidebar indeks
function fitZones() {
  // Isi TINGGI dgn lintang data (tanpa kosong atas/bawah) + tengah di zona -> semua zona muat di layar lebar.
  let lonW = 1e9, lonE = -1e9;
  for (const def of ZONE_DEFS) for (const bk of def.boxes) { const b = state.boxes[bk]; lonW = Math.min(lonW, b[2]); lonE = Math.max(lonE, b[3]); }
  const z = map.getBoundsZoom(dataBounds, true);   // inside=true -> data menutupi viewport (terisi penuh)
  map.setView([0, nlng((lonW + lonE) / 2)], z, { animate: false });
  return z;
}
function setZones(on) {
  zonesOn = on;
  $("zones-btn").classList.toggle("active", on);
  if (on && dataBounds) {
    map.setMaxBounds(dataBounds);   // terkunci PAS ke batas data (tak bisa geser ke luar/abu-abu)
    map.setMinZoom(2);
    const z = fitZones();
    map.setMinZoom(z);                        // kunci: zoom-out paling jauh = tampilan semua-zona
    drawZones();
  } else { clearZones(); frameRegion(); }     // pulihkan framing terkunci (fokus Indonesia)
}

/* ---- Arus laut (Copernicus): velocity partikel SELALU nyala di semua parameter
   (konsep sama angin kertas-cuaca); layer "Arus Laut" tambah kontur kecepatan. ---- */
let currentLayer = null, curCache = {};
function frameDateOf(f) {
  if (!f) return null;
  if (f.date) return f.date;
  if (f.valid_time) return f.valid_time.slice(0, 10).replace(/-/g, "");
  return null;
}
// Indeks frame "kini" (analisis run terkini) - default slider, retensi -24j di kiri
function nowIndex() {
  if (!frames.length) return 0;
  const nowT = state && state.now;
  if (activeLayer === "clim") { const mo = nowT ? +nowT.slice(5, 7) : 1; const i = frames.findIndex((f) => f.month === mo); return i < 0 ? 0 : i; }
  if (!nowT) return 0;
  if (frames[0].valid_time) {
    const target = Date.parse(nowT); let best = 0, bd = Infinity;
    frames.forEach((f, i) => { const d = Math.abs(Date.parse(f.valid_time) - target); if (d < bd) { bd = d; best = i; } });
    return best;
  }
  if (frames[0].date) {
    const nd = nowT.slice(0, 10).replace(/-/g, ""); let best = 0, bd = Infinity;
    frames.forEach((f, i) => { const d = Math.abs(+f.date - +nd); if (d < bd) { bd = d; best = i; } });
    return best;
  }
  return 0;
}
function frameT(f) {   // timestamp frame (per-jam pakai valid_time, harian pakai date)
  if (f && f.valid_time) return Date.parse(f.valid_time);
  if (f && f.date) return Date.UTC(+f.date.slice(0, 4), +f.date.slice(4, 6) - 1, +f.date.slice(6, 8), 12);
  return 0;
}
function curVecFor(f) {
  const c = state.currents; if (!c || !c.frames || !c.frames.length) return null;
  if (f && f.vec) return f.vec;                       // frame INI memang frame arus (layer Arus)
  // velocity "selalu-nyala" di layer lain: ambil arus PERMUKAAN terdekat waktunya (kini per-jam)
  const arr = c._tidx || (c._tidx = c.frames.map((fr) => ({ t: frameT(fr), vec: fr.vec })));
  const ft = frameT(f); let best = arr[0], bd = Infinity;
  for (const a of arr) { const dd = Math.abs(a.t - ft); if (dd < bd) { bd = dd; best = a; } }
  return best.vec;
}
async function updateCurrents() {
  const cf = curVecFor(frames[frameIdx]);
  if (!cf) { if (currentLayer && map.hasLayer(currentLayer)) map.removeLayer(currentLayer); return; }
  let data = curCache[cf];
  if (!data) { data = await fetch("data/output/" + cf, { cache: "no-store" }).then((r) => r.json()).catch(() => null); if (!data) return; curCache[cf] = data; }
  if (!currentLayer) currentLayer = L.velocityLayer({
    displayValues: false, data,   // leaflet-velocity render di overlayPane (z400), di atas sst(390)
    velocityScale: 0.12, particleAge: 90, particleMultiplier: 0.006, lineWidth: 1.6,
    colorScale: ["#a5f3ea", "#2dd4bf", "#0d9488"], frameRate: 20,
  });
  else currentLayer.setData(data);
  if (!map.hasLayer(currentLayer)) currentLayer.addTo(map);
}

/* ---- Frame ---- */
function frameTimeLabel(f) {
  if (activeLayer === "clim") return MONTHS_FULL[f.month - 1];
  if (!f.valid_time && f.date) { const d = f.date; return `${+d.slice(6, 8)} ${MONTHS[+d.slice(4, 6) - 1]} ${d.slice(0, 4)}`; }   // frame harian (kedalaman/anom/arus/sal)
  const w = toWIB(f.valid_time);
  return `${w.getUTCDate()} ${MONTHS[w.getUTCMonth()]}, ${String(w.getUTCHours()).padStart(2, "0")}:00 WIB`;
}
/* ---- Loading raster: skeleton peta saat ganti parameter, bar tipis saat scrub ----
   Leaflet imageOverlay.setUrl() menahan gambar LAMA sampai PNG baru selesai; di domain
   besar ini terasa "beku". Jadi kita tutup dgn skeleton (ganti layer) / bar (scrub frame)
   sampai <img> raster benar-benar ter-load. */
let rasterSeq = 0, rasterBarTimer = null;
const LAYER_NAME = { sst: "Suhu Laut", anom: "Anomali SST", clim: "Klimatologi", current: "Arus Laut", index: "Indeks Iklim", sal: "Salinitas", subt: "Suhu Bawah Permukaan" };
function hideSkeleton() {
  const s = $("skeleton");
  if (!s || s.classList.contains("hide")) return;
  s.classList.add("hide");                   // fade-out (transition CSS), lalu dilepas
  setTimeout(() => s.remove(), 500);
}
function clearRasterBar() { if (rasterBarTimer) { clearTimeout(rasterBarTimer); rasterBarTimer = null; } $("raster-bar").classList.remove("show"); }
function trackRaster(full) {
  const img = overlay && overlay.getElement();
  const seq = ++rasterSeq;                    // frame terbaru menang; listener frame lama diabaikan
  const settle = () => {
    if (seq !== rasterSeq) return;
    $("map-loading").classList.remove("show");
    clearRasterBar();
    hideSkeleton();                           // load-awal: lepas skeleton begitu raster pertama siap
  };
  if (!img || (img.complete && img.naturalWidth > 0)) { settle(); return; }   // sudah ter-cache
  if (full) {
    $("map-loading-text").textContent = "Memuat " + (LAYER_NAME[activeLayer] || "data") + "…";
    $("map-loading").classList.add("show");
  } else {
    clearRasterBar();
    rasterBarTimer = setTimeout(() => { if (seq === rasterSeq) $("raster-bar").classList.add("show"); }, 150);   // scrub cepat/ter-cache: jangan flash
  }
  img.addEventListener("load", settle, { once: true });
  img.addEventListener("error", settle, { once: true });
}

function showFrame(i, opts) {
  frameIdx = Math.max(0, Math.min(frames.length - 1, i));
  const f = frames[frameIdx];
  const d = state.domain;
  let bounds = [[d.latS, d.lonW], [d.latN, d.lonE]];
  if (activeLayer === "current" && state.currents && state.currents.bounds) {
    const cb = state.currents.bounds; bounds = [[cb.latS, cb.lonW], [cb.latN, cb.lonE]];   // grid arus sendiri
  } else if (activeLayer === "sal" && state.layers.sal && state.layers.sal.bounds) {
    const sb = state.layers.sal.bounds; bounds = [[sb.latS, sb.lonW], [sb.latN, sb.lonE]];  // grid salinitas Copernicus
  } else if (activeLayer === "subt" && state.layers.subt && state.layers.subt.bounds) {
    const sb = state.layers.subt.bounds; bounds = [[sb.latS, sb.lonW], [sb.latN, sb.lonE]];  // grid suhu-kedalaman Copernicus
  }
  const url = "data/output/" + (f.png || f.spd);   // arus: kontur kecepatan (spd)
  if (overlay) { overlay.setUrl(url); overlay.setBounds(bounds); }
  else overlay = L.imageOverlay(url, bounds, { opacity: 0.9, interactive: false, pane: "sst", className: "sst-overlay" }).addTo(map);
  trackRaster(opts && opts.layerSwitch);           // ganti layer -> skeleton; scrub/putar -> bar tipis
  $("valid-time").textContent = frameTimeLabel(f);
  $("time-slider").value = frameIdx;
  updateRangeFill();
  updateCurrents();
  if (pointActive && activeLayer !== "index") updatePointPopup();
  if ((activeLayer === "anom" || activeLayer === "index") && f.nino34 != null) liveIndex = f;
  if (activeLayer === "index") renderIndexDetail();
}

/* ---- Kedalaman terpadu: kedalaman 0 = permukaan (per-jam), >0 = lapisan bawah (harian).
   Suhu Laut: 0=SST, >0=subt. Arus: 0=arus permukaan, >0=arus kedalaman. ---- */
function tempFramesForDepth(d) {
  if (d === 0) return state.layers.sst.frames;
  return (state.layers.subt && state.layers.subt.frames[String(d - 1)]) || state.layers.sst.frames;
}
function curFramesForDepth(d) {
  if (d === 0) return state.currents.frames;
  return (state.currents.depth_frames && state.currents.depth_frames[String(d)]) || state.currents.frames;
}
function framesForDepth(d) { return activeLayer === "current" ? curFramesForDepth(d) : tempFramesForDepth(d); }
function depthLabels() {
  if (activeLayer === "current") return (state.currents && state.currents.depth_labels) || ["Permukaan"];
  if (activeLayer === "sst") return ["Permukaan / SST", ...((state.layers.subt && state.layers.subt.depth_labels) || [])];
  return [];
}
function hasDepth() { return activeLayer === "sst" || activeLayer === "current"; }

/* ---- Ganti layer (Suhu Laut / Arus / Anomali / ...) ---- */
function setLayer(key) {
  if (key === "current" && (!state.currents || !state.currents.frames || !state.currents.frames.length)) { toast("Data arus belum tersedia"); return; }
  if (key === "sal" && !(state.layers.sal && state.layers.sal.frames && state.layers.sal.frames.length)) { toast("Data salinitas belum tersedia"); return; }
  activeLayer = key;
  applyBasemap();   // gelap khusus anom, terang selainnya
  if (hasDepth() && selectedDepth >= depthLabels().length) selectedDepth = 0;   // clamp antar-layer
  frames = key === "current" ? curFramesForDepth(selectedDepth)
    : key === "sst" ? tempFramesForDepth(selectedDepth)
    : state.layers[FRAME_SRC[key]].frames;
  updateDepthBar();   // pemilih kedalaman di Suhu Laut & Arus
  document.querySelectorAll(".layer-btn").forEach((b) => b.classList.toggle("active", b.dataset.layer === key));
  document.querySelectorAll(".index-opt").forEach((o) => o.classList.remove("active"));   // keluar mode indeks
  renderLegend(key); buildTicks();
  $("time-slider").max = String(Math.max(0, frames.length - 1));
  clearZone();
  if (!pointActive) frameRegion();   // titik aktif: jangan reset view biar popup tetap di tempat
  openIndex(false);   // sidebar hanya untuk mode Indeks
  if (pointActive) { if (POINT_PARAM[key]) loadPD(POINT_PARAM[key].pd).then(() => updatePointPopup()); else closePoint(); }
  showFrame(nowIndex(), { layerSwitch: true });
}

/* ---- Pemilih kedalaman (Suhu Laut & Arus): slider VERTIKAL, permukaan di ATAS.
   Slider = input range yang diputar 90 derajat lewat CSS. Label tiap kedalaman
   punya kotak sendiri, ditaruh sejajar takiknya, dan tetap bisa diklik. ---- */
function updateDepthBar() {
  const labels = hasDepth() ? depthLabels() : [], n = labels.length;
  // Cuma satu pilihan berarti tak ada yang bisa dipilih, slidernya disembunyikan
  // saja daripada tampil sendirian dalam keadaan mati.
  $("depth-bar").hidden = n <= 1;
  if (n <= 1) return;
  syncDepthHeight();
  const rng = $("depth-range");
  rng.max = String(n - 1);
  rng.value = String(selectedDepth);
  $("depth-ticks").innerHTML = labels.map((lb, i) => {
    // Thumb slider tak pernah menyentuh ujung, selalu masuk setengah lebarnya
    // (8px dari 16px). Posisi label ikut dikurangi segitu biar benar-benar sejajar.
    const frac = n === 1 ? 0 : i / (n - 1);
    const pos = `calc(8px + (100% - 16px) * ${frac.toFixed(4)})`;
    const short = lb.split(" / ")[0];   // "Permukaan / SST" -> "Permukaan"
    return `<button type="button" class="depth-tick${i === selectedDepth ? " active" : ""}"` +
      ` data-depth="${i}" style="top:${pos}" title="${lb}">${short}</button>`;
  }).join("");
  $("depth-ticks").querySelectorAll(".depth-tick").forEach((b) =>
    b.addEventListener("click", () => setDepth(+b.dataset.depth)));
}

/* Panjang slider disamakan dengan tinggi panel Parameter di sebelah kiri.
   Harus diukur di JS karena elemen range diputar 90 derajat, jadi yang tampak
   sebagai tinggi sebenarnya lebar, dan lebar butuh angka pasti. Di lebar HP
   dilepas supaya nilai dari CSS yang dipakai, sebab panel Parameter di sana
   menciut jadi satu tombol saja. */
function syncDepthHeight() {
  const bar = $("depth-bar"), ref = document.querySelector(".layer-bar");
  if (!bar || !ref) return;
  if (window.innerWidth <= 640) { bar.style.removeProperty("--depth-h"); return; }
  const h = Math.round(ref.getBoundingClientRect().height);
  if (h > 0) bar.style.setProperty("--depth-h", h + "px");
}
function setDepth(i) {
  if (i === selectedDepth) return;
  selectedDepth = i;
  if (pointActive && i > 0) closePoint();   // klik-titik hanya untuk permukaan (pd kedalaman tak disimpan)
  frames = framesForDepth(i);
  $("time-slider").max = String(Math.max(0, frames.length - 1));
  updateDepthBar(); buildTicks();
  showFrame(nowIndex(), { layerSwitch: true });   // cadence bisa beda (per-jam <-> harian) -> resolve "kini"
}

/* ---- Ticks per cadence ---- */
function buildTicks() {
  const wrap = $("tl-ticks"), n = frames.length;
  if (!n) { wrap.innerHTML = ""; return; }
  let prev = null;
  wrap.innerHTML = frames.map((f, i) => {
    const pos = n === 1 ? 0 : (i / (n - 1)) * 100;
    const edge = i === 0 ? " edge-start" : (i === n - 1 ? " edge-end" : "");
    let lbl = "", isDay = false;
    if (activeLayer === "clim") { lbl = MONTHS[f.month - 1]; isDay = true; }
    else if (!f.valid_time && f.date) { lbl = `${+f.date.slice(6, 8)} ${MONTHS[+f.date.slice(4, 6) - 1]}`; isDay = true; }   // frame harian
    else { const w = toWIB(f.valid_time), day = w.getUTCDate(); isDay = i === 0 || day !== prev; prev = day; lbl = isDay ? `${day} ${MONTHS[w.getUTCMonth()]}` : ""; }
    return `<div class="tl-tick${isDay ? " day" : ""}${edge}" style="left:${pos}%"><span class="tl-tick-mark"></span>${lbl ? `<span class="tl-tick-lbl">${lbl}</span>` : ""}</div>`;
  }).join("");
}

/* ---- Panel Indeks (selector + detail per-indeks) ---- */
let liveIndex = null;  // frame anomali aktif (nilai indeks live)
function statusChip(s) {
  if (!s) return "chip-neutral";
  if (s.indexOf("El Nino") >= 0 || s.indexOf("Positif") >= 0 || s.indexOf("Hangat") >= 0) return "chip-warm";
  if (s.indexOf("La Nina") >= 0 || s.indexOf("Negatif") >= 0 || s.indexOf("Dingin") >= 0) return "chip-cool";
  return "chip-neutral";
}
function valClass(v) { if (v == null || isNaN(v)) return "v-neutral"; if (v >= 0.5) return "v-warm"; if (v <= -0.5) return "v-cool"; return "v-neutral"; }
function fmtSigned(v) { return (v >= 0 ? "+" : "") + Number(v).toFixed(2); }
function sparkPoints(vals, w, h) {
  if (!vals.length) return "";
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 0.4) { const m = (hi + lo) / 2; lo = m - 0.2; hi = m + 0.2; }
  const pad = 3;
  return vals.map((v, i) => `${(vals.length === 1 ? w / 2 : (i / (vals.length - 1)) * w).toFixed(1)},${(pad + (1 - (v - lo) / (hi - lo)) * (h - 2 * pad)).toFixed(1)}`).join(" ");
}
function ninoStatus(v) { return v >= 0.5 ? "El Nino" : v <= -0.5 ? "La Nina" : "Netral"; }
const INDEX_COLOR = { nino12: NINO_COLORS.nino12, nino3: NINO_COLORS.nino3, nino34: NINO_COLORS.nino34, nino4: NINO_COLORS.nino4, oni: "#7048e8", dmi: "#e64980" };
const INDEX_LABEL = { nino12: "Nino 1+2", nino3: "Nino 3", nino34: "Nino 3.4", nino4: "Nino 4", oni: "ONI", dmi: "DMI" };
const OBS_COLOR = "#1b5e9c", GFS_COLOR = "#e8590c";
const SINTEX_COLOR = "#2f9e44", SINTEX_FILL = "rgba(47,158,68,.16)";
function zoneKeyOf(k) { return k === "dmi" ? "iod" : k === "oni" ? "nino34" : k; }
function thrOf(k) { return k === "dmi" ? (state.iod_thresh || 0.4) : (state.enso_thresh || 0.5); }
function zoneTone(v, thr) { if (v == null || isNaN(v)) return "rgba(120,120,120,.45)"; if (v >= thr) return "rgba(214,96,77,.55)"; if (v <= -thr) return "rgba(33,102,172,.55)"; return "rgba(110,120,130,.4)"; }
function dnum(d) { return Date.UTC(+d.slice(0, 4), +d.slice(4, 6) - 1, +d.slice(6, 8)) / 864e5; }
// Sumbu Y "cantik": domain dibulatkan ke kelipatan rapi + tick berjarak sama (konsisten antar indeks)
function niceAxis(lo, hi) {
  let span = hi - lo; if (!(span > 0)) span = 1;
  const raw = span / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))), n = raw / mag;
  const step = (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
  const nlo = Math.floor(lo / step + 1e-9) * step, nhi = Math.ceil(hi / step - 1e-9) * step;
  const ticks = []; for (let v = nlo; v <= nhi + step * 1e-6; v += step) ticks.push(Math.round(v / step) * step);
  const dec = step >= 1 ? 0 : step >= 0.1 ? 1 : step >= 0.01 ? 2 : 3;
  return { lo: nlo, hi: nhi, step, ticks, dec };
}
function dlabel(d) { return `${+d.slice(6, 8)} ${MONTHS[+d.slice(4, 6) - 1]}`; }
function nowVal(key) {
  if (key === "dmi") return (liveIndex && liveIndex.dmi != null) ? liveIndex.dmi : state.iod.dmi_now;
  if (key === "oni") return state.enso.oni_latest ? state.enso.oni_latest.anom : null;
  return (liveIndex && liveIndex[key] != null) ? liveIndex[key] : state.enso.regions[key].now;
}

/* ---- Plot time-series indeks: OISST (observasi) + ekor GFS (prakiraan) ---- */
function indexPlotSVG(key) {
  const thr = thrOf(key);
  const W = 340, H = 184, padL = 30, padR = 10, padT = 12, padB = 30;
  const pw = W - padL - padR, ph = H - padT - padB, yTop = padT, yBot = padT + ph;
  let series, pts, oniMode = key === "oni";
  if (oniMode) {
    const off = (state.index_series.oni && state.index_series.oni.official) || [];
    series = [{ color: INDEX_COLOR.oni, dash: false, dots: true, data: off.map((r, i) => ({ x: i, v: r.v, lab: r.label })) }];
    pts = series[0].data;
  } else {
    const S = state.index_series[key] || { obs: [], gfs: [] };
    const obs = (S.obs || []).map((r) => ({ x: dnum(r.date), v: r.v, date: r.date }));
    const gfs = (S.gfs || []).map((r) => ({ x: dnum(r.date), v: r.v, date: r.date }));
    series = [{ color: OBS_COLOR, dash: false, dots: false, data: obs }, { color: GFS_COLOR, dash: true, dots: true, data: gfs }];
    pts = obs.concat(gfs);
  }
  pts = pts.filter((p) => p.v != null && !isNaN(p.v));
  if (!pts.length) return `<div class="ix-plot-empty">Data indeks belum tersedia.</div>`;
  const xmin = Math.min(...pts.map((p) => p.x)), xmax = Math.max(...pts.map((p) => p.x));
  const vals = pts.map((p) => p.v);
  let vlo = Math.min(...vals, -thr * 1.4), vhi = Math.max(...vals, thr * 1.4);
  const ax = niceAxis(vlo, vhi); vlo = ax.lo; vhi = ax.hi;
  const X = (x) => padL + (xmax === xmin ? pw / 2 : (x - xmin) / (xmax - xmin) * pw);
  const Y = (v) => padT + (1 - (v - vlo) / (vhi - vlo)) * ph;
  const cY = (v) => Math.max(yTop, Math.min(yBot, Y(v)));
  // pita zona (latar): hangat / netral / dingin
  const wB = cY(thr), cT = cY(-thr);
  let bands = "";
  if (wB > yTop) bands += `<rect x="${padL}" y="${yTop}" width="${pw}" height="${(wB - yTop).toFixed(1)}" fill="rgba(214,96,77,.10)"/>`;
  if (cT > wB) bands += `<rect x="${padL}" y="${wB.toFixed(1)}" width="${pw}" height="${(cT - wB).toFixed(1)}" fill="rgba(110,120,130,.05)"/>`;
  if (yBot > cT) bands += `<rect x="${padL}" y="${cT.toFixed(1)}" width="${pw}" height="${(yBot - cT).toFixed(1)}" fill="rgba(33,102,172,.10)"/>`;
  const hline = (v, st, dash) => { const y = Y(v); return (y < yTop || y > yBot) ? "" : `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${padL + pw}" y2="${y.toFixed(1)}" stroke="${st}" stroke-width="1"${dash ? ' stroke-dasharray="3 3"' : ""}/>`; };
  const guides = hline(0, "rgba(28,27,27,.35)", false) + hline(thr, "rgba(214,96,77,.5)", true) + hline(-thr, "rgba(33,102,172,.5)", true);
  const poly = (s) => {
    const d = s.data.filter((p) => p.v != null && !isNaN(p.v)); if (!d.length) return "";
    const pl = `<polyline points="${d.map((p) => `${X(p.x).toFixed(1)},${Y(p.v).toFixed(1)}`).join(" ")}" fill="none" stroke="${s.color}" stroke-width="2"${s.dash ? ' stroke-dasharray="4 3"' : ""} stroke-linejoin="round" stroke-linecap="round"/>`;
    const dots = s.dots ? d.map((p) => `<circle cx="${X(p.x).toFixed(1)}" cy="${Y(p.v).toFixed(1)}" r="2.3" fill="${s.color}"/>`).join("") : "";
    return pl + dots;
  };
  const lines = series.map(poly).join("");
  // gap seam OISST->GFS, diarsir warna zona
  let seam = "";
  if (!oniMode) {
    const obs = series[0].data.filter((p) => p.v != null), gfs = series[1].data.filter((p) => p.v != null);
    if (obs.length && gfs.length) {
      const a = obs[obs.length - 1], b = gfs[0], sx = (X(a.x) + X(b.x)) / 2, yA = Y(a.v), yB = Y(b.v);
      seam = `<line x1="${X(a.x).toFixed(1)}" y1="${yA.toFixed(1)}" x2="${X(b.x).toFixed(1)}" y2="${yB.toFixed(1)}" stroke="rgba(28,27,27,.3)" stroke-width="1" stroke-dasharray="2 2"/>` +
        `<rect x="${(sx - 3).toFixed(1)}" y="${Math.min(yA, yB).toFixed(1)}" width="6" height="${Math.max(1, Math.abs(yA - yB)).toFixed(1)}" fill="${zoneTone((a.v + b.v) / 2, thr)}"/>`;
    }
  }
  // penanda "kini" (posisi slider)
  let nowm = "";
  if (!oniMode && frames[frameIdx] && frames[frameIdx].date) { const nx = X(dnum(frames[frameIdx].date)); if (nx >= padL && nx <= padL + pw) nowm = `<line x1="${nx.toFixed(1)}" y1="${yTop}" x2="${nx.toFixed(1)}" y2="${yBot}" stroke="#f59f00" stroke-width="1.5"/>`; }
  const yfmt = (v) => Math.abs(v) < 1e-9 ? (0).toFixed(ax.dec) : (v > 0 ? "+" : "") + v.toFixed(ax.dec);
  const ylab = (v) => `<text x="${padL - 4}" y="${(Y(v) + 3).toFixed(1)}" text-anchor="end" class="ix-axl">${yfmt(v)}</text>`;
  const yaxis = ax.ticks.map(ylab).join("");
  let xaxis;
  if (oniMode) {
    const n = series[0].data.length, step = Math.max(1, Math.round(n / 4));
    const idx = []; for (let i = 0; i < n; i += step) idx.push(i); if (idx[idx.length - 1] !== n - 1) idx.push(n - 1);
    xaxis = idx.map((i) => series[0].data[i] ? `<text x="${X(i).toFixed(1)}" y="${H - 8}" text-anchor="${i === 0 ? "start" : i === n - 1 ? "end" : "middle"}" class="ix-axl">${series[0].data[i].lab}</text>` : "").join("");
  } else {
    // tick tiap hari dari xmin..xmax (termasuk hari tanpa data, biar tak ada lompatan tanggal)
    const d0 = Math.round(xmin), d1 = Math.round(xmax), nd = d1 - d0 + 1;
    const stepD = Math.max(1, Math.ceil(nd / 9));
    const days = []; for (let x = d0; x <= d1; x += stepD) days.push(x);
    if (days[days.length - 1] !== d1) days.push(d1);
    xaxis = days.map((x, i) => {
      const dt = new Date(x * 864e5), dd = dt.getUTCDate(), mo = dt.getUTCMonth() + 1;
      const xx = X(x), anch = i === 0 ? "start" : i === days.length - 1 ? "end" : "middle";
      return `<line x1="${xx.toFixed(1)}" y1="${yBot}" x2="${xx.toFixed(1)}" y2="${(yBot + 3).toFixed(1)}" stroke="rgba(28,27,27,.4)" stroke-width="1"/><text x="${xx.toFixed(1)}" y="${H - 8}" text-anchor="${anch}" class="ix-axl">${dd}/${mo}</text>`;
    }).join("");
  }
  return `<svg class="ix-plot-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${bands}${guides}${seam}${lines}${nowm}${yaxis}${xaxis}</svg>`;
}

/* ---- Plot musiman SINTEX-F (JAMSTEC): observasi + prakiraan + pita ensemble, bulanan ---- */
function seasonPlotSVG(key) {
  const season = state.season_forecast && state.season_forecast[key];
  if (!season) return "";
  const sObs = (season.obs || []).map((r) => ({ x: dnum(r.date), v: r.v, date: r.date }));
  const sFc = (season.fcst || []).map((r) => ({ x: dnum(r.date), v: r.v, date: r.date, lo: r.lo, hi: r.hi }));
  if (!sObs.length && !sFc.length) return "";
  const fcLine = sObs.length ? [sObs[sObs.length - 1]].concat(sFc) : sFc;   // sambung obs -> prakiraan
  const thr = thrOf(key);
  const W = 340, H = 184, padL = 30, padR = 10, padT = 12, padB = 30;
  const pw = W - padL - padR, ph = H - padT - padB, yTop = padT, yBot = padT + ph;
  const pts = sObs.concat(sFc);
  const xmin = Math.min(...pts.map((p) => p.x)), xmax = Math.max(...pts.map((p) => p.x));
  const vals = pts.map((p) => p.v);
  for (const r of sFc) { if (r.lo != null) vals.push(r.lo); if (r.hi != null) vals.push(r.hi); }
  let vlo = Math.min(...vals, -thr * 1.4), vhi = Math.max(...vals, thr * 1.4);
  const ax = niceAxis(vlo, vhi); vlo = ax.lo; vhi = ax.hi;
  const X = (x) => padL + (xmax === xmin ? pw / 2 : (x - xmin) / (xmax - xmin) * pw);
  const Y = (v) => padT + (1 - (v - vlo) / (vhi - vlo)) * ph;
  const cY = (v) => Math.max(yTop, Math.min(yBot, Y(v)));
  const wB = cY(thr), cT = cY(-thr);
  let bands = "";
  if (wB > yTop) bands += `<rect x="${padL}" y="${yTop}" width="${pw}" height="${(wB - yTop).toFixed(1)}" fill="rgba(214,96,77,.10)"/>`;
  if (cT > wB) bands += `<rect x="${padL}" y="${wB.toFixed(1)}" width="${pw}" height="${(cT - wB).toFixed(1)}" fill="rgba(110,120,130,.05)"/>`;
  if (yBot > cT) bands += `<rect x="${padL}" y="${cT.toFixed(1)}" width="${pw}" height="${(yBot - cT).toFixed(1)}" fill="rgba(33,102,172,.10)"/>`;
  const hline = (v, st, dash) => { const y = Y(v); return (y < yTop || y > yBot) ? "" : `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${padL + pw}" y2="${y.toFixed(1)}" stroke="${st}" stroke-width="1"${dash ? ' stroke-dasharray="3 3"' : ""}/>`; };
  const guides = hline(0, "rgba(28,27,27,.35)", false) + hline(thr, "rgba(214,96,77,.5)", true) + hline(-thr, "rgba(33,102,172,.5)", true);
  let band = "";
  const b = sFc.filter((r) => r.lo != null && r.hi != null);
  if (b.length >= 2) {
    const top = b.map((r) => `${X(r.x).toFixed(1)},${cY(r.hi).toFixed(1)}`);
    const bot = b.slice().reverse().map((r) => `${X(r.x).toFixed(1)},${cY(r.lo).toFixed(1)}`);
    band = `<polygon points="${top.concat(bot).join(" ")}" fill="${SINTEX_FILL}" stroke="none"/>`;
  }
  const line = (data, dash, dots) => {
    const d = data.filter((p) => p.v != null && !isNaN(p.v)); if (!d.length) return "";
    const pl = `<polyline points="${d.map((p) => `${X(p.x).toFixed(1)},${Y(p.v).toFixed(1)}`).join(" ")}" fill="none" stroke="${SINTEX_COLOR}" stroke-width="2"${dash ? ' stroke-dasharray="4 3"' : ""} stroke-linejoin="round" stroke-linecap="round"/>`;
    const dd = dots ? d.map((p) => `<circle cx="${X(p.x).toFixed(1)}" cy="${Y(p.v).toFixed(1)}" r="2.2" fill="${SINTEX_COLOR}"/>`).join("") : "";
    return pl + dd;
  };
  const lines = line(sObs, false, false) + line(fcLine, true, true);
  // penanda "kini" (batas observasi -> prakiraan)
  let nowm = "";
  const nx0 = sObs.length ? sObs[sObs.length - 1].x : (sFc.length ? sFc[0].x : null);
  if (nx0 != null) { const nx = X(nx0); if (nx >= padL && nx <= padL + pw) nowm = `<line x1="${nx.toFixed(1)}" y1="${yTop}" x2="${nx.toFixed(1)}" y2="${yBot}" stroke="#f59f00" stroke-width="1.5"/>`; }
  const yfmt = (v) => Math.abs(v) < 1e-9 ? (0).toFixed(ax.dec) : (v > 0 ? "+" : "") + v.toFixed(ax.dec);
  const yaxis = ax.ticks.map((v) => `<text x="${padL - 4}" y="${(Y(v) + 3).toFixed(1)}" text-anchor="end" class="ix-axl">${yfmt(v)}</text>`).join("");
  const months = [...new Set(pts.map((p) => p.date.slice(0, 6)))].sort();
  const nm = months.length, target = Math.min(6, nm);
  const pick = new Set();
  for (let i = 0; i < target; i++) pick.add(Math.round(i * (nm - 1) / Math.max(1, target - 1)));
  const xaxis = [...pick].sort((a, b) => a - b).map((mi) => {
    const ym = months[mi], xx = X(dnum(ym + "15")), mo = +ym.slice(4, 6), yr = ym.slice(2, 4);
    const lab = (mo === 1 || mi === 0) ? `${MONTHS[mo - 1]} ${yr}` : MONTHS[mo - 1];
    const anch = mi === 0 ? "start" : mi === nm - 1 ? "end" : "middle";
    return `<line x1="${xx.toFixed(1)}" y1="${yBot}" x2="${xx.toFixed(1)}" y2="${(yBot + 3).toFixed(1)}" stroke="rgba(28,27,27,.4)" stroke-width="1"/><text x="${xx.toFixed(1)}" y="${H - 8}" text-anchor="${anch}" class="ix-axl">${lab}</text>`;
  }).join("");
  return `<svg class="ix-plot-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${bands}${guides}${band}${lines}${nowm}${yaxis}${xaxis}</svg>`;
}
function plotBlock(title, svg, legend) {
  return `<div class="ix-plot-ttl">${title}</div>${svg}<div class="ix-plot-lg">${legend}</div>`;
}
function renderIndexPlot() {
  const box = $("ix-plot"); if (!box) return;
  const k = selectedIndex;
  const season = state.season_forecast && state.season_forecast[k];
  const obsClim = state.obs_clim || "COBE 1991-2020";
  if (k === "oni") {
    const lg = `<span class="ix-lg"><i style="background:${INDEX_COLOR.oni}"></i>ONI resmi CPC (rata 3 bln)</span>`;
    box.innerHTML = plotBlock(`Indeks ${INDEX_LABEL[k]}`, indexPlotSVG(k), lg);
    return;
  }
  // Plot 1: harian OISST (observasi) + GFS (prakiraan)
  const lgDaily = `<span class="ix-lg"><i style="background:${OBS_COLOR}"></i>OISST observasi</span>`
    + `<span class="ix-lg"><i class="dash" style="border-top-color:${GFS_COLOR}"></i>CMEMS prakiraan</span>`
    + `<span class="ix-lg-note">Klimatologi ${obsClim}</span>`;
  const dailyTitle = season ? `Indeks ${INDEX_LABEL[k]} · harian` : `Indeks ${INDEX_LABEL[k]}`;
  let html = plotBlock(dailyTitle, indexPlotSVG(k), lgDaily);
  // Plot 2 (hanya Nino 3.4 & DMI): prakiraan musiman SINTEX-F
  if (season) {
    const lgSeason = `<span class="ix-lg"><i style="background:${SINTEX_COLOR}"></i>Observasi</span>`
      + `<span class="ix-lg"><i class="dash" style="border-top-color:${SINTEX_COLOR}"></i>Prakiraan</span>`
      + `<span class="ix-lg"><i class="band" style="background:${SINTEX_FILL}"></i>sebaran ensemble (10-90%)</span>`
      + `<span class="ix-lg-note">Klimatologi ${state.season_clim || "1983-2015"}, ${state.season_source || "JAMSTEC"}</span>`;
    html += `<div class="ix-plot-sec">` + plotBlock(`Prakiraan musiman ${INDEX_LABEL[k]}`, seasonPlotSVG(k), lgSeason) + `</div>`;
  }
  box.innerHTML = html;
}
function enterIndexMode() {
  if (activeLayer !== "index") lastLayer = activeLayer;   // ingat layer semula
  activeLayer = "index";
  applyBasemap();   // mode Indeks pakai basemap terang (bukan anom)
  closePoint();   // mode Indeks ambil alih panel
  frames = state.layers.anom.frames;
  document.querySelectorAll(".layer-btn").forEach((b) => b.classList.remove("active"));
  renderLegend("anom"); buildTicks();
  $("time-slider").max = String(Math.max(0, frames.length - 1));
  openIndex(true);
  showFrame(nowIndex(), { layerSwitch: true });
}
function buildIndexPanel() {
  $("pt-badge").textContent = "INDEKS IKLIM";
  $("ip-status").textContent = state.data_date ? `${state.data_date.slice(6, 8)} ${MONTHS[+state.data_date.slice(4, 6) - 1]} ${state.data_date.slice(0, 4)}` : "";
  $("ip-cards").innerHTML = `<div class="ix-plot-wrap" id="ix-plot"></div><div class="ip-detail" id="ip-detail"></div>`;
  renderIndexPlot(); renderIndexDetail();
}
function selectIndex(key) {
  if (!key) return;
  selectedIndex = key;
  if (activeLayer !== "index") enterIndexMode();
  document.querySelectorAll(".index-opt").forEach((o) => o.classList.toggle("active", o.dataset.ix === key));
  const zk = zoneKeyOf(key); showZone(zk); zoomZone(zk);
  buildIndexPanel();
}
function exitIndexMode() {
  const bar = $("index-toggle").parentElement; if (bar) bar.classList.remove("open");
  setLayer(lastLayer || "sst");   // balik ke layer parameter semula (bersihkan index-opt, zona, tutup panel)
}
function renderIndexDetail() {
  const box = $("ip-detail"); if (!box) return;
  const k = selectedIndex, v = nowVal(k);
  if (k === "dmi") {
    box.innerHTML = `<div class="ip-row"><span class="label-caps">DMI · Dipol Samudra Hindia</span><span class="chip ${statusChip(state.iod.status)}">${state.iod.status || "-"}</span></div>
      <div class="ip-big"><span class="${valClass(v)}">${fmtSigned(v)}</span><span class="unit">°C</span></div>`;
    return;
  }
  if (k === "oni") {
    const oni = state.enso.oni_latest;
    box.innerHTML = `<div class="ip-row"><span class="label-caps">ONI · ENSO resmi</span><span class="chip ${statusChip(state.enso.status)}">${state.enso.status || "-"}</span></div>
      <div class="ip-big"><span class="${valClass(v)}">${v == null ? "–" : fmtSigned(v)}</span><span class="unit">°C</span></div>`;
    return;
  }
  const reg = state.enso.regions[k];
  box.innerHTML = `<div class="ip-row"><span class="label-caps">${reg.label}</span><span class="chip ${statusChip(ninoStatus(v))}">${ninoStatus(v)}</span></div>
    <div class="ip-big"><span class="${valClass(v)}">${fmtSigned(v)}</span><span class="unit">°C</span></div>`;
}

/* ================= Klik-titik: nilai dari grid mentah (point_data) ================= */
let pdArr = {}, pointActive = false, pointLat = null, pointLon = null, pointPopup = null, pointMarker = null;
async function loadPD(key) {
  if (pdArr[key] !== undefined) return pdArr[key];
  const m = state.point_data && state.point_data[key];
  if (!m) { pdArr[key] = null; return null; }
  try {
    const buf = await fetch("data/output/" + m.file, { cache: "no-store" }).then((r) => r.arrayBuffer());
    const stream = new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip")));
    pdArr[key] = new Int16Array(await stream.arrayBuffer());
  } catch (e) { pdArr[key] = null; }
  return pdArr[key];
}
function sampleGrid(arr, m, ti, lat, lon, comp) {
  if (!arr || !m) return null;
  const nx = m.nx, ny = m.ny, nt = m.nt || 1;
  const base = (((comp || 0) * nt) + ti) * ny * nx;
  const fx = (lon - m.west) / (m.east - m.west) * (nx - 1);
  const fy = (m.north - lat) / (m.north - m.south) * (ny - 1);
  if (fx < -0.5 || fx > nx - 0.5 || fy < -0.5 || fy > ny - 0.5) return null;
  const x0 = Math.max(0, Math.min(nx - 1, Math.floor(fx))), y0 = Math.max(0, Math.min(ny - 1, Math.floor(fy)));
  const x1 = Math.min(x0 + 1, nx - 1), y1 = Math.min(y0 + 1, ny - 1), tx = fx - x0, ty = fy - y0;
  const g = (x, y) => { const val = arr[base + y * nx + x]; return val <= -32000 ? null : val * m.scale; };   // sentinel NaN (-32768 atau -32767 hasil clip pack_grid)
  const q = [[g(x0, y0), (1 - tx) * (1 - ty)], [g(x1, y0), tx * (1 - ty)], [g(x0, y1), (1 - tx) * ty], [g(x1, y1), tx * ty]];
  let s = 0, w = 0;
  for (const [val, wt] of q) if (val != null) { s += val * wt; w += wt; }
  return w > 0 ? s / w : null;
}
function tiByDate(m, date) { const a = (m.dates || []).indexOf(date); return a < 0 ? 0 : a; }
function tiSstFor(m, f) {
  if (activeLayer === "sst") return frameIdx;
  const d = frameDateOf(f), i = (m.times || []).findIndex((t) => t.slice(0, 10).replace(/-/g, "") === d);
  return i < 0 ? (m.times ? m.times.length - 1 : 0) : i;
}
const COMPASS = ["Utara", "Timur Laut", "Timur", "Tenggara", "Selatan", "Barat Daya", "Barat", "Barat Laut"];
function dirLabel(u, v) {
  const deg = (Math.atan2(u, v) * 180 / Math.PI + 360) % 360;   // arah ALIRAN menuju (0=U, 90=T)
  return `${COMPASS[Math.round(deg / 45) % 8]} (${Math.round(deg)}°)`;
}
// Parameter yang punya data titik (klim tak ada point_data)
const POINT_PARAM = {
  sst:     { pd: "sst",  label: "Suhu Muka Laut", unit: "°C",  color: "#ef780d", signed: false },
  anom:    { pd: "anom", label: "Anomali SST",    unit: "°C",  color: "#e8590c", signed: true },
  current: { pd: "cur",  label: "Arus Laut",      unit: "m/s", color: "#0d9488", signed: false, vector: true },
  clim:    { pd: "clim", label: "Klimatologi SST", unit: "°C", color: "#2b8a9e", signed: false },
  sal:     { pd: "sal",  label: "Salinitas",      unit: "PSU", color: "#1b9e8a", signed: false },
};
function ptXlabel(f) {
  if (!f) return "";
  if (f.valid_time) { const w = toWIB(f.valid_time); return `${w.getUTCDate()}/${w.getUTCMonth() + 1}`; }
  if (f.date) return `${+f.date.slice(6, 8)}/${+f.date.slice(4, 6)}`;
  if (f.month) return MONTHS[f.month - 1];
  return "";
}
// Sumbu waktu deret titik diambil dari pd SENDIRI (harian/bulanan), bukan dari frames tampilan
// (SST kini per-jam tapi pd-nya harian) -> label & indeks-kini dipetakan lewat tanggal.
function pdTimeArr(pd) { return pd.dates || pd.months || pd.times || []; }
function pdLabel(pd, i) {
  if (pd.dates) { const d = pd.dates[i]; return `${+d.slice(6, 8)}/${+d.slice(4, 6)}`; }
  if (pd.months) return MONTHS[pd.months[i] - 1];
  if (pd.times) { const w = toWIB(pd.times[i]); return `${w.getUTCDate()}/${w.getUTCMonth() + 1}`; }
  return "";
}
function pdCurIdx(pd, f) {
  if (pd.dates) {
    const d = frameDateOf(f), j = pd.dates.indexOf(d);
    if (j >= 0) return j;
    let best = pd.dates.length - 1, bd = Infinity;
    pd.dates.forEach((x, k) => { const dd = Math.abs(+x - +d); if (dd < bd) { bd = dd; best = k; } });
    return best;
  }
  if (pd.months) { const j = pd.months.indexOf(f.month); return j < 0 ? 0 : j; }
  return Math.min(frameIdx, pdTimeArr(pd).length - 1);
}
function pointSeries(param) {
  const pd = state.point_data && state.point_data[param.pd], arr = pdArr[param.pd];
  if (!pd || !arr) return null;
  const n = pdTimeArr(pd).length;
  const vals = [];
  for (let i = 0; i < n; i++) {
    if (param.vector) {
      const u = sampleGrid(arr, pd, i, pointLat, pointLon, 0), v = sampleGrid(arr, pd, i, pointLat, pointLon, 1);
      vals.push((u == null || v == null) ? null : { spd: Math.hypot(u, v), u, v });
    } else vals.push(sampleGrid(arr, pd, i, pointLat, pointLon, 0));
  }
  return { pd, vals, n };
}
// Plot time-series di titik: sumbu X waktu (ikut slider), sumbu Y nilai + satuan
function pointPlotSVG(nums, param, curIdx, pd) {
  const n = nums.length, good = nums.filter((v) => v != null && !isNaN(v));
  if (good.length < 2) return `<div class="kf-pop-empty">Tak ada deret di titik ini.</div>`;
  const W = 264, H = 120, padL = 48, padR = 8, padT = 12, padB = 20;
  const pw = W - padL - padR, ph = H - padT - padB, yTop = padT, yBot = padT + ph;
  let vlo = Math.min(...good), vhi = Math.max(...good);
  if (param.signed) { vlo = Math.min(vlo, 0); vhi = Math.max(vhi, 0); }
  if (vhi - vlo < 1e-6) { vhi += 0.5; vlo -= 0.5; }
  const ax = niceAxis(vlo, vhi); vlo = ax.lo; vhi = ax.hi;
  const X = (i) => padL + (n === 1 ? pw / 2 : i / (n - 1) * pw);
  const Y = (v) => padT + (1 - (v - vlo) / (vhi - vlo)) * ph;
  const zero = (param.signed && 0 >= vlo && 0 <= vhi) ? `<line x1="${padL}" y1="${Y(0).toFixed(1)}" x2="${padL + pw}" y2="${Y(0).toFixed(1)}" stroke="rgba(28,27,27,.3)" stroke-width="1"/>` : "";
  const pts = nums.map((v, i) => (v == null || isNaN(v)) ? null : `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).filter(Boolean).join(" ");
  const line = `<polyline points="${pts}" fill="none" stroke="${param.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  const ci = Math.min(curIdx, n - 1), cv = nums[ci], nxp = X(ci);
  const nowm = `<line x1="${nxp.toFixed(1)}" y1="${yTop}" x2="${nxp.toFixed(1)}" y2="${yBot}" stroke="#f59f00" stroke-width="1.5"/>` +
    (cv != null && !isNaN(cv) ? `<circle cx="${nxp.toFixed(1)}" cy="${Y(cv).toFixed(1)}" r="2.8" fill="${param.color}" stroke="#fff" stroke-width="1"/>` : "");
  const AX = "rgba(28,27,27,.55)";
  const axisLines = `<line x1="${padL}" y1="${yTop}" x2="${padL}" y2="${yBot}" stroke="${AX}" stroke-width="1"/><line x1="${padL}" y1="${yBot}" x2="${(padL + pw).toFixed(1)}" y2="${yBot}" stroke="${AX}" stroke-width="1"/>`;
  const yfmt = (v) => param.signed ? (Math.abs(v) < 1e-9 ? (0).toFixed(ax.dec) : (v > 0 ? "+" : "") + v.toFixed(ax.dec)) : v.toFixed(ax.dec);
  const yaxis = ax.ticks.map((v) => `<line x1="${padL - 3}" y1="${Y(v).toFixed(1)}" x2="${padL}" y2="${Y(v).toFixed(1)}" stroke="${AX}" stroke-width="1"/><text x="${padL - 5}" y="${(Y(v) + 3).toFixed(1)}" text-anchor="end" class="kf-axl">${yfmt(v)}</text>`).join("");
  const uy = padT + ph / 2;
  const ulab = `<text x="11" y="${uy.toFixed(1)}" text-anchor="middle" transform="rotate(-90 11 ${uy.toFixed(1)})" class="kf-axl kf-axunit">${param.unit}</text>`;
  // satu tick per tanggal (frame pertama tiap label) -> konsisten, tak ada tanggal yang lompat
  const seenD = new Set(); let dayIdx = [];
  for (let i = 0; i < n; i++) { const lab = pdLabel(pd, i); if (lab && !seenD.has(lab)) { seenD.add(lab); dayIdx.push(i); } }
  if (dayIdx.length > 6) { const st = Math.ceil(dayIdx.length / 6); dayIdx = dayIdx.filter((_, j) => j % st === 0 || j === dayIdx.length - 1); }
  const xaxis = dayIdx.map((i) => {
    const anch = i === 0 ? "start" : i >= n - 1 ? "end" : "middle";
    return `<line x1="${X(i).toFixed(1)}" y1="${yBot}" x2="${X(i).toFixed(1)}" y2="${(yBot + 3).toFixed(1)}" stroke="${AX}" stroke-width="1"/><text x="${X(i).toFixed(1)}" y="${H - 4}" text-anchor="${anch}" class="kf-axl">${pdLabel(pd, i)}</text>`;
  }).join("");
  return `<svg class="kf-pop-plot" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${axisLines}${zero}${line}${nowm}${yaxis}${ulab}${xaxis}</svg>`;
}
function pointPopupHTML() {
  const param = POINT_PARAM[activeLayer];
  const lonDisp = ((pointLon + 540) % 360) - 180;
  const coord = `${pointLat.toFixed(2)}°, ${lonDisp.toFixed(2)}°`;
  if (!param) return `<div class="kf-pop-ttl">Titik</div><div class="kf-pop-empty">Pilih SST, Anomali, atau Arus.</div>`;
  const s = pointSeries(param);
  if (!s) return `<div class="kf-pop-ttl">${param.label}</div><div class="kf-pop-coord">${coord}</div><div class="kf-pop-empty">Data titik belum siap.</div>`;
  const idx = pdCurIdx(s.pd, frames[frameIdx]), cur = s.vals[idx];   // petakan frame tampilan -> indeks pd
  let big, nums, dirLine = "";
  if (param.vector) {
    nums = s.vals.map((o) => o ? o.spd : null);
    big = cur ? cur.spd.toFixed(2) : "–";
    dirLine = cur ? `<div class="kf-pop-sub">Arah aliran ${dirLabel(cur.u, cur.v)} · Copernicus</div>` : `<div class="kf-pop-sub">di darat / luar data</div>`;
  } else {
    nums = s.vals;
    big = (cur == null) ? "–" : (param.signed ? fmtSigned(cur) : cur.toFixed(1));
  }
  const bigCls = (param.signed && cur != null) ? valClass(cur) : "";
  return `<div class="kf-pop-ttl">${param.label}</div>
    <div class="kf-pop-coord">${coord}</div>
    <div class="kf-pop-big"><span class="${bigCls}">${big}</span> <span class="kf-pop-unit">${param.unit}</span></div>
    ${dirLine}${pointPlotSVG(nums, param, idx, s.pd)}`;
}
function setPointMarker(lat, lon) {
  const ll = [lat, nlng(lon)];
  if (pointMarker) pointMarker.setLatLng(ll);
  else pointMarker = L.marker(ll, { icon: L.divIcon({ className: "pt-marker", html: "", iconSize: [16, 16] }), interactive: false, pane: "boxes" }).addTo(map);
}
async function openPoint(lat, lon) {
  if (activeLayer === "index") return;
  if ((activeLayer === "sst" || activeLayer === "current") && selectedDepth > 0) { toast("Klik-titik hanya untuk permukaan"); return; }   // pd kedalaman tak disimpan
  const param = POINT_PARAM[activeLayer];
  if (!param) { toast("Klik titik untuk SST, Anomali SST, atau Arus Laut"); return; }
  pointActive = true; pointLat = lat; pointLon = lon;
  setPointMarker(lat, lon);
  await loadPD(param.pd);
  if (!pointActive) return;
  if (!pointPopup) pointPopup = L.popup({ className: "kf-pop", autoPan: true, maxWidth: 300, minWidth: 282, autoPanPadding: [24, 24], closeOnClick: false, autoClose: false });
  pointPopup.setLatLng([lat, nlng(lon)]).setContent(pointPopupHTML()).openOn(map);
}
function updatePointPopup() {
  if (pointActive && pointPopup && pointPopup.isOpen()) pointPopup.setContent(pointPopupHTML());
}
function closePoint() {
  pointActive = false;
  if (pointMarker) { map.removeLayer(pointMarker); pointMarker = null; }
  if (pointPopup) { const p = pointPopup; pointPopup = null; map.closePopup(p); }
}
map.on("popupclose", (e) => {
  if (e.popup && e.popup.options.className === "kf-pop") {
    pointActive = false; pointPopup = null;
    if (pointMarker) { map.removeLayer(pointMarker); pointMarker = null; }
  }
});
map.on("click", (e) => { if (activeLayer !== "index") openPoint(e.latlng.lat, e.latlng.lng); });

/* ---- Timeline ---- */
function updateRangeFill() {
  const sl = $("time-slider"), pct = sl.max > 0 ? (sl.value / sl.max) * 100 : 0;
  sl.style.background = `linear-gradient(90deg,var(--lime) ${pct}%,var(--surface-low) ${pct}%)`;
}
function afterFrame() { if (activeLayer === "index") { renderIndexDetail(); renderIndexPlot(); } }
$("time-slider").addEventListener("input", (e) => { if (playing) togglePlay(); showFrame(+e.target.value); afterFrame(); });
$("depth-range").addEventListener("input", (e) => setDepth(+e.target.value));
window.addEventListener("resize", syncDepthHeight);
if (document.fonts && document.fonts.ready) document.fonts.ready.then(syncDepthHeight);
function togglePlay() {
  playing = !playing;
  $("play-icon").textContent = playing ? "pause" : "play_arrow";
  if (playing) playTimer = setInterval(() => { showFrame((frameIdx + 1) % frames.length); afterFrame(); }, 900);
  else clearInterval(playTimer);
}
$("play-btn").addEventListener("click", togglePlay);
document.querySelectorAll(".layer-btn").forEach((b) => b.addEventListener("click", () => setLayer(b.dataset.layer)));
$("index-toggle").addEventListener("click", (e) => e.currentTarget.parentElement.classList.toggle("open"));
$("model-toggle").addEventListener("click", (e) => e.currentTarget.parentElement.classList.toggle("open"));
document.querySelectorAll(".index-opt").forEach((b) => b.addEventListener("click", () => {
  if (activeLayer === "index" && selectedIndex === b.dataset.ix) exitIndexMode();   // pencet lagi = matikan
  else selectIndex(b.dataset.ix);
}));

/* ---- Panel Indeks show/hide (pakai #point-panel) ---- */
function openIndex(open) {
  const p = $("point-panel");
  p.classList.toggle("open", open); p.classList.toggle("hidden", !open);
  $("pt-reopen").classList.toggle("show", false);
  $("ui").classList.toggle("ip-open", open);
}
$("pt-hide").addEventListener("click", () => { openIndex(false); $("pt-reopen").classList.add("show"); });
$("pt-reopen").addEventListener("click", () => { if (activeLayer === "index") openIndex(true); });
// Tombol X: matikan mode aktif (titik / indeks) lalu tutup panel
$("pt-off").addEventListener("click", () => {
  if (pointActive) { closePoint(); openIndex(false); $("pt-reopen").classList.remove("show"); }
  else if (activeLayer === "index") exitIndexMode();
  else { openIndex(false); $("pt-reopen").classList.remove("show"); }
});

/* ---- Tentang ---- */
const aboutOverlay = $("about-overlay");
$("nav-arrow").addEventListener("click", () => $("nav-arrow").closest(".brand-row").classList.toggle("nav-open"));
$("about-btn").addEventListener("click", () => aboutOverlay.classList.add("show"));
$("about-close").addEventListener("click", () => aboutOverlay.classList.remove("show"));
aboutOverlay.addEventListener("click", (e) => { if (e.target === aboutOverlay) aboutOverlay.classList.remove("show"); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") aboutOverlay.classList.remove("show"); });

/* ---- Kontrol lain ---- */
$("zoom-in").addEventListener("click", () => map.zoomIn());
$("zoom-out").addEventListener("click", () => map.zoomOut());
$("fs-btn").addEventListener("click", () => {
  $("stage").classList.toggle("immersive");
  if (!document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {});
  else document.exitFullscreen?.();
  setTimeout(() => map.invalidateSize(), 60);
});
$("zones-btn").addEventListener("click", () => setZones(!zonesOn));
$("share-btn").addEventListener("click", async () => {
  try { if (navigator.share) await navigator.share({ title: "Kertas Fenomena", url: location.href }); else { await navigator.clipboard.writeText(location.href); toast("Link disalin"); } } catch (_) {}
});
function toast(m) { const t = $("toast"); t.textContent = m; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 1800); }
$("ctrl-toggle").addEventListener("click", (e) => e.currentTarget.parentElement.classList.toggle("ctrl-open"));
$("param-toggle").addEventListener("click", (e) => e.currentTarget.parentElement.classList.toggle("param-open"));
$("data-fresh").addEventListener("click", () => $("data-fresh").classList.toggle("open"));

/* ---- Init ---- */
/* ---- Ringkasan awam otomatis: terjemahkan kondisi ENSO/IOD -> kalimat + dampak Indonesia ---- */
function ensoStrength(oni) {
  const a = Math.abs(oni);
  if (a < 0.5) return ""; if (a < 1.0) return "lemah"; if (a < 1.5) return "sedang";
  if (a < 2.0) return "kuat"; return "sangat kuat";
}
function laySummary() {
  const es = state.enso.status || "Netral";                         // El Nino / La Nina / Netral
  const oni = state.enso.oni_latest ? state.enso.oni_latest.anom : null;
  const is = state.iod.status || "Netral";                          // IOD Positif / IOD Negatif / Netral
  const strg = oni != null ? ensoStrength(oni) : "";
  const ensoLabel = es === "Netral" ? "ENSO netral" : `${es}${strg ? " " + strg : ""}`;
  let dampak;
  if (es.indexOf("El Nino") >= 0) dampak = "Indonesia cenderung lebih kering dari biasanya (hujan di bawah normal); waspada kekeringan dan kebakaran lahan.";
  else if (es.indexOf("La Nina") >= 0) dampak = "Indonesia cenderung lebih basah dari biasanya (hujan di atas normal); waspada banjir dan longsor.";
  else dampak = "Pola hujan Indonesia cenderung mendekati normal.";
  if (is.indexOf("Positif") >= 0) dampak += " IOD positif memperkuat kecenderungan kering, terutama Indonesia bagian barat.";
  else if (is.indexOf("Negatif") >= 0) dampak += " IOD negatif menambah peluang hujan, terutama Indonesia bagian barat.";
  return { ensoLabel, es, is, dampak };
}
function renderBrief() {
  if (!state || !state.enso || !state.iod) return;
  const s = laySummary();
  const iodLabel = s.is === "Netral" ? "IOD Netral" : s.is;
  $("brief-chips").innerHTML =
    `<span class="chip ${statusChip(s.es)}">${s.ensoLabel}</span>` +
    `<span class="chip ${statusChip(s.is)}">${iodLabel}</span>`;
  $("brief-text").textContent = s.dampak + " Ini kecenderungan umum, bukan kepastian.";
  $("climate-brief").hidden = false;
}
$("brief-close").addEventListener("click", () => { $("climate-brief").hidden = true; });

renderLegend("sst");
fetch(DATA, { cache: "no-store" }).then((r) => r.json()).then((doc) => {
  state = doc;
  const d = state.domain;
  dataBounds = L.latLngBounds([d.latS, d.lonW], [d.latN, d.lonE]);
  // Darat = basemap OSM (dipasang di atas, lapisan "basemap"); data laut transparan tepat di pantai.
  if (state.currents && state.currents.label) $("cur-model-opt").textContent = state.currents.label;
  document.querySelector('.layer-btn[data-layer="current"]').classList.toggle("disabled", !(state.currents && state.currents.frames && state.currents.frames.length));
  document.querySelector('.layer-btn[data-layer="sal"]').classList.toggle("disabled", !(state.layers.sal && state.layers.sal.frames && state.layers.sal.frames.length));
  setLayer("sst");   // mulai di SST; panel indeks dibangun saat pilih dari dropdown
  renderBrief();     // ringkasan awam kondisi iklim kini
  frameRegion();
  map.on("resize", frameRegion);
  if (state.run) { const w = toWIB(state.run); $("fresh-text").textContent = `Update: ${String(w.getUTCHours()).padStart(2, "0")}:00 WIB, ${w.getUTCDate()} ${MONTHS[w.getUTCMonth()]}`; }
  $("loading").style.display = "none";
}).catch((err) => { hideSkeleton(); $("loading").style.display = "block"; $("loading").textContent = "Gagal memuat data: " + err; console.error(err); });
