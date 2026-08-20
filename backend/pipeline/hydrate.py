"""Ambil data yang SUDAH ada di situs live, alih alih membuatnya ulang dari nol.

Dipakai untuk push yang cuma menyentuh tampilan. Runner GitHub selalu mulai bersih,
jadi tanpa ini setiap ubah satu baris CSS pun harus mengunduh 18 GB dan merender
ratusan frame lagi, sekitar 21 menit. Padahal datanya sudah tayang dan masih segar.

Daftar berkas diambil dari `climate.json` situs live, jadi tak ada daftar yang perlu
dijaga manual. Kalau ada satu saja yang gagal, skrip keluar dengan kode 1 supaya
workflow balik ke pipeline penuh. Lebih baik lama daripada tayang dengan data bolong.

URL diambil dari env SITE_DATA_URL, di-set oleh workflow.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config as C

SITE = os.environ.get("SITE_DATA_URL", "").rstrip("/")
WORKERS = 8


def _sesi():
    s = requests.Session()
    # Runner kadang kena hambatan jaringan sesaat. Tanpa retry, satu sendat = jalur cepat batal.
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=4, backoff_factor=2,
                                                      status_forcelist=[429, 500, 502, 503, 504])))
    return s


def daftar_berkas(doc):
    """Semua berkas yang ditunjuk climate.json. Ikut struktur run.py, jangan diubah sepihak."""
    out = []
    lay = doc.get("layers") or {}
    for key in ("sst", "anom", "sal", "clim"):
        for fr in (lay.get(key) or {}).get("frames") or []:
            out.append(fr.get("png"))
    for lst in ((lay.get("subt") or {}).get("frames") or {}).values():   # per kedalaman
        for fr in lst or []:
            out.append(fr.get("png"))
    cur = doc.get("currents") or {}
    for fr in cur.get("frames") or []:
        out += [fr.get("vec"), fr.get("spd")]
    for lst in (cur.get("depth_frames") or {}).values():
        for fr in lst or []:
            out += [fr.get("vec"), fr.get("spd")]
    for m in (doc.get("point_data") or {}).values():
        if isinstance(m, dict):
            out.append(m.get("file"))
    return sorted({f for f in out if f})


def main():
    if not SITE:
        print("hydrate: SITE_DATA_URL kosong, tak bisa jalan.")
        return 1
    os.makedirs(C.OUT_DIR, exist_ok=True)
    s = _sesi()
    try:
        r = s.get(f"{SITE}/climate.json", timeout=(15, 60))
        r.raise_for_status()
        doc = r.json()
    except Exception as e:
        print(f"hydrate: climate.json situs live tak terbaca ({e}).")
        return 1

    berkas = daftar_berkas(doc)
    print(f"hydrate: {len(berkas)} berkas dari {SITE}")
    print(f"  data live dibuat {doc.get('generated')}, run {doc.get('run')}")
    if not berkas:
        print("hydrate: daftar berkas kosong, mencurigakan.")
        return 1

    gagal, byte = [], 0

    def ambil(nama):
        try:
            rr = s.get(f"{SITE}/{nama}", timeout=(15, 180))
            if rr.status_code != 200 or not rr.content:
                return nama, 0
            with open(os.path.join(C.OUT_DIR, nama), "wb") as f:
                f.write(rr.content)
            return None, len(rr.content)
        except Exception:
            return nama, 0

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for nama, n in ex.map(ambil, berkas):
            if nama:
                gagal.append(nama)
            byte += n

    if gagal:
        print(f"hydrate: {len(gagal)} berkas GAGAL, contoh {gagal[:5]}")
        return 1

    # climate.json ditulis PALING AKHIR. Kalau di atas ada yang gagal, tak ada manifes
    # yang kelihatan sah menunjuk berkas yang tak lengkap.
    with open(os.path.join(C.OUT_DIR, "climate.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"hydrate: selesai, {len(berkas)} berkas, {byte / 1e6:.0f} MB.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
