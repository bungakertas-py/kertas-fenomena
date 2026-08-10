"""Unduh GFS via NOMADS filter (subset var+region, GRIB2 kecil) + teks indeks CPC.

Tahan-banting: session retry + backoff (NOMADS/CPC kadang lambat dari CI).
"""
import datetime as dt
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config as C

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "kertas-fenomena/0.2 (climate monitor)"})
_RETRY = Retry(total=5, connect=5, read=5, backoff_factor=2,
               status_forcelist=[408, 429, 500, 502, 503, 504], raise_on_status=False)
_ADAPTER = HTTPAdapter(max_retries=_RETRY)
_SESSION.mount("https://", _ADAPTER)
_SESSION.mount("http://", _ADAPTER)
_TIMEOUT = (30, 150)


def _get(url, timeout=_TIMEOUT):
    r = _SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r


def fetch_text(url):
    return _get(url).text


def download_bytes(url, timeout=(30, 180)):
    return _get(url, timeout=timeout).content


def download_currents(start_iso, end_iso, dest_path):
    """Arus forecast Copernicus (uo/vo) HARIAN untuk rentang tanggal SST -> file netCDF.
    Domain lon 30..290, kedalaman 0..250 m (utk lapisan 50/100/200; permukaan per-jam terpisah)."""
    import os
    if os.environ.get("KF_REUSE_CUR") and os.path.exists(dest_path) and os.path.getsize(dest_path) > 1_000_000:
        return dest_path   # dev: pakai nc cache (hemat unduh saat iterasi render)
    import copernicusmarine as cm
    d = os.path.dirname(dest_path); fn = os.path.basename(dest_path)
    cm.subset(
        dataset_id=C.CURRENTS["dataset"], variables=C.CURRENTS["vars"],
        minimum_longitude=C.LON_MIN, maximum_longitude=C.LON_MAX,
        minimum_latitude=C.LAT_MIN, maximum_latitude=C.LAT_MAX,
        minimum_depth=0, maximum_depth=250,
        start_datetime=start_iso, end_datetime=end_iso,
        output_filename=fn, output_directory=d, overwrite=True,
    )
    return dest_path


def download_salinity(start_iso, end_iso, dest_path):
    """Salinitas permukaan forecast Copernicus (`so`) untuk rentang tanggal SST -> netCDF.
    Domain & login sama dgn arus; permukaan saja (depth 0..1 m)."""
    import os
    if os.environ.get("KF_REUSE_SAL") and os.path.exists(dest_path) and os.path.getsize(dest_path) > 1_000_000:
        return dest_path   # dev: pakai nc cache
    import copernicusmarine as cm
    d = os.path.dirname(dest_path); fn = os.path.basename(dest_path)
    cm.subset(
        dataset_id=C.SALINITY["dataset"], variables=C.SALINITY["vars"],
        minimum_longitude=C.LON_MIN, maximum_longitude=C.LON_MAX,
        minimum_latitude=C.LAT_MIN, maximum_latitude=C.LAT_MAX,
        minimum_depth=0, maximum_depth=1,
        start_datetime=start_iso, end_datetime=end_iso,
        output_filename=fn, output_directory=d, overwrite=True,
    )
    return dest_path


def download_sst_hourly(start_iso, end_iso, dest_path):
    """Permukaan per-jam CMEMS PT1H-m: SST (thetao) + arus (uo,vo) SEKALIGUS (satu unduhan).
    Rentang waktu jam (retensi..forecast). Permukaan saja (depth 0..1 m)."""
    import os
    if os.environ.get("KF_REUSE_SSTH") and os.path.exists(dest_path) and os.path.getsize(dest_path) > 1_000_000:
        return dest_path
    import copernicusmarine as cm
    d = os.path.dirname(dest_path); fn = os.path.basename(dest_path)
    cm.subset(
        dataset_id=C.SST_CMEMS["dataset"], variables=[C.SST_CMEMS["var"], "uo", "vo"],
        minimum_longitude=C.LON_MIN, maximum_longitude=C.LON_MAX,
        minimum_latitude=C.LAT_MIN, maximum_latitude=C.LAT_MAX,
        minimum_depth=0, maximum_depth=1,
        start_datetime=start_iso, end_datetime=end_iso,
        output_filename=fn, output_directory=d, overwrite=True,
    )
    return dest_path


