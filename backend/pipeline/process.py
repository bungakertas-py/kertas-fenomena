"""Proses GFS: decode GRIB (eccodes), render SST/Anomali/Klimatologi (berpita),
velocity JSON angin, dan indeks kotak. Orientasi seragam: baris-0 = utara, kolom-0 = barat.
"""
import json
import math
import os

import numpy as np
import eccodes as ec
from PIL import Image, ImageFilter, ImageDraw

from . import config as C

MS_TO_KT = 1.943844
LAND_GEOJSON = os.path.join(C.ROOT, "frontend", "data", "osm_land.geojson")  # coastline SAMA dgn tile OSM (z<=9)
_LMASK = {}
_LCOVER = {}


def land_render_mask(west, east, north, south, W, H, erode=0):
    """Raster boolean darat (True=darat) dari poligon 10m di grid W x H utk bounds diberikan.
    Dipakai jadi alpha data: laut opaque, darat transparan (biar basemap OSM tembus di darat).
    `erode` = kikis darat n piksel (~0.08 deg/px) supaya data nembus ke garis pantai OSM (tutup jahitan)."""
    key = (round(west, 3), round(east, 3), round(north, 3), round(south, 3), W, H, erode)
    if key in _LMASK:
        return _LMASK[key]
    gj = json.load(open(LAND_GEOJSON, encoding="utf-8"))
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)

    def px(ring):
        return [((lon - west) / (east - west) * (W - 1), (north - lat) / (north - south) * (H - 1))
                for lon, lat in ring]

    for feat in gj["features"]:          # SEMUA fitur (osm_land lama + darat lintang tinggi)
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            if not poly or len(poly[0]) < 3:
                continue
            d.polygon(px(poly[0]), fill=255)
            for hole in poly[1:]:
                if len(hole) >= 3:
                    d.polygon(px(hole), fill=0)
    if erode:
        img = img.filter(ImageFilter.MinFilter(erode * 2 + 1))   # kikis darat -> data maju ke pantai OSM
    m = np.asarray(img) >= 128
    _LMASK[key] = m
    return m


# ================= Decode GRIB =================
def read_grib(path):
    """Baca semua pesan GRIB -> ({shortName: array north-up}, meta grid)."""
    fields = {}
    meta = None
    with open(path, "rb") as f:
        while True:
            g = ec.codes_grib_new_from_file(f)
            if g is None:
                break
            sn = ec.codes_get(g, "shortName")
            Ni = ec.codes_get(g, "Ni"); Nj = ec.codes_get(g, "Nj")
            la1 = ec.codes_get(g, "latitudeOfFirstGridPointInDegrees")
            la2 = ec.codes_get(g, "latitudeOfLastGridPointInDegrees")
            lo1 = ec.codes_get(g, "longitudeOfFirstGridPointInDegrees")
            lo2 = ec.codes_get(g, "longitudeOfLastGridPointInDegrees")
            vals = ec.codes_get_values(g).reshape(Nj, Ni)
            ec.codes_release(g)
            if la1 < la2:                      # jadikan baris-0 = utara
                vals = vals[::-1]; north, south = la2, la1
            else:
                north, south = la1, la2
            if lo1 > lo2:                      # jadikan kolom-0 = barat
                vals = vals[:, ::-1]; west, east = lo2, lo1
            else:
                west, east = lo1, lo2
            fields[sn] = vals.astype("f4")
            meta = {"nx": int(Ni), "ny": int(Nj), "west": float(west), "east": float(east),
                    "south": float(south), "north": float(north)}
    return fields, meta


def _pick(fields, *names):
    for n in names:
        if n in fields:
            return fields[n]
    return None


def sst_from_fields(fields):
    """SST degC di laut (mask darat via land-sea mask). NaN di darat."""
    t = _pick(fields, "t", "2t", "skt")
    lsm = _pick(fields, "lsm", "land")
    if t is None:
        raise RuntimeError(f"TMP tak ada di GRIB: {list(fields)}")
    sst = t - 273.15
    if lsm is not None:
        sst = np.where(lsm < 0.5, sst, np.nan)
    return np.clip(sst, -2.0, 40.0)


def wind_from_fields(fields):
    u = _pick(fields, "10u", "u10", "u")
    v = _pick(fields, "10v", "v10", "v")
    return u, v


# ================= Klimatologi =================
_CLIM = None
_CLIM_DOMAIN = {}


