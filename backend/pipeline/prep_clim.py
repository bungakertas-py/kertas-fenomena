"""Sekali jalan: unduh klimatologi bulanan OISST 1991-2020 (PSL, ~46MB),
ciutkan ke 1 derajat, simpan aset statis backend/data/clim_sst_1deg.npz.

Jalankan: python -m backend.pipeline.prep_clim  (atau langsung file ini)
Hasil dipakai run.py untuk menghitung anomali (basis 1991-2020).
"""
import io
import os
import numpy as np
import requests
from netCDF4 import Dataset

from . import config as C


def coarsen_mean(arr, k):
    """Rata-rata blok kxk, abaikan NaN. arr: (ny,nx) -> (ny//k, nx//k)."""
    ny, nx = arr.shape
    ny2, nx2 = ny // k, nx // k
    arr = arr[: ny2 * k, : nx2 * k].reshape(ny2, k, nx2, k)
    return np.nanmean(arr, axis=(1, 3))


def main():
    os.makedirs(os.path.dirname(C.CLIM_PATH), exist_ok=True)
    print("Unduh LTM 1991-2020 ...", C.PSL_LTM)
    r = requests.get(C.PSL_LTM, timeout=180)
    r.raise_for_status()
    ds = Dataset("inmem", mode="r", memory=r.content)
    lat = np.array(ds.variables["lat"][:], dtype="f4")
    lon = np.array(ds.variables["lon"][:], dtype="f4")
    sst = ds.variables["sst"][:]  # (time=12, [zlev], lat, lon) masked
    sst = np.ma.squeeze(sst)      # -> (12, lat, lon) diharapkan
    if sst.ndim != 3:
        raise SystemExit(f"Bentuk LTM tak terduga: {sst.shape}")
    print("LTM shape:", sst.shape, "lat", lat.size, "lon", lon.size)

    # ke float dgn NaN utk daratan
    sstf = np.ma.filled(sst.astype("f4"), np.nan)

    k = C.COARSEN
    clim = np.stack([coarsen_mean(sstf[m], k) for m in range(sstf.shape[0])])  # (12, ny, nx)
    lat1 = lat[: (lat.size // k) * k].reshape(-1, k).mean(axis=1)  # rata-rata tiap 4 lintang
    lon1 = lon[: (lon.size // k) * k].reshape(-1, k).mean(axis=1)

    np.savez_compressed(C.CLIM_PATH, clim=clim.astype("f4"), lat=lat1.astype("f4"), lon=lon1.astype("f4"))
    sz = os.path.getsize(C.CLIM_PATH)
    print(f"Simpan {C.CLIM_PATH}  ({sz:,} bytes)  clim shape {clim.shape}")
    print("lat1", lat1[0], "..", lat1[-1], "  lon1", lon1[0], "..", lon1[-1])
    # sanity: rata-rata global Januari (harus ~ suhu laut wajar)
    print("clim[Jan] nanmean %.2f degC" % np.nanmean(clim[0]))


if __name__ == "__main__":
    main()
