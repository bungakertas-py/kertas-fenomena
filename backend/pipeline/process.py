"""Proses grid: baca OISST resolusi asli 0.25, hitung anomali, render PNG, indeks kotak.

Data SST dipakai resolusi asli 0.25 derajat (detail, tampilan mulus). Klimatologi
disimpan 1 derajat (aset kecil) lalu di-upsample halus ke 0.25 saat menghitung anomali
(klimatologi bervariasi mulus, jadi upsample tak kehilangan info berarti).
"""
import numpy as np
from netCDF4 import Dataset
from PIL import Image, ImageFilter

from . import config as C

_CLIM = None
_CLIM_NAT = {}


def load_clim():
    global _CLIM
    if _CLIM is None:
        z = np.load(C.CLIM_PATH)
        _CLIM = z["clim"]  # (12,180,360)
    return _CLIM


def clim_native(month, ny=720, nx=1440):
    """Klimatologi bulan (1-12) di-upsample ke grid OISST asli (720x1440)."""
    if month not in _CLIM_NAT:
        m = load_clim()[month - 1]
        mask = ~np.isnan(m)
        fill = float(np.nanmean(m))
        filled = np.where(mask, m, fill).astype("f4")
        up = np.asarray(Image.fromarray(filled, "F").resize((nx, ny), Image.BICUBIC), dtype="f4")
        _CLIM_NAT[month] = up
    return _CLIM_NAT[month]


def read_sst_native(nc_bytes):
    """OISST harian -> (sst 720x1440 dgn NaN, lat, lon) resolusi asli 0.25."""
    ds = Dataset("inmem", mode="r", memory=nc_bytes)
    sst = ds.variables["sst"][0, 0]
    lat = np.array(ds.variables["lat"][:], dtype="f4")
    lon = np.array(ds.variables["lon"][:], dtype="f4")
    sstf = np.ma.filled(sst.astype("f4"), np.nan)
    ds.close()
    return sstf, lat, lon


def anomaly(sst_native, month):
    """Anomali basis 1991-2020 di resolusi asli."""
    return sst_native - clim_native(month, sst_native.shape[0], sst_native.shape[1])


# --- Indeks kotak ---
def _box_mean(field, lat, lon, box):
    la0, la1, lo0, lo1 = box
    li = (lat >= la0) & (lat <= la1)
    lj = (lon >= lo0) & (lon <= lo1)
    return float(np.nanmean(field[np.ix_(li, lj)]))


def indices(anom, lat, lon):
    b = {k: _box_mean(anom, lat, lon, v) for k, v in C.BOXES.items()}
    return {
        "nino12": round(b["nino12"], 2), "nino3": round(b["nino3"], 2),
        "nino34": round(b["nino34"], 2), "nino4": round(b["nino4"], 2),
        "dmi": round(b["iod_west"] - b["iod_east"], 2),
    }


# --- Colormap diverging (cocok legenda frontend) ---
_STOPS = np.array([-1.0, -0.5, 0.0, 0.5, 1.0])
_COLORS = np.array([
    [33, 102, 172], [103, 169, 207], [247, 247, 247], [239, 138, 98], [178, 24, 43],
], dtype="f4")


def _colormap(norm):
    r = np.interp(norm, _STOPS, _COLORS[:, 0])
    g = np.interp(norm, _STOPS, _COLORS[:, 1])
    b = np.interp(norm, _STOPS, _COLORS[:, 2])
    return np.stack([r, g, b], axis=-1)


def crop_domain(field, lat, lon):
    """Potong ke domain. Kembalikan (sub, bounds=(latS,latN,lonW,lonE) tepi sel)."""
    li = np.where((lat >= C.LAT_MIN) & (lat <= C.LAT_MAX))[0]
    lj = np.where((lon >= C.LON_MIN) & (lon <= C.LON_MAX))[0]
    sub = field[np.ix_(li, lj)]
    dlat = float(abs(lat[1] - lat[0])); dlon = float(abs(lon[1] - lon[0]))
    bounds = (
        float(lat[li[0]] - dlat / 2), float(lat[li[-1]] + dlat / 2),
        float(lon[lj[0]] - dlon / 2), float(lon[lj[-1]] + dlon / 2),
    )
    return sub, bounds


def render_anom_png(anom, lat, lon, path, scale=2):
    """Render anomali 0.25 -> PNG domain-cropped, halus. Kembalikan bounds."""
    sub, bounds = crop_domain(anom, lat, lon)
    ny, nx = sub.shape
    mask = ~np.isnan(sub)
    filled = np.where(mask, sub, 0.0).astype("f4")
    W, H = nx * scale, ny * scale
    field = np.asarray(Image.fromarray(filled, "F").resize((W, H), Image.BICUBIC), dtype="f4")
    mup = np.asarray(Image.fromarray((mask * 255).astype("u1"), "L").resize((W, H), Image.BILINEAR))

    norm = np.clip(field / C.ANOM_ABS, -1.0, 1.0)
    rgb = _colormap(norm).astype("u1")
    alpha = np.where(mup >= 128, 235, 0).astype("u1")
    rgba = np.dstack([rgb, alpha])[::-1]  # lintang naik -> baris atas = utara
    Image.fromarray(rgba, "RGBA").filter(ImageFilter.SMOOTH).save(path)
    return bounds
