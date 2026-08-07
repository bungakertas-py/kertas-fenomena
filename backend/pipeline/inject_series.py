"""Dev-only: suntik index_series (GFS forecast + OISST obs + ONI) ke climate.json
yang sudah ada, tanpa rerun pipeline GFS. Jalankan dari root:
  backend/venv/Scripts/python.exe -m backend.pipeline.inject_series
"""
import json
import os

from . import config as C
from . import download
from . import indices
from . import process

CJ = os.path.join(C.OUT_DIR, "climate.json")
SER_KEYS = ("nino12", "nino3", "nino34", "nino4", "dmi")


def main():
    doc = json.load(open(CJ, encoding="utf-8"))
    anom = doc["layers"]["anom"]["frames"]
    gfs_ser = {k: [{"date": f["date"], "v": f[k]} for f in anom] for k in SER_KEYS}
    obs_ser = {k: [] for k in SER_KEYS}
    files = download.latest_oisst_files(C.OISST_DAYS)
    print(f"OISST: {len(files)} hari ({files[0][0]}..{files[-1][0]})")
    for date, url in files:
        try:
            idx = process.oisst_indices(download.download_bytes(url), int(date[4:6]))
            for k in SER_KEYS:
                obs_ser[k].append({"date": date, "v": idx[k]})
            print(f"  {date}  nino34={idx['nino34']:+.2f}  dmi={idx['dmi']:+.2f}")
        except Exception as e:
            print("  lewati", date, e)
    cpc = indices.fetch_cpc(months=24)
    series = {k: {"obs": obs_ser[k], "gfs": gfs_ser[k]} for k in SER_KEYS}
    series["oni"] = {"official": cpc.get("oni_series", [])}
    doc["index_series"] = series
    doc["enso_thresh"] = C.ENSO_THRESH
    doc["iod_thresh"] = C.IOD_THRESH
    # arus laut FORECAST (Copernicus, per tanggal anom)
    try:
        cdates = [f["date"] for f in anom]
        s_iso = f"{cdates[0][:4]}-{cdates[0][4:6]}-{cdates[0][6:8]}T00:00:00"
        e_iso = f"{cdates[-1][:4]}-{cdates[-1][4:6]}-{cdates[-1][6:8]}T00:00:00"
        cnc = os.path.join(C.OUT_DIR, "_kf_currents.nc")
        download.download_currents(s_iso, e_iso, cnc)
        cf, _ = process.currents_frames(cnc, C.OUT_DIR, doc.get("run", "1970-01-01T00:00:00Z"))
        os.remove(cnc)
        doc["currents"] = {"label": C.CURRENTS["label"], "cadence": "daily", "frames": cf}
        doc.pop("currents_label", None)
        print(f"arus laut Copernicus OK: {len(cf)} tanggal {[f['date'] for f in cf]}")
    except Exception as e:
        print("arus laut gagal:", repr(e)[:200])
    json.dump(doc, open(CJ, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    g = gfs_ser["nino34"][0]["v"] if gfs_ser["nino34"] else None
    o = obs_ser["nino34"][-1]["v"] if obs_ser["nino34"] else None
    print(f"OK. nino34 GFS(kini)={g}  OISST(terakhir)={o}  ONI seri={len(series['oni']['official'])}")


if __name__ == "__main__":
    main()