def load_clim():
    global _CLIM
    if _CLIM is None:
        z = np.load(C.CLIM_PATH)
        _CLIM = {"clim": z["clim"], "lat": z["lat"], "lon": z["lon"]}
    return _CLIM


def clim_domain(month, meta):
    """Klimatologi SST bulan (1-12) di grid domain (north-up), di-upsample halus."""
    key = (month, meta["ny"], meta["nx"])
    if key in _CLIM_DOMAIN:
        return _CLIM_DOMAIN[key]
    c = load_clim()
    m = c["clim"][month - 1]; lat = c["lat"]; lon = (c["lon"] % 360)
    ri = np.where((lat >= C.LAT_MIN) & (lat <= C.LAT_MAX))[0]      # lat menurun -> north->south
    ci = np.where((lon >= C.LON_MIN) & (lon <= C.LON_MAX))[0]      # lon menaik -> west->east
    sub = m[np.ix_(ri, ci)]
    mask = np.isfinite(sub)
    fill = float(np.nanmean(sub))
    filled = np.where(mask, sub, fill).astype("f4")
    up = np.asarray(Image.fromarray(filled, "F").resize((meta["nx"], meta["ny"]), Image.BICUBIC), dtype="f4")
    _CLIM_DOMAIN[key] = up
    return up


# ================= Colormap GRADASI MULUS (kontinu) =================
# Palet SST termal (biru dingin -> merah panas). Anomali diverging MEMAKAI biru & merah
# yang SAMA (ujung dingin #2166ac, ujung panas #a50026) supaya selaras SST/klim.
SST_POS = [0.0, 0.14, 0.30, 0.45, 0.60, 0.72, 0.83, 0.93, 1.0]
SST_RGB = [[8, 3, 107], [33, 102, 172], [67, 147, 195], [53, 200, 169], [127, 211, 79],
           [232, 208, 32], [245, 159, 0], [232, 72, 28], [165, 0, 38]]
# Anomali: palet SEISMIC diverging (biru dingin -> putih 0 -> merah panas), -3..+3 degC.
# Pusat PUTIH -> basemap anomali dibuat GELAP di frontend biar kontras.
ANOM_POS = [0.0, 0.0667, 0.1333, 0.2, 0.2667, 0.3333, 0.4, 0.4667, 0.5333, 0.6, 0.6667, 0.7333, 0.8, 0.8667, 0.9333, 1.0]
ANOM_RGB = [[0, 0, 76], [0, 0, 124], [0, 0, 172], [0, 0, 219], [17, 17, 255], [85, 85, 255],
            [153, 153, 255], [221, 221, 255], [255, 221, 221], [255, 153, 153], [255, 85, 85],
            [255, 17, 17], [230, 0, 0], [195, 0, 0], [162, 0, 0], [128, 0, 0]]
# Kecepatan arus 0..2 m/s (OCEAN): tenang = hijau/biru gelap -> deras biru muda -> putih
SPEED_POS = [0.0, 0.0667, 0.1333, 0.2, 0.2667, 0.3333, 0.4, 0.4667, 0.5333, 0.6, 0.6667, 0.7333, 0.8, 0.8667, 0.9333, 1.0]
SPEED_RGB = [[0, 128, 0], [0, 102, 17], [0, 76, 34], [0, 51, 51], [0, 25, 68], [0, 0, 85],
             [0, 26, 102], [0, 51, 119], [0, 77, 136], [0, 102, 153], [0, 128, 170],
             [51, 153, 187], [102, 179, 204], [153, 204, 221], [204, 229, 238], [255, 255, 255]]
SPEED_MAX = 2.0
# Salinitas permukaan 30..38 PSU (HALINE): navy gelap -> biru -> teal -> hijau -> kuning pucat
SAL_POS = [0.0, 0.0667, 0.1333, 0.2, 0.2667, 0.3333, 0.4, 0.4667, 0.5333, 0.6, 0.6667, 0.7333, 0.8, 0.8667, 0.9333, 1.0]
SAL_RGB = [[17, 24, 84], [23, 41, 108], [27, 59, 127], [30, 78, 140], [29, 97, 147], [27, 115, 149],
           [24, 134, 148], [28, 149, 141], [43, 163, 131], [70, 178, 118], [103, 190, 103],
           [139, 201, 93], [178, 212, 86], [209, 223, 109], [231, 233, 137], [245, 242, 170]]
COAST_FEATHER = 1.0   # blur tipis cakupan darat (px); supersampling sudah anti-alias, ini sekadar pelembut
COAST_TRIM = 1        # kikis N sel low-res dari tepi darat: buang sel laut pesisir GFS yg terkontaminasi darat


