"""Unduh data: OISST harian (NCEI) + teks indeks CPC."""
import re
import requests

from . import config as C

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "kertas-fenomena/0.1 (climate monitor)"})


def _get(url, timeout=90):
    r = _SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r


def _list_hrefs(url):
    return re.findall(r'href="([^"]+)"', _get(url, timeout=45).text)


def latest_oisst_files(n):
    """Kembalikan n file OISST harian TERBARU: list (date 'YYYYMMDD', url), urut lama->baru.

    Menelusuri direktori NCEI (tanpa menebak tanggal). Ambil bulan terbaru, kalau
    kurang dari n mundur ke bulan sebelumnya.
    """
    months = sorted(m for m in _list_hrefs(C.OISST_BASE + "/") if re.fullmatch(r"\d{6}", m))
    if not months:
        raise RuntimeError("Direktori OISST kosong")
    found = []  # (date, url)
    mi = len(months) - 1
    while len(found) < n and mi >= 0:
        mm = months[mi]
        murl = f"{C.OISST_BASE}/{mm}/"
        files = _list_hrefs(murl)
        recs = []
        for f in files:
            m = re.search(r"v02r01\.(\d{8})", f)
            if m:
                recs.append((m.group(1), murl + f))
        recs.sort(key=lambda x: x[0])
        found = recs + found  # bulan lebih lama di depan
        mi -= 1
    found.sort(key=lambda x: x[0])
    return found[-n:]


def download_bytes(url, timeout=120):
    return _get(url, timeout=timeout).content


def fetch_text(url, timeout=60):
    return _get(url, timeout=timeout).text
