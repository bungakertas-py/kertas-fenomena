"""Orchestrator pipeline v2 (GFS).

Alur: cari run GFS -> per langkah 3-jam unduh (SST+angin), render SST PNG + velocity JSON ->
gabung per hari jadi Anomali (SST-klim) + indeks -> render Klimatologi 12 bulan ->
tumpang indeks resmi CPC -> tulis frontend/data/output/{*.png,*.json, climate.json}.
"""
import json
import os
import tempfile
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import warnings

import numpy as np

warnings.filterwarnings("ignore", message="Mean of empty slice")   # nanmean di piksel darat

from . import config as C
from . import download, process, indices


def _valid_time(run, fstep):
    return run + timedelta(hours=fstep)


def _grid_meta(meta):
    return {"ny": meta["ny"], "nx": meta["nx"], "west": meta["west"], "east": meta["east"],
            "north": meta["north"], "south": meta["south"]}


def _edge_bounds(west, east, north, south, nx, ny):
    """Bounds penempatan PNG = titik grid (true geo). (Ekstensi tepi dibatalkan: bikin geser vs basemap.)"""
    return (west, east, north, south)


def _write_point_data(sst_day_fields, anom_fields, anom_frames, meta, cur_native, sal_native=None):
    """Grid mentah (int16 gzip) utk klik-titik, semua HARIAN di grid CMEMS: SST(rata harian),
    Anomali(harian); arus u/v(harian) & salinitas(harian) di grid Copernicus native."""
    pd = {}
    try:
        with open(os.path.join(C.OUT_DIR, "pd_sst.bin.gz"), "wb") as f:
            f.write(process.pack_grid(np.stack(sst_day_fields), 0.01))
        pd["sst"] = {"file": "pd_sst.bin.gz", "scale": 0.01, "nt": len(sst_day_fields), **_grid_meta(meta),
                     "dates": [fr["date"] for fr in anom_frames]}
        with open(os.path.join(C.OUT_DIR, "pd_anom.bin.gz"), "wb") as f:
            f.write(process.pack_grid(np.stack(anom_fields), 0.01))
        pd["anom"] = {"file": "pd_anom.bin.gz", "scale": 0.01, "nt": len(anom_fields), **_grid_meta(meta),
                      "dates": [fr["date"] for fr in anom_frames]}
        # klimatologi 12 bulan di grid GFS (klik-titik: siklus tahunan di lokasi)
        clim_stack = np.stack([process.clim_domain(mth, meta) for mth in range(1, 13)])
        with open(os.path.join(C.OUT_DIR, "pd_clim.bin.gz"), "wb") as f:
            f.write(process.pack_grid(clim_stack, 0.01))
        pd["clim"] = {"file": "pd_clim.bin.gz", "scale": 0.01, "nt": 12, **_grid_meta(meta),
                      "months": list(range(1, 13))}
        if cur_native:
            lat, lon = cur_native["lat"], cur_native["lon"]
            with open(os.path.join(C.OUT_DIR, "pd_cur.bin.gz"), "wb") as f:
                f.write(process.pack_grid(np.stack([cur_native["u"], cur_native["v"]]), 0.001))
            pd["cur"] = {"file": "pd_cur.bin.gz", "scale": 0.001, "comp": 2, "nt": len(cur_native["dates"]),
                         "ny": int(len(lat)), "nx": int(len(lon)),
                         "west": float(lon[0]), "east": float(lon[-1]),
                         "north": float(lat[0]), "south": float(lat[-1]), "dates": cur_native["dates"]}
        if sal_native:
            lat, lon = sal_native["lat"], sal_native["lon"]
            with open(os.path.join(C.OUT_DIR, "pd_sal.bin.gz"), "wb") as f:
                f.write(process.pack_grid(sal_native["sal"], 0.01))   # PSU ~30-38, scale 0.01 (int16 aman)
            pd["sal"] = {"file": "pd_sal.bin.gz", "scale": 0.01, "nt": len(sal_native["dates"]),
                         "ny": int(len(lat)), "nx": int(len(lon)),
                         "west": float(lon[0]), "east": float(lon[-1]),
                         "north": float(lat[0]), "south": float(lat[-1]), "dates": sal_native["dates"]}
        print(f"  point_data: {list(pd)}")
    except Exception as e:
        print("PERINGATAN point_data gagal:", e)
    return pd