def _colormap(norm01, pos, rgb):
    rgb = np.asarray(rgb, "f4")
    out = np.stack([np.interp(norm01, pos, rgb[:, k]) for k in range(3)], axis=-1)
    return np.clip(out, 0, 255).astype("u1")


def _fill_nan_nearest(a, iters=10):
    """Isi NaN (darat) dgn rata tetangga berulang -> tepi pantai mulus, tak ada fringe gelap."""
    a = a.astype("f4").copy()
    for _ in range(iters):
        nan = ~np.isfinite(a)
        if not nan.any():
            break
        acc = np.zeros_like(a); cnt = np.zeros_like(a)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sh = np.roll(a, (dy, dx), (0, 1)); m = np.isfinite(sh)
            acc += np.where(m, np.nan_to_num(sh), 0.0); cnt += m
        newv = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
        a = np.where(nan, newv, a)
    return np.where(np.isfinite(a), a, np.nanmean(a[np.isfinite(a)]))


def _merc_warp_rows(arr, north, south):
    """Squish gambar equirectangular -> Web Mercator (arah vertikal) supaya PAS di peta Leaflet
    (imageOverlay ditaruh linear di Mercator). Tanpa ini data geser di lintang vs basemap/tile."""
    H = arr.shape[0]
    yN = math.log(math.tan(math.pi / 4 + math.radians(north) / 2))
    yS = math.log(math.tan(math.pi / 4 + math.radians(south) / 2))
    yj = yN - np.arange(H) / (H - 1) * (yN - yS)
    latj = np.degrees(2.0 * np.arctan(np.exp(yj)) - math.pi / 2)
    src = (north - latj) / (north - south) * (H - 1)
    s0 = np.clip(np.floor(src).astype(int), 0, H - 1)
    s1 = np.clip(s0 + 1, 0, H - 1)
    t = (src - s0).astype("f4")[:, None, None]
    return (arr[s0].astype("f4") * (1 - t) + arr[s1].astype("f4") * t).astype(arr.dtype)


def land_cover(west, east, north, south, W, H, ss=2):
    """Cakupan darat HALUS (0..1) via supersampling: gambar poligon di ss*W x ss*H lalu
    ciutkan -> tepi pantai anti-alias (bukan biner bergerigi)."""
    key = (round(west, 3), round(east, 3), round(north, 3), round(south, 3), W, H, ss)
    if key in _LCOVER:
        return _LCOVER[key]
    m = land_render_mask(west, east, north, south, W * ss, H * ss)   # boolean hi-res (cache sendiri)
    cov = np.asarray(Image.fromarray((m * 255).astype("u1"), "L").resize((W, H), Image.BILINEAR), dtype="f4") / 255.0
    if COAST_FEATHER:
        cov = np.asarray(Image.fromarray((cov * 255).astype("u1"), "L").filter(ImageFilter.GaussianBlur(COAST_FEATHER)), dtype="f4") / 255.0
    _LCOVER[key] = cov
    return cov


