/* ===== Kertas Fenomena - v1 (ENSO + IOD), tersambung data OISST/CPC ===== */
"use strict";

const DATA = "data/output/climate.json";

/* Legenda anomali SST (harus cocok colormap PNG di process.py). */
const ANOM_LEGEND = {
  title: "Anomali SST (degC)",
  grad: "linear-gradient(90deg,#2166ac,#67a9cf,#f7f7f7,#ef8a62,#b2182b)",
  scale: ["-3", "-1.5", "0", "+1.5", "+3"],
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
const nlng = (l) => ((l % 360) + 360) % 360;           // ke 0..360
const fmtDate = (d) => `${d.slice(6, 8)} ${MONTHS[+d.slice(4, 6) - 1]} ${d.slice(0, 4)}`;

let state = null;      // isi climate.json
let frameIdx = 0;
let overlay = null;    // imageOverlay aktif
let playing = false, playTimer = null;
let ninoLayer = null, iodLayer = null;

/* ---- Peta (tanpa tile; backdrop CSS jadi latar; lon 0..360 Pasifik di tengah) ---- */
const map = L.map("map", {
  zoomControl: false, attributionControl: false,
  minZoom: 2, maxZoom: 7, zoomSnap: 0.25,
  worldCopyJump: false,
  maxBounds: [[-58, 15], [58, 305]], maxBoundsViscosity: 0.5,
}).setView([-2, 118], 3.2);

/* ---- Legenda ---- */
function renderLegend() {
  document.getElementById("lg-title").textContent = ANOM_LEGEND.title;
  document.getElementById("lg-bar").style.background = ANOM_LEGEND.grad;
  document.getElementById("lg-scale").innerHTML = ANOM_LEGEND.scale.map((s) => `<span>${s}</span>`).join("");
}

/* ---- Layer list (v1: satu layer) ---- */
function renderLayerList() {
  const el = document.getElementById("layer-list");
  el.innerHTML = "";
  const btn = document.createElement("button");
  btn.className = "layer-btn active";
  btn.innerHTML = `<span class="material-symbols-outlined">thermostat</span><span>Anomali SST</span>`;
  el.appendChild(btn);
}

/* ---- Kotak Nino & kutub IOD ---- */
function boxRect(b, opts) {
  // b = [la0,la1,lo0,lo1] (lon 0..360)
  return L.rectangle([[b[0], b[2]], [b[1], b[3]]], opts);
}
function buildOverlays() {
  const bx = state.boxes;
  const nOpt = { color: "#0029d7", weight: 2, fill: false, interactive: false };
  const nOptHi = { color: "#0029d7", weight: 3, fill: true, fillColor: "#0029d7", fillOpacity: 0.10, interactive: false };
  ninoLayer = L.layerGroup([
    boxRect(bx.nino4, nOpt), boxRect(bx.nino3, nOpt), boxRect(bx.nino12, nOpt),
    boxRect(bx.nino34, nOptHi),
    L.marker([6, nlng(215)], { interactive: false, icon: L.divIcon({ className: "box-lbl", html: "NINO 3.4", iconSize: [60, 14] }) }),
  ]);
  const iOpt = { color: "#e64980", weight: 3, fill: true, fillColor: "#e64980", fillOpacity: 0.10, interactive: false };
  iodLayer = L.layerGroup([
    boxRect(bx.iod_west, iOpt), boxRect(bx.iod_east, iOpt),
    L.marker([12, 60], { interactive: false, icon: L.divIcon({ className: "box-lbl", html: "IOD W", iconSize: [40, 14] }) }),
    L.marker([2, 100], { interactive: false, icon: L.divIcon({ className: "box-lbl", html: "IOD E", iconSize: [40, 14] }) }),
  ]);
  // equator tipis
  L.polyline([[0, state.domain.lonW], [0, state.domain.lonE]], { color: "#ffffff", weight: 1, opacity: 0.18, dashArray: "4 6", interactive: false }).addTo(map);
  if (document.getElementById("ov-nino").checked) ninoLayer.addTo(map);
  if (document.getElementById("ov-iod").checked) iodLayer.addTo(map);
}

/* ---- Frame peta ---- */
function showFrame(i) {
  frameIdx = Math.max(0, Math.min(state.frames.length - 1, i));
  const f = state.frames[frameIdx];
  const d = state.domain;
  const bounds = [[d.latS, d.lonW], [d.latN, d.lonE]];
  const url = "data/output/" + f.png;
  if (overlay) overlay.setUrl(url), overlay.setBounds(bounds);
  else overlay = L.imageOverlay(url, bounds, { opacity: 0.9, interactive: false, className: "sst-overlay" }).addTo(map);
  // timeline
  document.getElementById("tl-time").textContent = fmtDate(f.date);
  document.getElementById("time-range").value = frameIdx;
  updateRangeFill();
  // update angka live + penanda sparkline
  updateLiveReadouts(f);
}

/* ---- Panel Indeks ---- */
function statusChipClass(status) {
  if (!status) return "chip-neutral";
  if (status.indexOf("El Nino") >= 0 || status.indexOf("Positif") >= 0) return "chip-warm";
  if (status.indexOf("La Nina") >= 0 || status.indexOf("Negatif") >= 0) return "chip-cool";
  return "chip-neutral";
}
function sparkPoints(vals, w, h) {
  if (!vals.length) return "";
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 0.4) { const m = (hi + lo) / 2; lo = m - 0.2; hi = m + 0.2; }
  const pad = 3;
  return vals.map((v, i) => {
    const x = vals.length === 1 ? w / 2 : (i / (vals.length - 1)) * w;
    const y = pad + (1 - (v - lo) / (hi - lo)) * (h - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}
function buildIndexPanel() {
  const e = state.enso, i = state.iod;
  const oni = e.oni_latest;
  const ensoSeries = e.nino34_series.map((s) => s.nino34);
  const iodSeries = i.dmi_series.map((s) => s.dmi);
  const el = document.getElementById("ip-cards");
  el.innerHTML = `
    <div class="ip-card">
      <div class="ip-row">
        <span class="mono-label">ENSO &middot; Nino 3.4</span>
        <span class="chip ${statusChipClass(e.status)}">${e.status || "-"}</span>
      </div>
      <div class="ip-big"><span id="enso-now">${fmtSigned(e.nino34_now)}</span><span class="unit">degC</span></div>
      <svg class="spark" viewBox="0 0 120 30" preserveAspectRatio="none"><polyline points="${sparkPoints(ensoSeries, 120, 30)}" /></svg>
      <span class="ip-cap">Nino 3.4 bulanan (CPC, 24 bln)</span>
      <div class="ip-fc"><span class="mono-label">ONI resmi</span><span class="ip-fc-val">${oni ? fmtSigned(oni.anom) + " (" + oni.seas + " " + oni.year + ")" : "-"}</span></div>
      <div class="ip-fc"><span class="mono-label">Prakiraan ${e.forecast.source}</span><span class="ip-fc-val">${e.forecast.note}</span></div>
    </div>
    <div class="ip-card">
      <div class="ip-row">
        <span class="mono-label">IOD &middot; DMI</span>
        <span class="chip ${statusChipClass(i.status)}">${i.status || "-"}</span>
      </div>
      <div class="ip-big"><span id="iod-now">${fmtSigned(i.dmi_now)}</span><span class="unit">degC</span></div>
      <svg class="spark" viewBox="0 0 120 30" preserveAspectRatio="none"><polyline points="${sparkPoints(iodSeries, 120, 30)}" /></svg>
      <span class="ip-cap">DMI harian (dari OISST, ${iodSeries.length} hari)</span>
      <div class="ip-fc"><span class="mono-label">Prakiraan ${i.forecast.source}</span><span class="ip-fc-val">${i.forecast.note}</span></div>
    </div>`;
  document.getElementById("ip-note").textContent = "Keadaan kini. Basis anomali 1991-2020.";
}
function fmtSigned(v) { return (v >= 0 ? "+" : "") + v.toFixed(2); }
function updateLiveReadouts(f) {
  const en = document.getElementById("enso-now");
  const io = document.getElementById("iod-now");
  if (en) en.textContent = fmtSigned(f.nino34);
  if (io) io.textContent = fmtSigned(f.dmi);
}

/* ---- Timeline ---- */
const range = document.getElementById("time-range");
function updateRangeFill() {
  const pct = range.max > 0 ? (range.value / range.max) * 100 : 0;
  range.style.backgroundSize = pct + "% 100%";
}
range.addEventListener("input", () => showFrame(+range.value));
const playBtn = document.getElementById("play-btn");
playBtn.addEventListener("click", () => {
  playing = !playing;
  playBtn.querySelector(".material-symbols-outlined").textContent = playing ? "pause" : "play_arrow";
  if (playing) playTimer = setInterval(() => showFrame((frameIdx + 1) % state.frames.length), 900);
  else clearInterval(playTimer);
});

/* ---- Overlay toggles ---- */
document.getElementById("ov-nino").addEventListener("change", (e) => {
  if (!ninoLayer) return; e.target.checked ? ninoLayer.addTo(map) : map.removeLayer(ninoLayer);
});
document.getElementById("ov-iod").addEventListener("change", (e) => {
  if (!iodLayer) return; e.target.checked ? iodLayer.addTo(map) : map.removeLayer(iodLayer);
});

/* ---- Panel Indeks show/hide ---- */
const indexPanel = document.getElementById("index-panel");
const indexBtn = document.getElementById("index-btn");
function toggleIndex(force) {
  const show = force != null ? force : indexPanel.hidden;
  indexPanel.hidden = !show;
  indexBtn.classList.toggle("active", show);
}
indexBtn.classList.add("active");
indexBtn.addEventListener("click", () => toggleIndex());
document.getElementById("index-close").addEventListener("click", () => toggleIndex(false));

/* ---- Panel titik ---- */
const pointPanel = document.getElementById("point-panel");
map.on("click", (e) => {
  const lon = nlng(e.latlng.lng);
  document.getElementById("pp-loc").textContent = `${e.latlng.lat.toFixed(2)}, ${lon.toFixed(2)}E`;
  pointPanel.hidden = false;
});
document.getElementById("pp-close").addEventListener("click", () => { pointPanel.hidden = true; });

/* ---- Kartu nama ---- */
const aboutOverlay = document.getElementById("about-overlay");
document.getElementById("about-btn").addEventListener("click", () => aboutOverlay.classList.add("show"));
document.getElementById("about-close").addEventListener("click", () => aboutOverlay.classList.remove("show"));
aboutOverlay.addEventListener("click", (e) => { if (e.target === aboutOverlay) aboutOverlay.classList.remove("show"); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") aboutOverlay.classList.remove("show"); });

/* ---- Kontrol lain ---- */
document.getElementById("zoom-in").addEventListener("click", () => map.zoomIn());
document.getElementById("zoom-out").addEventListener("click", () => map.zoomOut());
document.getElementById("fs-btn").addEventListener("click", () => {
  if (!document.fullscreenElement) document.documentElement.requestFullscreen?.();
  else document.exitFullscreen?.();
});
document.getElementById("lang-btn").addEventListener("click", (e) => e.currentTarget.classList.toggle("en"));

/* ---- Init ---- */
renderLayerList();
renderLegend();
fetch(DATA, { cache: "no-store" })
  .then((r) => r.json())
  .then((doc) => {
    state = doc;
    range.max = state.frames.length - 1;
    buildOverlays();
    buildIndexPanel();
    showFrame(state.frames.length - 1);
    document.getElementById("tl-horizon").textContent = `Anomali SST harian &middot; ${state.frames.length} hari`.replace("&middot;", "·");
  })
  .catch((err) => {
    document.getElementById("ip-note").textContent = "Gagal memuat data: " + err;
    console.error(err);
  });
