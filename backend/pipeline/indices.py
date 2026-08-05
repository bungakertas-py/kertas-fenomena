"""Parse indeks resmi CPC: ONI (ENSO) + Nino bulanan (basis 1991-2020)."""
from . import config as C
from . import download

_SEAS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]


def parse_oni(text):
    """oni.ascii.txt -> list {seas, year, total, anom} urut waktu."""
    rows = []
    for ln in text.splitlines()[1:]:
        p = ln.split()
        if len(p) == 4:
            try:
                rows.append({"seas": p[0], "year": int(p[1]), "total": float(p[2]), "anom": float(p[3])})
            except ValueError:
                pass
    return rows


def parse_nino_monthly(text):
    """ersst5.nino.mth.91-20.ascii -> list {year, mon, nino34_anom, ...} urut waktu."""
    rows = []
    for ln in text.splitlines()[1:]:
        p = ln.split()
        if len(p) >= 10:
            try:
                rows.append({
                    "year": int(p[0]), "mon": int(p[1]),
                    "nino12": float(p[3]), "nino3": float(p[5]),
                    "nino4": float(p[7]), "nino34": float(p[9]),
                })
            except ValueError:
                pass
    return rows


def enso_status(oni_anom):
    if oni_anom >= C.ENSO_THRESH:
        return "El Nino"
    if oni_anom <= -C.ENSO_THRESH:
        return "La Nina"
    return "Netral"


def iod_status(dmi):
    if dmi >= C.IOD_THRESH:
        return "IOD Positif"
    if dmi <= -C.IOD_THRESH:
        return "IOD Negatif"
    return "Netral"


def fetch_cpc(months=24):
    """Ambil ONI + Nino bulanan CPC. Kembalikan dict ringkas untuk frontend."""
    oni = parse_oni(download.fetch_text(C.CPC_ONI))
    nino = parse_nino_monthly(download.fetch_text(C.CPC_NINO_MON))
    latest_oni = oni[-1] if oni else None
    series = [
        {"t": f"{r['year']}-{r['mon']:02d}", "nino34": r["nino34"]}
        for r in nino[-months:]
    ]
    return {
        "oni_latest": latest_oni,
        "oni_status": enso_status(latest_oni["anom"]) if latest_oni else None,
        "nino34_series": series,
    }