def _render_field(field, path, vmin, vmax, pos, rgb, scale=3, alpha=235, bounds=None, dilate=4):
    """Gradasi kontinu, halus dekat pantai. Bila `bounds` diberikan -> DARAT ditopeng jadi NaN
    lalu diisi ulang dari LAUT terdekat (buang rim dingin/pelangi di pantai), dan alpha pakai
    cakupan darat anti-alias (laut opaque -> darat transparan mulus). Tanpa bounds -> fallback lama."""
    ny, nx = field.shape
    mask = np.isfinite(field)
    field = field.astype("f4").copy()
    if bounds is not None:
        # KUNCI: topeng darat jadi NaN di LOW-RES sebelum upsample. Darat SST=0 (bukan NaN) -> kalau
        # dibiarkan, BICUBIC menginterpolasi laut-hangat <-> 0 di pantai -> rim navy + pelangi. Diisi
        # ulang dari laut terdekat dulu, jadi tepi pantai laut<->laut (mulus, tanpa rim).
        land_lo = land_render_mask(bounds[0], bounds[1], bounds[2], bounds[3], nx, ny)
        if COAST_TRIM:   # tumbuhkan darat 1 sel -> sel laut pesisir terkontaminasi ikut diisi ulang dari laut lepas
            land_lo = np.asarray(Image.fromarray((land_lo * 255).astype("u1"), "L").filter(ImageFilter.MaxFilter(COAST_TRIM * 2 + 1))) >= 128
        field[land_lo] = np.nan
    filled = _fill_nan_nearest(field, iters=24)
    W, H = nx * scale, ny * scale
    up = np.asarray(Image.fromarray(filled, "F").resize((W, H), Image.BICUBIC), dtype="f4")
    norm = np.clip((up - vmin) / (vmax - vmin), 0.0, 1.0)
    rgbimg = _colormap(norm, pos, rgb)
    if bounds is not None:
        cov = land_cover(bounds[0], bounds[1], bounds[2], bounds[3], W, H)   # cakupan darat anti-alias (0..1)
        a = ((1.0 - cov) * alpha).astype("u1")                # alpha anti-alias: mulus laut->darat, tanpa halo
    else:
        mimg = Image.fromarray((mask * 255).astype("u1"), "L")
        if dilate:
            mimg = mimg.filter(ImageFilter.MaxFilter(dilate * 2 + 1))
        mup = np.asarray(mimg.resize((W, H), Image.BILINEAR))
        a = np.where(mup >= 128, alpha, 0).astype("u1")
    rgba = np.dstack([rgbimg, a])
    if bounds is not None:
        rgba = _merc_warp_rows(rgba, bounds[2], bounds[3])   # equirect -> Web Mercator (sejajar basemap)
    img = Image.fromarray(rgba, "RGBA")                      # tanpa SMOOTH: cegah warna darat bocor lintas-alpha
    if path.lower().endswith(".webp"):                       # WebP q90 = ~5-7x lebih kecil dari PNG, visual sama
        img.save(path, "WEBP", quality=90, method=4, alpha_quality=100)   # method 4: encode 2-3x lebih cepat, ukuran ~sama
    else:
        img.save(path)


def render_land_png(ocean_mask, path, scale=3, color=(27, 36, 48)):
    """Siluet darat dari MASK GFS yg sama dgn SST -> tepi pantai plek sama data.
    Darat = opaque (warna slate gelap), laut = transparan. Statik (darat tak berubah)."""
    ny, nx = ocean_mask.shape
    W, H = nx * scale, ny * scale
    mup = np.asarray(Image.fromarray((ocean_mask.astype("u1") * 255), "L").resize((W, H), Image.BILINEAR))
    a = np.where(mup < 128, 255, 0).astype("u1")  # darat = <128 (kebalikan alpha SST)
    rgb = np.zeros((H, W, 3), "u1")
    rgb[..., 0], rgb[..., 1], rgb[..., 2] = color
    Image.fromarray(np.dstack([rgb, a]), "RGBA").filter(ImageFilter.SMOOTH).save(path)


def render_sst_png(sst, path, scale=3, bounds=None):
    _render_field(sst, path, C.SST_MIN, C.SST_MAX, SST_POS, SST_RGB, scale=scale, bounds=bounds)


def render_anom_png(anom, path, scale=3, bounds=None):
    _render_field(anom, path, -C.ANOM_ABS, C.ANOM_ABS, ANOM_POS, ANOM_RGB, scale=scale, bounds=bounds)


def render_speed_png(speed, path, scale=3, bounds=None):
    """Kontur kecepatan arus (magnitude m/s), 0..SPEED_MAX, darat transparan."""
    _render_field(speed, path, 0.0, SPEED_MAX, SPEED_POS, SPEED_RGB, scale=scale, bounds=bounds)


def render_salinity_png(sal, path, scale=1, bounds=None):
    """Salinitas permukaan (PSU) 30..38 dgn palet haline, darat transparan."""
    _render_field(sal, path, C.SAL_MIN, C.SAL_MAX, SAL_POS, SAL_RGB, scale=scale, bounds=bounds)


def render_subt_png(t, path, scale=1, bounds=None):
    """Suhu laut (degC) di kedalaman tertentu, palet termal SST, grid Copernicus native."""
    _render_field(t, path, C.SST_MIN, C.SST_MAX, SST_POS, SST_RGB, scale=scale, bounds=bounds)


# ================= Indeks kotak =================
def indices_from_anom(anom, meta):
    lat = np.linspace(meta["north"], meta["south"], meta["ny"])
    lon = np.linspace(meta["west"], meta["east"], meta["nx"])

    def bm(box):
        la0, la1, lo0, lo1 = box
        li = (lat >= la0) & (lat <= la1); lj = (lon >= lo0) & (lon <= lo1)
        return float(np.nanmean(anom[np.ix_(li, lj)]))

    b = {k: bm(v) for k, v in C.BOXES.items()}
    return {"nino12": round(b["nino12"], 2), "nino3": round(b["nino3"], 2),
            "nino34": round(b["nino34"], 2), "nino4": round(b["nino4"], 2),
            "dmi": round(b["iod_west"] - b["iod_east"], 2)}


