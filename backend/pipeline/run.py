"""Orchestrator pipeline v1 (ENSO + IOD).

Alur: unduh N hari OISST terakhir -> anomali 1 derajat (basis 1991-2020) ->
render PNG per hari + hitung Nino3.4/DMI per hari -> gabung indeks resmi CPC ->
tulis frontend/data/output/{sst_anom_*.png, climate.json}.
"""
import json
import os
from datetime import datetime, timezone

from . import config as C
from . import download, process, indices


def main():
    os.makedirs(C.OUT_DIR, exist_ok=True)
    process.load_clim()

    files = download.latest_oisst_files(C.N_DAYS)  # lama -> baru
    print(f"OISST {len(files)} hari: {files[0][0]} .. {files[-1][0]}")

    frames = []
    bounds = None
    for date, url in files:
        raw = download.download_bytes(url)
        sst, lat, lon = process.read_sst_native(raw)
        anom = process.anomaly(sst, int(date[4:6]))
        png_name = f"sst_anom_{date}.png"
        bounds = process.render_anom_png(anom, lat, lon, os.path.join(C.OUT_DIR, png_name))
        idx = process.indices(anom, lat, lon)
        frames.append({"date": date, "png": png_name, "nino34": idx["nino34"], "dmi": idx["dmi"]})
        print(f"  {date}  nino34={idx['nino34']:+.2f}  dmi={idx['dmi']:+.2f}")

    latest = frames[-1]

    # Indeks resmi CPC (ENSO)
    try:
        cpc = indices.fetch_cpc(months=24)
    except Exception as e:  # jaga-jaga kalau CPC down
        print("PERINGATAN: gagal ambil CPC:", e)
        cpc = {"oni_latest": None, "oni_status": None, "nino34_series": []}

    doc = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_date": latest["date"],
        "domain": {"latS": bounds[0], "latN": bounds[1], "lonW": bounds[2], "lonE": bounds[3]},
        "anom_abs": C.ANOM_ABS,
        "boxes": C.BOXES,
        "frames": frames,
        "enso": {
            "status": cpc["oni_status"],
            "oni_latest": cpc["oni_latest"],
            "nino34_now": latest["nino34"],
            "nino34_series": cpc["nino34_series"],
            "forecast": {"source": "CPC/IRI", "note": "segera"},
        },
        "iod": {
            "status": indices.iod_status(latest["dmi"]),
            "dmi_now": latest["dmi"],
            "dmi_series": [{"date": f["date"], "dmi": f["dmi"]} for f in frames],
            "forecast": {"source": "BoM", "note": "segera"},
        },
    }
    with open(os.path.join(C.OUT_DIR, "climate.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    print("Selesai. Status ENSO:", doc["enso"]["status"], "| IOD:", doc["iod"]["status"])
    print("nino34_now", latest["nino34"], "dmi_now", latest["dmi"])
    print("Output ->", C.OUT_DIR)


if __name__ == "__main__":
    main()