def _apply_index_bias_correction(anom_frames, obs_ser, keys):
    """Koreksi-bias: SST CMEMS lebih hangat dari baseline COBE -> indeks kita bias tinggi.
    Geser tiap indeks CMEMS sebesar offset rata-rata (CMEMS - OISST) pada hari yg ada di
    KEDUANYA, supaya angka & garis menyambung observasi OISST. anom_frames dikoreksi in-place.
    (Peta anomali TETAP relatif-COBE; ini khusus indeks/angka.)"""
    for k in keys:
        obs = {r["date"]: r["v"] for r in obs_ser.get(k, []) if r.get("v") is not None}
        diffs = [f[k] - obs[f["date"]] for f in anom_frames
                 if f.get(k) is not None and f["date"] in obs]
        if not diffs:
            continue
        off = sum(diffs) / len(diffs)
        for f in anom_frames:
            if f.get(k) is not None:
                f[k] = round(f[k] - off, 3)
        print(f"  koreksi-bias {k}: offset {off:+.2f} (n={len(diffs)} hari tumpang-tindih OISST)")


def main():
    os.makedirs(C.OUT_DIR, exist_ok=True)
    # SST dari MODEL LAUT CMEMS per-jam (ganti GFS). Jendela: retensi..forecast jam sekitar "kini".
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    run = now                                    # acuan "kini" untuk downstream (now_iso/today/doc.run)
    start = now - timedelta(hours=C.SST_CMEMS["retensi_hours"])
    end = now + timedelta(hours=C.SST_CMEMS["forecast_hours"])
    print(f"SST CMEMS per-jam: {start:%Y-%m-%d %HZ} .. {end:%Y-%m-%d %HZ}")
    ssth_nc = os.path.join(tempfile.gettempdir(), "kf_sst_hourly.nc")
    download.download_sst_hourly(start.strftime("%Y-%m-%dT%H:00:00"), end.strftime("%Y-%m-%dT%H:00:00"), ssth_nc)
    per_step, meta, sea_mask = process.sst_hourly_steps(ssth_nc, C.OUT_DIR)
    print(f"  {len(per_step)} frame SST per-jam di grid CMEMS {meta['nx']}x{meta['ny']}")

    sst_frames = [{"valid_time": s["vt"].strftime("%Y-%m-%dT%H:00:00Z"), "png": s["png"]}
                  for s in per_step]

    # ---- Anomali harian (rata SST per hari - klim bulan) ----
    days = OrderedDict()
    for s in per_step:
        days.setdefault(s["date"], []).append(s)
    grid_bounds = _edge_bounds(meta["west"], meta["east"], meta["north"], meta["south"], meta["nx"], meta["ny"])
    anom_frames = []
    anom_fields = []
    sst_day_fields = []       # rata-rata SST harian -> point_data SST HARIAN (bukan per-jam, biar ringan)
    for date, group in days.items():
        month = group[0]["month"]
        sst_day = np.nanmean(np.stack([g["sst"] for g in group]), axis=0)
        clim = process.clim_domain(month, meta)
        anom = sst_day - clim
        anom_fields.append(anom)
        sst_day_fields.append(sst_day)
        idx = process.indices_from_anom(anom, meta)
        apng = f"anom_{date}.webp"
        anom_frames.append({"date": date, "png": apng,
                            "nino12": idx["nino12"], "nino3": idx["nino3"],
                            "nino34": idx["nino34"], "nino4": idx["nino4"], "dmi": idx["dmi"]})
        print(f"  anomali {date}  nino34={idx['nino34']:+.2f}  dmi={idx['dmi']:+.2f}")
    process.render_batch(((process.render_anom_png, (anom_fields[i], os.path.join(C.OUT_DIR, f["png"])),
                           {"scale": 1, "bounds": grid_bounds})   # grid CMEMS sudah 1/12 -> native
                          for i, f in enumerate(anom_frames)), label="anomali harian")

    # ---- Klimatologi 12 bulan (SST absolut, mask laut) ----
    clim_frames = [{"month": mth, "png": f"clim_{mth:02d}.webp"} for mth in range(1, 13)]
    process.render_batch(((process.render_sst_png,
                           (np.where(sea_mask, process.clim_domain(f["month"], meta), np.nan),
                            os.path.join(C.OUT_DIR, f["png"])),
                           {"scale": 1, "bounds": grid_bounds})   # grid CMEMS native
                          for f in clim_frames), label="klimatologi bulanan")

    # Darat = poligon vektor 10m statik (frontend/data/land_10m.geojson, dibuat prep_land.py).

    # ---- Arus laut: PERMUKAAN per-jam (dari nc SST hourly yg sudah punya uo/vo) + KEDALAMAN harian ----
    ref_iso = run.strftime("%Y-%m-%dT%H:00:00Z")
    cdates = [f["date"] for f in anom_frames]
    s_iso = f"{cdates[0][:4]}-{cdates[0][4:6]}-{cdates[0][6:8]}T00:00:00"
    e_iso = f"{cdates[-1][:4]}-{cdates[-1][4:6]}-{cdates[-1][6:8]}T00:00:00"
    currents = None
    cur_native = None
    try:
        surf_frames, cur_native = process.currents_hourly(ssth_nc, C.OUT_DIR, ref_iso)   # permukaan per-jam
        clat, clon = cur_native["lat"], cur_native["lon"]
        cb = _edge_bounds(float(clon[0]), float(clon[-1]), float(clat[0]), float(clat[-1]), len(clon), len(clat))
        currents = {"label": C.CURRENTS["label"], "cadence": "1h", "frames": surf_frames,
                    "depth_labels": ["0 m"], "depth_frames": {},
                    "bounds": {"lonW": cb[0], "lonE": cb[1], "latN": cb[2], "latS": cb[3]}}
        print(f"  arus permukaan per-jam: {len(surf_frames)} frame")
        try:   # lapisan bawah HARIAN (P1D cur di 50/100/200 m)
            cnc = os.path.join(tempfile.gettempdir(), "kf_currents.nc")
            download.download_currents(s_iso, e_iso, cnc)
            cd = process.currents_depth(cnc, C.OUT_DIR, ref_iso)
            currents["depth_labels"] = ["0 m"] + cd["depth_labels"]
            currents["depth_frames"] = cd["frames"]
            print(f"  arus kedalaman: {len(cd['depth_labels'])} lapisan (level {cd['depth_used']} m)")
        except Exception as e:
            print("PERINGATAN arus kedalaman gagal:", e)
    except Exception as e:
        print("PERINGATAN arus permukaan gagal:", e)

    # ---- Salinitas permukaan FORECAST (Copernicus, per tanggal SST) ----
    salinity = None
    sal_native = None
    try:
        cdates = [f["date"] for f in anom_frames]
        s_iso = f"{cdates[0][:4]}-{cdates[0][4:6]}-{cdates[0][6:8]}T00:00:00"
        e_iso = f"{cdates[-1][:4]}-{cdates[-1][4:6]}-{cdates[-1][6:8]}T00:00:00"
        snc = os.path.join(tempfile.gettempdir(), "kf_salinity.nc")
        download.download_salinity(s_iso, e_iso, snc)
        sf, sal_native = process.salinity_frames(snc, C.OUT_DIR)
        slat, slon = sal_native["lat"], sal_native["lon"]
        sb = _edge_bounds(float(slon[0]), float(slon[-1]), float(slat[0]), float(slat[-1]), len(slon), len(slat))
        salinity = {"label": C.SALINITY["label"], "cadence": "daily", "frames": sf,
                    "bounds": {"lonW": sb[0], "lonE": sb[1], "latN": sb[2], "latS": sb[3]}}
        print(f"  salinitas Copernicus: {len(sf)} tanggal ({','.join(f['date'] for f in sf)})")
    except Exception as e:
        print("PERINGATAN salinitas gagal:", e)

    # ---- Suhu bawah permukaan FORECAST (Copernicus thetao, multi-kedalaman) ----
    subtemp = None
    try:
        cdates = [f["date"] for f in anom_frames]
        s_iso = f"{cdates[0][:4]}-{cdates[0][4:6]}-{cdates[0][6:8]}T00:00:00"
        e_iso = f"{cdates[-1][:4]}-{cdates[-1][4:6]}-{cdates[-1][6:8]}T00:00:00"
        stnc = os.path.join(tempfile.gettempdir(), "kf_subtemp.nc")
        download.download_subtemp(s_iso, e_iso, stnc)
        st = process.subtemp_frames(stnc, C.OUT_DIR)
        b = st["bounds"]
        subtemp = {"label": C.SUBTEMP["label"], "cadence": "daily",
                   "depths": st["depths"], "depth_labels": st["depth_labels"], "depth_used": st["depth_used"],
                   "frames": st["frames"],
                   "bounds": {"lonW": b[0], "lonE": b[1], "latN": b[2], "latS": b[3]}}
        print(f"  suhu bawah permukaan: {len(st['depths'])} kedalaman x {len(st['dates'])} tanggal (level {st['depth_used']} m)")
    except Exception as e:
        print("PERINGATAN suhu bawah permukaan gagal:", e)

    # ---- Point data (grid mentah utk klik-titik) ----
    point_data = _write_point_data(sst_day_fields, anom_fields, anom_frames, meta, cur_native, sal_native)

    # ---- OISST observasi (dulu) -> lalu KOREKSI-BIAS indeks CMEMS agar menyambung observasi ----
    SER_KEYS = ("nino12", "nino3", "nino34", "nino4", "dmi")
    obs_ser = {k: [] for k in SER_KEYS}
    try:
        files = download.latest_oisst_files(C.OISST_DAYS)
        print(f"  OISST: {len(files)} hari ({files[0][0]}..{files[-1][0]})")
        for date, url in files:
            try:
                idx = process.oisst_indices(download.download_bytes(url), int(date[4:6]))
                for k in SER_KEYS:
                    obs_ser[k].append({"date": date, "v": idx[k]})
            except Exception as e:
                print("  OISST lewati", date, e)
    except Exception as e:
        print("PERINGATAN OISST gagal:", e)
    _apply_index_bias_correction(anom_frames, obs_ser, SER_KEYS)   # anom_frames dikoreksi in-place

    now_iso = run.strftime("%Y-%m-%dT%H:00:00Z")   # analisis run terkini = "kini"
    today = run.strftime("%Y%m%d")
    latest = next((f for f in anom_frames if f["date"] == today), anom_frames[0])  # hari "kini" (terkoreksi)

    # ---- Indeks resmi CPC (tumpang) ----
    try:
        cpc = indices.fetch_cpc(months=24)
    except Exception as e:
        print("PERINGATAN CPC gagal:", e)
        cpc = {"oni_latest": None, "oni_status": None, "nino_series": {}, "series_labels": []}

    regions = {k: {"label": indices.NINO_LABELS[k], "now": latest[k],
                   "series": cpc["nino_series"].get(k, [])} for k in indices.NINO_KEYS}
    dmi_series = [{"date": f["date"], "dmi": f["dmi"]} for f in anom_frames]
    gfs_ser = {k: [{"date": f["date"], "v": f[k]} for f in anom_frames] for k in SER_KEYS}   # terkoreksi
    index_series = {k: {"obs": obs_ser[k], "gfs": gfs_ser[k]} for k in SER_KEYS}
    index_series["oni"] = {"official": cpc.get("oni_series", [])}

    # ---- Prakiraan musiman SINTEX-F (JAMSTEC): Nino3.4 & DMI ----
    season_forecast = indices.fetch_sintex()

    doc = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run": run.strftime("%Y-%m-%dT%H:00:00Z"),
        "now": now_iso,
        "data_date": today,
        "domain": (lambda b: {"lonW": b[0], "lonE": b[1], "latN": b[2], "latS": b[3]})(
            _edge_bounds(meta["west"], meta["east"], meta["north"], meta["south"], meta["nx"], meta["ny"])),
        "anom_abs": C.ANOM_ABS, "sst_min": C.SST_MIN, "sst_max": C.SST_MAX,
        "boxes": C.BOXES,
        "currents": currents, "point_data": point_data,
        "index_series": index_series,
        "season_forecast": season_forecast,
        "season_source": C.SINTEX_SOURCE, "season_clim": C.SINTEX_CLIM, "obs_clim": C.OBS_CLIM,
        "enso_thresh": C.ENSO_THRESH, "iod_thresh": C.IOD_THRESH,
        "layers": {
            "sst": {"label": "Suhu Muka Laut (model laut)", "cadence": "1h", "frames": sst_frames},
            "anom": {"label": "Anomali SST", "cadence": "daily", "frames": anom_frames},
            **({"sal": {"label": "Salinitas Permukaan", "cadence": "daily",
                        "frames": salinity["frames"], "bounds": salinity["bounds"]}} if salinity else {}),
            **({"subt": {"label": "Suhu Bawah Permukaan", "cadence": "daily",
                         "depths": subtemp["depths"], "depth_labels": subtemp["depth_labels"],
                         "frames": subtemp["frames"], "bounds": subtemp["bounds"]}} if subtemp else {}),
            "clim": {"label": "Klimatologi SST", "cadence": "monthly", "frames": clim_frames},
        },
        "enso": {"status": cpc["oni_status"], "oni_latest": cpc["oni_latest"],
                 "regions": regions, "series_labels": cpc["series_labels"]},
        "iod": {"status": indices.iod_status(latest["dmi"]), "dmi_now": latest["dmi"],
                "dmi_series": dmi_series},
    }
    with open(os.path.join(C.OUT_DIR, "climate.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    print(f"Selesai. SST {len(sst_frames)} frame, Anomali {len(anom_frames)} hari, Klim 12 bln.")
    print("ENSO:", doc["enso"]["status"], "| IOD:", doc["iod"]["status"],
          "| nino34_now", latest["nino34"])


if __name__ == "__main__":
    main()