# ---- Indeks OISST (observasi) dgn klimatologi COBE yg SAMA spt GFS ----
def _box_mean_grid(field, lat, lon, box):
    la0, la1, lo0, lo1 = box
    li = (lat >= la0) & (lat <= la1)
    lj = (lon >= lo0) & (lon <= lo1)
    sub = field[np.ix_(li, lj)]
    return float(np.nanmean(sub)) if np.isfinite(sub).any() else float("nan")


_CLIM_BOX = {}


def clim_box_means(month):
    if month in _CLIM_BOX:
        return _CLIM_BOX[month]
    c = load_clim()
    m = c["clim"][month - 1]
    lat = np.asarray(c["lat"]); lon = np.asarray(c["lon"]) % 360
    r = {k: _box_mean_grid(m, lat, lon, v) for k, v in C.BOXES.items()}
    _CLIM_BOX[month] = r
    return r


def oisst_indices(nc_bytes, month):
    """OISST harian (nc) -> indeks anomali kotak (Nino1+2/3/3.4/4, DMI) vs COBE clim."""
    from netCDF4 import Dataset
    ds = Dataset("inmem", mode="r", memory=nc_bytes)
    ds.set_auto_maskandscale(True)
    raw = ds.variables["sst"][0, 0]                    # MaskedArray (darat/es ter-mask)
    sst = np.ma.filled(np.ma.masked_invalid(raw).astype("f4"), np.nan)  # mask -> NaN (bukan .data mentah)
    lat = np.asarray(ds.variables["lat"][:]); lon = np.asarray(ds.variables["lon"][:]) % 360
    ds.close()
    cb = clim_box_means(month)
    b = {k: _box_mean_grid(sst, lat, lon, v) - cb[k] for k, v in C.BOXES.items()}
    return {"nino12": round(b["nino12"], 2), "nino3": round(b["nino3"], 2),
            "nino34": round(b["nino34"], 2), "nino4": round(b["nino4"], 2),
            "dmi": round(b["iod_west"] - b["iod_east"], 2)}


# ================= Velocity JSON (leaflet-velocity) =================
def velocity_json(u, v, meta, run, fstep, path):
    nx, ny = meta["nx"], meta["ny"]
    dx = round((meta["east"] - meta["west"]) / (nx - 1), 4)
    dy = round((meta["north"] - meta["south"]) / (ny - 1), 4)
    header = {
        "lo1": meta["west"], "la1": meta["north"], "lo2": meta["east"], "la2": meta["south"],
        "nx": nx, "ny": ny, "dx": dx, "dy": dy,
        "parameterCategory": 2, "parameterUnit": "m.s-1",
        "refTime": run.strftime("%Y-%m-%dT%H:00:00Z"), "forecastTime": fstep,
    }
    uf = np.nan_to_num(u).astype("f4").ravel(order="C").round(2).tolist()
    vf = np.nan_to_num(v).astype("f4").ravel(order="C").round(2).tolist()
    payload = [
        {"header": {**header, "parameterNumber": 2, "parameterNumberName": "U-component_of_wind"}, "data": uf},
        {"header": {**header, "parameterNumber": 3, "parameterNumberName": "V-component_of_wind"}, "data": vf},
    ]
    with open(path, "w") as f:
        json.dump(payload, f, separators=(",", ":"))


def _write_current_frame(u, v, lat, lon, ref_time, path):
    ny, nx = u.shape
    west, east, north, south = float(lon[0]), float(lon[-1]), float(lat[0]), float(lat[-1])
    header = {
        "lo1": west, "la1": north, "lo2": east, "la2": south, "nx": nx, "ny": ny,
        "dx": round((east - west) / (nx - 1), 4), "dy": round((north - south) / (ny - 1), 4),
        "parameterCategory": 2, "parameterUnit": "m.s-1", "refTime": ref_time, "forecastTime": 0,
    }
    uf = np.nan_to_num(u).ravel(order="C").round(2).tolist()
    vf = np.nan_to_num(v).ravel(order="C").round(2).tolist()
    payload = [
        {"header": {**header, "parameterNumber": 2, "parameterNumberName": "U-component_of_current"}, "data": uf},
        {"header": {**header, "parameterNumber": 3, "parameterNumberName": "V-component_of_current"}, "data": vf},
    ]
    with open(path, "w") as f:
        json.dump(payload, f, separators=(",", ":"))


