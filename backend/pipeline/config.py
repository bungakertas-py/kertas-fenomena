"""Konfigurasi pipeline Kertas Fenomena v1 (ENSO + IOD).

Sumber data:
- Peta anomali SST: NOAA OISST v2.1 harian (NCEI), var `sst`.
- Klimatologi 1991-2020: PSL monthly LTM (diciutkan ke 1 derajat, aset statis).
- Indeks resmi ENSO: CPC (ONI + Nino bulanan basis 1991-2020).
Anomali dihitung sendiri: sst_harian - klim_bulanan[bulan] (basis 1991-2020, konsisten CPC).
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
OUT_DIR = os.path.join(ROOT, "frontend", "data", "output")
CLIM_PATH = os.path.join(BACKEND, "data", "clim_sst_1deg.npz")

# --- Grid & domain ---
COARSEN = 4                     # 0.25 derajat -> 1 derajat (blok 4x4)
# Domain konvensi lon 0-360 (Pasifik di tengah). 30E .. 290E (=70W), 30S..30N.
LON_MIN, LON_MAX = 30.0, 290.0
LAT_MIN, LAT_MAX = -30.0, 30.0

# --- Frame waktu (peta harian terakhir) ---
N_DAYS = 10                     # jumlah peta harian (mundur dari tanggal terbaru)

# --- Skala warna anomali (diverging, degC) ---
ANOM_ABS = 3.0                  # -3 .. +3

# --- Kotak indeks (lat0,lat1, lon0,lon1) konvensi lon 0-360 ---
BOXES = {
    "nino12":  (-10.0, 0.0, 270.0, 280.0),   # 90W-80W
    "nino3":   (-5.0, 5.0, 210.0, 270.0),    # 150W-90W
    "nino34":  (-5.0, 5.0, 190.0, 240.0),    # 170W-120W
    "nino4":   (-5.0, 5.0, 160.0, 210.0),    # 160E-150W
    "iod_west":(-10.0, 10.0, 50.0, 70.0),
    "iod_east":(-10.0, 0.0, 90.0, 110.0),
}

# --- Sumber ---
OISST_BASE = "https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr"
PSL_LTM = "https://downloads.psl.noaa.gov/Datasets/noaa.oisst.v2.highres/sst.mon.ltm.1991-2020.nc"
CPC_ONI = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
CPC_NINO_MON = "https://www.cpc.ncep.noaa.gov/data/indices/ersst5.nino.mth.91-20.ascii"

# --- Ambang status ---
# ENSO (ONI): >=+0.5 El Nino, <=-0.5 La Nina (resmi butuh 5 musim beruntun; kita label indikatif)
ENSO_THRESH = 0.5
# IOD (DMI): >=+0.4 positif, <=-0.4 negatif (ambang BoM)
IOD_THRESH = 0.4
