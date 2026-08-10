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


def _write_point_data(per_step, anom_fields, anom_frames, meta, cur_native, sal_native=None):
    """Grid mentah (int16 gzip) utk klik-titik: SST(3-jam), Anomali(harian) di grid GFS;
    arus u/v(harian) & salinitas(harian) di grid Copernicus native."""
    pd = {}
    try:
        with open(os.path.join(C.OUT_DIR, "pd_sst.bin.gz"), "wb") as f:
            f.write(process.pack_grid(np.stack([s["sst"] for s in per_step]), 0.01))
        pd["sst"] = {"file": "pd_sst.bin.gz", "scale": 0.01, "nt": len(per_step), **_grid_meta(meta),
                     "times": [s["vt"].strftime("%Y-%m-%dT%H:00:00Z") for s in per_step]}
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


def main():
    os.makedirs(C.OUT_DIR, exist_ok=True)
    run = download.find_run_with_data(download.latest_run())
    print(f"Run GFS: {run:%Y-%m-%d %HZ}")

    present = [(run, f, False) for f in range(0, C.FORECAST_HOURS + 1, C.STEP_HOURS)]
    lim = os.environ.get("KF_MAX_STEPS")
    if lim:
        present = present[: int(lim)]
    # Retensi masa lampau (mirip kertas-cuaca): analisis run GFS sebelumnya (tiap 6 jam, ambil
    # f000+f003) mengisi valid_time -PAST_HOURS..-STEP secara 3-jaman. Best-effort: dilewati bila
    # run lama tak tersedia di NOMADS.
    past = []
    if not os.environ.get("KF_NO_PAST"):
        for dh in range(C.PAST_HOURS, 0, -6):
            r = run - timedelta(hours=dh)
            past += [(r, 0, True), (r, C.STEP_HOURS, True)]
    specs = past + present   # kronologis: lampau -> kini -> forecast

    meta = None
    sea_mask = None
    per_step = []           # {vt, date, month, sst, png}
    tmp = os.path.join(tempfile.gettempdir(), "kf_gfs_step.grib2")

    for r, fstep, is_past in specs:
        vt = r + timedelta(hours=fstep)
        try:
            download.download_step(r, fstep, tmp)
        except Exception as e:
            if is_past:
                print(f"  (lewati lampau {vt:%Y-%m-%d %HZ}: {e})")
                continue
            raise
        fields, m = process.read_grib(tmp)
        meta = m
        sst = process.sst_from_fields(fields)
        if sea_mask is None:
            lsm = process._pick(fields, "lsm", "land")
            sea_mask = (lsm < 0.5) if lsm is not None else np.isfinite(sst)
        # render SST per langkah (wind velocity dibuang; arus laut dari Copernicus)
        tag = vt.strftime("%Y%m%d_%H")
        png = f"sst_{tag}.webp"
        process.render_sst_png(sst, os.path.join(C.OUT_DIR, png),
                               bounds=_edge_bounds(m["west"], m["east"], m["north"], m["south"], m["nx"], m["ny"]))
        per_step.append({"vt": vt, "date": vt.strftime("%Y%m%d"), "month": vt.month,
                         "sst": sst, "png": png})
        print(f"  {'past ' if is_past else 'fcst '}{vt:%Y-%m-%d %HZ}  SST ekuator ~{np.nanmean(sst[sst.shape[0]//2]):.1f}C")

    sst_frames = [{"valid_time": s["vt"].strftime("%Y-%m-%dT%H:00:00Z"), "png": s["png"]}
                  for s in per_step]

    # ---- Anomali harian (rata SST per hari - klim bulan) ----
    days = OrderedDict()
    for s in per_step:
        days.setdefault(s["date"], []).append(s)
    anom_frames = []
    anom_fields = []
    for date, group in days.items():
        month = group[0]["month"]
        sst_day = np.nanmean(np.stack([g["sst"] for g in group]), axis=0)
        clim = process.clim_domain(month, meta)
        anom = sst_day - clim
        anom_fields.append(anom)
        idx = process.indices_from_anom(anom, meta)
        apng = f"anom_{date}.webp"
        process.render_anom_png(anom, os.path.join(C.OUT_DIR, apng),
                                bounds=_edge_bounds(meta["west"], meta["east"], meta["north"], meta["south"], meta["nx"], meta["ny"]))
        anom_frames.append({"date": date, "png": apng,
                            "nino12": idx["nino12"], "nino3": idx["nino3"],
                            "nino34": idx["nino34"], "nino4": idx["nino4"], "dmi": idx["dmi"]})
        print(f"  anomali {date}  nino34={idx['nino34']:+.2f}  dmi={idx['dmi']:+.2f}")

    # ---- Klimatologi 12 bulan (SST absolut, mask laut) ----
    clim_frames = []
    for mth in range(1, 13):
        cfield = np.where(sea_mask, process.clim_domain(mth, meta), np.nan)
        cpng = f"clim_{mth:02d}.webp"
        process.render_sst_png(cfield, os.path.join(C.OUT_DIR, cpng),
                               bounds=_edge_bounds(meta["west"], meta["east"], meta["north"], meta["south"], meta["nx"], meta["ny"]))
        clim_frames.append({"month": mth, "png": cpng})

    # Darat = poligon vektor 10m statik (frontend/data/land_10m.geojson, dibuat prep_land.py).

    # ---- Arus laut FORECAST (Copernicus, per tanggal SST) ----
    currents = None
    cur_native = None
    try:
        cdates = [f["date"] for f in anom_frames]
        s_iso = f"{cdates[0][:4]}-{cdates[0][4:6]}-{cdates[0][6:8]}T00:00:00"
        e_iso = f"{cdates[-1][:4]}-{cdates[-1][4:6]}-{cdates[-1][6:8]}T00:00:00"
        cnc = os.path.join(tempfile.gettempdir(), "kf_currents.nc")
        download.download_currents(s_iso, e_iso, cnc)
        cf, cur_native = process.currents_frames(cnc, C.OUT_DIR, run.strftime("%Y-%m-%dT%H:00:00Z"))
        clat, clon = cur_native["lat"], cur_native["lon"]
        cb = _edge_bounds(float(clon[0]), float(clon[-1]), float(clat[0]), float(clat[-1]), len(clon), len(clat))
        currents = {"label": C.CURRENTS["label"], "cadence": "daily", "frames": cf,
                    "bounds": {"lonW": cb[0], "lonE": cb[1], "latN": cb[2], "latS": cb[3]}}
        print(f"  arus laut Copernicus: {len(cf)} tanggal ({','.join(f['date'] for f in cf)})")
    except Exception as e:
        print("PERINGATAN arus laut gagal:", e)

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
    point_data = _write_point_data(per_step, anom_fields, anom_frames, meta, cur_native, sal_native)

    now_iso = run.strftime("%Y-%m-%dT%H:00:00Z")   # analisis run terkini = "kini"
    today = run.strftime("%Y%m%d")
    latest = next((f for f in anom_frames if f["date"] == today), anom_frames[0])  # hari "kini"

    # ---- Indeks resmi CPC (tumpang) ----
    try:
        cpc = indices.fetch_cpc(months=24)
    except Exception as e:
        print("PERINGATAN CPC gagal:", e)
        cpc = {"oni_latest": None, "oni_status": None, "nino_series": {}, "series_labels": []}

    regions = {k: {"label": indices.NINO_LABELS[k], "now": latest[k],
                   "series": cpc["nino_series"].get(k, [])} for k in indices.NINO_KEYS}
    dmi_series = [{"date": f["date"], "dmi": f["dmi"]} for f in anom_frames]

    # ---- Seri indeks harian: GFS (forecast) vs OISST (observasi) ----
    SER_KEYS = ("nino12", "nino3", "nino34", "nino4", "dmi")
    gfs_ser = {k: [{"date": f["date"], "v": f[k]} for f in anom_frames] for k in SER_KEYS}
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
            "sst": {"label": "Sea Surface Temperature", "cadence": "3h", "frames": sst_frames},
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