def currents_frames(nc_path, out_dir, ref_time):
    """Arus Copernicus (nc multi-waktu, lon 30..290) -> per TANGGAL:
    kontur kecepatan NATIVE `curspd_DATE.png` + vektor (distride) `cur_DATE.json`.
    Kembalikan (frames[{date,vec,spd}], native{u,v,lat,lon,dates}) utk point_data."""
    import os
    import xarray as xr
    ds = xr.open_dataset(nc_path)
    if "depth" in ds.dims:
        ds = ds.isel(depth=0)
    lat = np.asarray(ds["latitude"].values, dtype="f4")
    lon = np.asarray(ds["longitude"].values, dtype="f4")
    lat_desc = lat[0] > lat[-1]
    latN = lat if lat_desc else lat[::-1]
    cbounds = (float(lon[0]), float(lon[-1]), float(latN[0]), float(latN[-1]))
    vs = C.CURRENTS["vec_stride"]
    frames, us_all, vs_all, dates = [], [], [], []
    for ti in range(ds.sizes["time"]):
        date = str(ds["time"].values[ti])[:10].replace("-", "")
        u = np.asarray(ds["uo"].isel(time=ti).values, dtype="f4")
        v = np.asarray(ds["vo"].isel(time=ti).values, dtype="f4")
        if not lat_desc:                                  # jadikan north-up
            u = u[::-1]; v = v[::-1]
        speed = np.sqrt(u * u + v * v)                    # NATIVE (tanpa downsample)
        spd = f"curspd_{date}.webp"
        render_speed_png(speed, os.path.join(out_dir, spd), scale=1, bounds=cbounds)
        uu = u[::vs, ::vs]; vv = v[::vs, ::vs]; la = latN[::vs]; lo = lon[::vs]  # partikel distride
        vec = f"cur_{date}.json"
        _write_current_frame(uu, vv, la, lo, ref_time, os.path.join(out_dir, vec))
        frames.append({"date": date, "vec": vec, "spd": spd})
        us_all.append(u); vs_all.append(v); dates.append(date)
    ds.close()
    native = {"u": np.stack(us_all), "v": np.stack(vs_all), "lat": latN, "lon": lon, "dates": dates}
    return frames, native


def currents_hourly(nc_path, out_dir, ref_time):
    """Arus PERMUKAAN per-JAM dari PT1H (uo/vo di nc yg sama dgn SST) -> curspd_{tag}.webp +
    cur_{tag}.json per jam. Kembalikan (frames[{valid_time,vec,spd}], native{u,v,lat,lon,dates}
    HARIAN utk point_data)."""
    import os
    import xarray as xr
    from datetime import datetime, timezone
    from collections import OrderedDict
    ds = xr.open_dataset(nc_path)
    if "depth" in ds.dims:
        ds = ds.isel(depth=0)
    lat = np.asarray(ds["latitude"].values, dtype="f4")
    lon = np.asarray(ds["longitude"].values, dtype="f4")
    lat_desc = lat[0] > lat[-1]
    latN = lat if lat_desc else lat[::-1]
    cbounds = (float(lon[0]), float(lon[-1]), float(latN[0]), float(latN[-1]))
    vs = C.CURRENTS["vec_stride"]
    frames = []
    day_u, day_v = OrderedDict(), OrderedDict()
    for ti in range(ds.sizes["time"]):
        vt = datetime.fromisoformat(str(ds["time"].values[ti])[:19]).replace(tzinfo=timezone.utc)
        u = np.asarray(ds["uo"].isel(time=ti).values, dtype="f4")
        v = np.asarray(ds["vo"].isel(time=ti).values, dtype="f4")
        if not lat_desc:
            u = u[::-1]; v = v[::-1]
        tag = vt.strftime("%Y%m%d_%H")
        spd = f"curspd_{tag}.webp"
        render_speed_png(np.sqrt(u * u + v * v), os.path.join(out_dir, spd), scale=1, bounds=cbounds)
        vec = f"cur_{tag}.json"
        _write_current_frame(u[::vs, ::vs], v[::vs, ::vs], latN[::vs], lon[::vs], ref_time, os.path.join(out_dir, vec))
        frames.append({"valid_time": vt.strftime("%Y-%m-%dT%H:00:00Z"), "vec": vec, "spd": spd})
        d = vt.strftime("%Y%m%d")
        day_u.setdefault(d, []).append(u); day_v.setdefault(d, []).append(v)
    ds.close()
    dates = list(day_u.keys())
    u_daily = np.stack([np.nanmean(np.stack(day_u[d]), axis=0) for d in dates])
    v_daily = np.stack([np.nanmean(np.stack(day_v[d]), axis=0) for d in dates])
    native = {"u": u_daily, "v": v_daily, "lat": latN, "lon": lon, "dates": dates}
    return frames, native


