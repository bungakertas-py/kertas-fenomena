"""Konfigurasi pipeline Kertas Fenomena v2 (PIVOT ke GFS).

Sumber:
- SST realtime: GFS (NOMADS filter) `TMP:surface` di laut (mask `LAND:surface`), per 3 jam.
- Angin overlay: GFS `UGRD/VGRD` 10 m, per 3 jam.
- Klimatologi: aset statis COBE-SST2 LTM 1991-2020 (`clim_sst_cobe_1deg.npz`, di-commit).
Anomali = SST GFS - klimatologi[bulan]. Indeks (Nino, ONI, DMI) dihitung dari anomali kita.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
OUT_DIR = os.path.join(ROOT, "frontend", "data", "output")
CLIM_PATH = os.path.join(BACKEND, "data", "clim_sst_cobe_1deg.npz")

# --- Domain (konvensi lon 0-360, Pasifik di tengah). Lintang diperluas -65..65 biar zona terisi ---
LON_MIN, LON_MAX = 30.0, 290.0
LAT_MIN, LAT_MAX = -65.0, 65.0
REGION = {"left_lon": LON_MIN, "right_lon": LON_MAX, "top_lat": LAT_MAX, "bottom_lat": LAT_MIN}

# --- GFS NOMADS filter ---
GFS = {
    "filter_url": "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl",
    "run_hours": [0, 6, 12, 18],
    "availability_lag_hours": 5,
}
FORECAST_HOURS = 72      # SST + angin per 3 jam sampai +72 jam
STEP_HOURS = 3
PAST_HOURS = 24          # retensi masa lampau (mirip kertas-cuaca): -24 jam dari analisis run GFS sebelumnya

# --- Skala warna ---
ANOM_ABS = 3.0                       # anomali -3..+3 degC
SST_MIN, SST_MAX = 0.0, 32.0         # SST absolut degC (colormap termal)

# --- Kotak indeks (lat0,lat1, lon0,lon1) konvensi lon 0-360 ---
BOXES = {
    "nino12":  (-10.0, 0.0, 270.0, 280.0),
    "nino3":   (-5.0, 5.0, 210.0, 270.0),
    "nino34":  (-5.0, 5.0, 190.0, 240.0),
    "nino4":   (-5.0, 5.0, 160.0, 210.0),
    "iod_west": (-10.0, 10.0, 50.0, 70.0),
    "iod_east": (-10.0, 0.0, 90.0, 110.0),
}

# --- Indeks resmi CPC (untuk ditumpang; ONI resmi + Nino bulanan) ---
CPC_ONI = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
CPC_NINO_MON = "https://www.cpc.ncep.noaa.gov/data/indices/ersst5.nino.mth.91-20.ascii"

# --- Prakiraan musiman SINTEX-F (JAMSTEC): Nino3.4 & DMI, observasi + prakiraan bulanan ---
# CSV statis: kolom Obs (observasi) + F2-3DVAR-Mean (mean prakiraan) + anggota ensemble (plume).
SINTEX = {
    "nino34": "https://www.jamstec.go.jp/virtualearth/data/SINTEX/SINTEX_Nino34.csv",
    "dmi":    "https://www.jamstec.go.jp/virtualearth/data/SINTEX/SINTEX_DMI.csv",
}
SINTEX_CLIM = "1983-2015"      # klimatologi SINTEX (beda dari COBE 1991-2020 kita)
SINTEX_SOURCE = "SINTEX-F (JAMSTEC)"
SINTEX_OBS_MONTHS = 12         # jumlah bulan observasi terakhir yang ditampilkan
OBS_CLIM = "COBE 1991-2020"    # klimatologi garis OISST/GFS kita

# --- OISST harian (NCEI): observasi SST untuk pembanding indeks vs GFS ---
# Indeks OISST dihitung dgn klimatologi COBE yg SAMA -> beda garis = murni sumber SST.
OISST_BASE = "https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr"
OISST_DAYS = 4   # ~3 hari ke belakang (observasi), sisanya di plot = GFS kini + prakiraan

# --- Arus laut permukaan FORECAST (Copernicus Marine, model laut global 1/12 deg) ---
# GFS = atmosfer (tak punya arus). Ini model laut CMEMS: arus harian analisis+forecast,
# horizon disamakan SST (per tanggal frame). Butuh akun gratis (login copernicusmarine).
CURRENTS = {
    "dataset": "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m",
    "vars": ["uo", "vo"],
    "vec_stride": 3,   # partikel velocity: ~0.25 deg (demi performa animasi leaflet-velocity)
    "label": "Copernicus (CMEMS)",
}
# --- Salinitas permukaan FORECAST (Copernicus Marine, produk PHY yg sama, variabel `so`) ---
# Login copernicusmarine yg sama dgn arus. Permukaan (0..1 m), harian analisis+forecast.
SALINITY = {
    "dataset": "cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m",
    "vars": ["so"],
    "label": "Copernicus (CMEMS)",
}
SAL_MIN, SAL_MAX = 30.0, 38.0   # salinitas permukaan PSU (colormap haline)
# Kontur kecepatan arus & point_data = resolusi ASLI (tanpa downsample).

# --- Ambang status ---
ENSO_THRESH = 0.5   # ONI/Nino3.4
IOD_THRESH = 0.4    # DMI (BoM)
