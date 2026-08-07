"""Parse indeks resmi CPC: ONI (ENSO) + Nino bulanan (basis 1991-2020)."""
import csv as _csv
import io as _io

from . import config as C
from . import download

_SEAS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]


def _fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_sintex(csv_text, obs_months=12):
    """CSV SINTEX-F -> {obs:[{date,v}], fcst:[{date,v,lo,hi}], mean_key}.
    date = 'YYYYMMDD' (tgl 15 tiap bulan). Obs = observasi; fcst = mean prakiraan +
    pita persentil 10-90 dari anggota ensemble. Klimatologi SINTEX = 1983-2015."""
    rows = list(_csv.reader(_io.StringIO(csv_text)))
    if len(rows) < 2:
        return None
    hdr = rows[0]
    idx = {c: i for i, c in enumerate(hdr)}
    mean_key = "F2-3DVAR-Mean" if "F2-3DVAR-Mean" in idx else "Mean"
    skip = {"time", "Obs", "Mean", "F1-Mean", "F2-Mean", "F2-3DVAR-Mean"}
    members = [c for c in hdr if c not in skip]

    def pct(vals, p):
        if not vals:
            return None
        s = sorted(vals)
        i = min(len(s) - 1, max(0, round((p / 100) * (len(s) - 1))))
        return s[i]

    obs, fcst = [], []
    for r in rows[1:]:
        if not r or not r[0]:
            continue
        date = r[0].replace("-", "")            # 2026-08-15 -> 20260815
        o = _fnum(r[idx["Obs"]]) if "Obs" in idx else None
        if o is not None:
            obs.append({"date": date, "v": round(o, 2)})
            continue
        m = _fnum(r[idx[mean_key]])
        if m is None:
            continue
        vals = [v for v in (_fnum(r[idx[c]]) for c in members) if v is not None]
        row = {"date": date, "v": round(m, 2)}
        if len(vals) >= 3:
            row["lo"] = round(pct(vals, 10), 2)
            row["hi"] = round(pct(vals, 90), 2)
        fcst.append(row)
    if obs_months and len(obs) > obs_months:
        obs = obs[-obs_months:]
    return {"obs": obs, "fcst": fcst, "mean_key": mean_key}


def fetch_sintex():
    """Ambil prakiraan musiman SINTEX-F untuk Nino3.4 & DMI. Kembalikan dict {key: parsed}."""
    out = {}
    for k, url in C.SINTEX.items():
        try:
            s = parse_sintex(download.fetch_text(url), C.SINTEX_OBS_MONTHS)
            if s and (s["obs"] or s["fcst"]):
                out[k] = s
                print(f"  SINTEX {k}: obs {len(s['obs'])}, fcst {len(s['fcst'])} ({s['mean_key']})")
        except Exception as e:
            print(f"  PERINGATAN SINTEX {k} gagal:", e)
    return out

# Wilayah Nino (urut timur -> barat) + label tampil
NINO_KEYS = ("nino12", "nino3", "nino34", "nino4")
NINO_LABELS = {"nino12": "Nino 1+2", "nino3": "Nino 3", "nino34": "Nino 3.4", "nino4": "Nino 4"}


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
    """Ambil ONI + Nino bulanan CPC (keempat wilayah). Kembalikan dict untuk frontend."""
    oni = parse_oni(download.fetch_text(C.CPC_ONI))
    nino = parse_nino_monthly(download.fetch_text(C.CPC_NINO_MON))
    latest_oni = oni[-1] if oni else None
    recent = nino[-months:]
    labels = [f"{r['year']}-{r['mon']:02d}" for r in recent]
    series = {k: [r[k] for r in recent] for k in NINO_KEYS}   # {wilayah: [anom bulanan...]}
    oni_series = [{"label": f"{r['seas']} {r['year']}", "v": round(r["anom"], 2)} for r in oni[-months:]]
    return {
        "oni_latest": latest_oni,
        "oni_status": enso_status(latest_oni["anom"]) if latest_oni else None,
        "nino_series": series,
        "series_labels": labels,
        "oni_series": oni_series,
    }