def currents_depth(nc_path, out_dir, ref_time):
    """Arus di KEDALAMAN (P1D cur, punya dim depth) -> per (kedalaman,tanggal)
    curspd_d{k}_{DATE}.webp + cur_d{k}_{DATE}.json. Kembalikan info{depth_labels, depth_used,
    frames{'1':[...],'2':[...],'3':[...]}}. Index 1.. (0 = permukaan per-jam terpisah)."""
    import os
    import xarray as xr
    ds = xr.open_dataset(nc_path)
    lat = np.asarray(ds["latitude"].values, dtype="f4")
    lon = np.asarray(ds["longitude"].values, dtype="f4")
    lat_desc = lat[0] > lat[-1]
    latN = lat if lat_desc else lat[::-1]
    cbounds = (float(lon[0]), float(lon[-1]), float(latN[0]), float(latN[-1]))
    vs = C.CURRENTS["vec_stride"]
    depvals = np.asarray(ds["depth"].values, dtype="f4")
    targets = C.CURRENTS["depths"]
    lev_idx = [int(np.argmin(np.abs(depvals - t))) for t in targets]
    used = [round(float(depvals[i]), 1) for i in lev_idx]
    dates = [str(ds["time"].values[ti])[:10].replace("-", "") for ti in range(ds.sizes["time"])]
    frames = {}
    for k, di in enumerate(lev_idx, start=1):
        lst = []
        for ti in range(ds.sizes["time"]):
            u = np.asarray(ds["uo"].isel(time=ti, depth=di).values, dtype="f4")
            v = np.asarray(ds["vo"].isel(time=ti, depth=di).values, dtype="f4")
            if not lat_desc:
                u = u[::-1]; v = v[::-1]
            spd = f"curspd_d{k}_{dates[ti]}.webp"
            render_speed_png(np.sqrt(u * u + v * v), os.path.join(out_dir, spd), scale=1, bounds=cbounds)
            vec = f"cur_d{k}_{dates[ti]}.json"
            _write_current_frame(u[::vs, ::vs], v[::vs, ::vs], latN[::vs], lon[::vs], ref_time, os.path.join(out_dir, vec))
            lst.append({"date": dates[ti], "vec": vec, "spd": spd})
        frames[str(k)] = lst
    ds.close()
    return {"depth_labels": [f"{t} m" for t in targets], "depth_used": used, "frames": frames}


def salinity_frames(nc_path, out_dir):
    """Salinitas Copernicus (nc multi-waktu, var `so`) -> per TANGGAL `sal_DATE.png` NATIVE.
    Kembalikan (frames[{date,png}], native{sal,lat,lon,dates}) utk point_data."""
    import os
    import xarray as xr
    ds = xr.open_dataset(nc_path)
    if "depth" in ds.dims:
        ds = ds.isel(depth=0)
    lat = np.asarray(ds["latitude"].values, dtype="f4")
    lon = np.asarray(ds["longitude"].values, dtype="f4")
    lat_desc = lat[0] > lat[-1]
    latN = lat if lat_desc else lat[::-1]
    sbounds = (float(lon[0]), float(lon[-1]), float(latN[0]), float(latN[-1]))
    frames, sal_all, dates = [], [], []
    for ti in range(ds.sizes["time"]):
        date = str(ds["time"].values[ti])[:10].replace("-", "")
        so = np.asarray(ds["so"].isel(time=ti).values, dtype="f4")   # darat/es = NaN (masked)
        if not lat_desc:
            so = so[::-1]                                             # north-up
        png = f"sal_{date}.webp"
        render_salinity_png(so, os.path.join(out_dir, png), scale=1, bounds=sbounds)
        frames.append({"date": date, "png": png})
        sal_all.append(so); dates.append(date)
    ds.close()
    native = {"sal": np.stack(sal_all), "lat": latN, "lon": lon, "dates": dates}
    return frames, native