def download_subtemp(start_iso, end_iso, dest_path):
    """Suhu laut (`thetao`) 0-250 m forecast Copernicus -> netCDF (multi-kedalaman)."""
    import os
    if os.environ.get("KF_REUSE_SUBT") and os.path.exists(dest_path) and os.path.getsize(dest_path) > 1_000_000:
        return dest_path
    import copernicusmarine as cm
    d = os.path.dirname(dest_path); fn = os.path.basename(dest_path)
    cm.subset(
        dataset_id=C.SUBTEMP["dataset"], variables=C.SUBTEMP["vars"],
        minimum_longitude=C.LON_MIN, maximum_longitude=C.LON_MAX,
        minimum_latitude=C.LAT_MIN, maximum_latitude=C.LAT_MAX,
        minimum_depth=0, maximum_depth=250,
        start_datetime=start_iso, end_datetime=end_iso,
        output_filename=fn, output_directory=d, overwrite=True,
    )
    return dest_path


def _list_hrefs(url):
    return re.findall(r'href="([^"]+)"', _get(url, timeout=(20, 60)).text)


def latest_oisst_files(n):
    """n file OISST harian TERBARU: list (date 'YYYYMMDD', url), urut lama->baru.
    Telusuri direktori NCEI (tanpa menebak tanggal); mundur antar-bulan bila kurang.
    """
    months = sorted(m.strip("/") for m in _list_hrefs(C.OISST_BASE + "/")
                    if re.fullmatch(r"\d{6}/?", m))
    if not months:
        raise RuntimeError("Direktori OISST kosong")
    found = []  # (date, url)
    mi = len(months) - 1
    while len(found) < n and mi >= 0:
        murl = f"{C.OISST_BASE}/{months[mi]}/"
        recs = []
        for f in _list_hrefs(murl):
            m = re.search(r"v02r01\.(\d{8})", f)
            if m:
                recs.append((m.group(1), murl + f.lstrip("/")))
        recs.sort(key=lambda x: x[0])
        found = recs + found
        mi -= 1
    found.sort(key=lambda x: x[0])
    # dedup per tanggal (bisa ada _preliminary + final; ambil yg terakhir muncul)
    seen = {}
    for d, u in found:
        seen[d] = u
    out = sorted(seen.items())
    return out[-n:]


def latest_run(now_utc=None):
    """Run GFS terbaru yang kemungkinan sudah tersedia (perhitungkan jeda rilis)."""
    now = now_utc or dt.datetime.now(dt.timezone.utc)
    cand = now - dt.timedelta(hours=C.GFS["availability_lag_hours"])
    day = cand.replace(minute=0, second=0, microsecond=0)
    for h in sorted(C.GFS["run_hours"], reverse=True):
        if cand.hour >= h:
            return day.replace(hour=h)
    prev = day - dt.timedelta(days=1)
    return prev.replace(hour=max(C.GFS["run_hours"]))


def _filter_url(run, fstep, var_names, levels):
    ymd = run.strftime("%Y%m%d"); cc = run.strftime("%H"); fff = f"{fstep:03d}"
    params = {
        "file": f"gfs.t{cc}z.pgrb2.0p25.f{fff}",
        "dir": f"/gfs.{ymd}/{cc}/atmos",
        "subregion": "",
        "leftlon": C.REGION["left_lon"], "rightlon": C.REGION["right_lon"],
        "toplat": C.REGION["top_lat"], "bottomlat": C.REGION["bottom_lat"],
    }
    for lv in levels:
        params[f"lev_{lv}"] = "on"
    for v in var_names:
        params[f"var_{v}"] = "on"
    q = "&".join(f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in params.items())
    return f"{C.GFS['filter_url']}?{q}"


def download_step(run, fstep, dest):
    """Unduh satu langkah forecast: SST(TMP+LAND @surface) + angin(UGRD/VGRD @10m) -> file GRIB2.

    Satu request berisi 4 pesan. Lempar RuntimeError bila respons bukan GRIB.
    """
    url = _filter_url(run, fstep,
                      var_names=["TMP", "LAND", "UGRD", "VGRD"],
                      levels=["surface", "10_m_above_ground"])
    content = _get(url).content
    if not content.startswith(b"GRIB"):
        raise RuntimeError(f"Respons bukan GRIB (run {run:%Y%m%d %HZ} f{fstep:03d} belum ada?): "
                           f"{content[:120]!r}")
    with open(dest, "wb") as f:
        f.write(content)
    return dest


def find_run_with_data(run):
    """Cek run punya f000; kalau tidak, mundur satu siklus (maks 4x)."""
    for _ in range(4):
        try:
            url = _filter_url(run, 0, ["TMP"], ["surface"])
            if _SESSION.get(url, timeout=(20, 60)).content.startswith(b"GRIB"):
                return run
        except Exception:
            pass
        run = run - dt.timedelta(hours=6)
    raise RuntimeError("Tak menemukan run GFS dengan data")