def sst_hourly_steps(nc_path, out_dir):
    """SST MODEL LAUT per-jam (thetao permukaan CMEMS PT1H-m) -> render per JAM `sst_{tag}.webp`
    di grid CMEMS 1/12 native. Kembalikan (per_step[{vt,date,month,sst,png}], meta, sea_mask).
    Ganti sumber SST GFS; downstream (anom harian, indeks, klim, pd) pakai meta ini apa adanya."""
    import os
    import xarray as xr
    from datetime import datetime, timezone
    ds = xr.open_dataset(nc_path)
    if "depth" in ds.dims:
        ds = ds.isel(depth=0)                          # permukaan (level terdangkal ~0.5 m)
    var = C.SST_CMEMS["var"]
    lat = np.asarray(ds["latitude"].values, dtype="f4")
    lon = np.asarray(ds["longitude"].values, dtype="f4")
    lat_desc = lat[0] > lat[-1]
    latN = lat if lat_desc else lat[::-1]
    W_, E_, N_, S_ = float(lon[0]), float(lon[-1]), float(latN[0]), float(latN[-1])
    meta = {"nx": int(len(lon)), "ny": int(len(latN)), "west": W_, "east": E_, "south": S_, "north": N_}
    bounds = (W_, E_, N_, S_)
    per_step, sea_mask = [], None
    for ti in range(ds.sizes["time"]):
        vt = datetime.fromisoformat(str(ds["time"].values[ti])[:19]).replace(tzinfo=timezone.utc)
        sst = np.asarray(ds[var].isel(time=ti).values, dtype="f4")     # darat = NaN (masked)
        if not lat_desc:
            sst = sst[::-1]                                            # north-up
        if sea_mask is None:
            sea_mask = np.isfinite(sst)
        tag = vt.strftime("%Y%m%d_%H")
        png = f"sst_{tag}.webp"
        render_sst_png(sst, os.path.join(out_dir, png), scale=1, bounds=bounds)
        per_step.append({"vt": vt, "date": vt.strftime("%Y%m%d"), "month": vt.month, "sst": sst, "png": png})
    ds.close()
    return per_step, meta, sea_mask


def subtemp_frames(nc_path, out_dir):
    """Suhu laut Copernicus (`thetao`, banyak kedalaman) -> per (kedalaman target, tanggal)
    `subt_{k}_{DATE}.webp` NATIVE. Kembalikan info{depths, depth_labels, depth_used, frames, bounds}."""
    import os
    import xarray as xr
    ds = xr.open_dataset(nc_path)
    lat = np.asarray(ds["latitude"].values, dtype="f4")
    lon = np.asarray(ds["longitude"].values, dtype="f4")
    lat_desc = lat[0] > lat[-1]
    latN = lat if lat_desc else lat[::-1]
    sbounds = (float(lon[0]), float(lon[-1]), float(latN[0]), float(latN[-1]))
    depvals = np.asarray(ds["depth"].values, dtype="f4")
    targets = C.SUBTEMP["depths"]
    lev_idx = [int(np.argmin(np.abs(depvals - t))) for t in targets]     # level CMEMS terdekat tiap target
    used = [round(float(depvals[i]), 1) for i in lev_idx]
    dates = [str(ds["time"].values[ti])[:10].replace("-", "") for ti in range(ds.sizes["time"])]
    frames = {}
    for k, di in enumerate(lev_idx):
        lst = []
        for ti in range(ds.sizes["time"]):
            t2 = np.asarray(ds["thetao"].isel(time=ti, depth=di).values, dtype="f4")
            if not lat_desc:
                t2 = t2[::-1]
            png = f"subt_{k}_{dates[ti]}.webp"
            render_subt_png(t2, os.path.join(out_dir, png), scale=1, bounds=sbounds)
            lst.append({"date": dates[ti], "png": png})
        frames[str(k)] = lst
    ds.close()
    return {"depths": list(targets), "depth_used": used, "depth_labels": [f"{t} m" for t in targets],
            "frames": frames, "bounds": sbounds, "dates": dates}


# ================= Point data (grid mentah utk klik-titik) =================
def pack_grid(stack, scale):
    """(nt,ny,nx) atau (ncomp,nt,ny,nx) float -> int16 gzip (NaN=-32768)."""
    import gzip
    fin = np.isfinite(stack)
    a = np.clip(np.round(np.asarray(stack) / scale), -32767, 32767)   # clip DATA dulu
    a = np.where(fin, a, -32768).astype("<i2")                        # sentinel NaN = -32768 (jangan ke-clip)
    return gzip.compress(a.tobytes(), 6)
