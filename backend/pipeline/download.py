"""Unduh data: OISST harian (NCEI) + teks indeks CPC.

Tahan-banting: session dgn retry + backoff (server NOAA/NCEI kadang lambat dari CI).
"""
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config as C

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "kertas-fenomena/0.1 (climate monitor)"})
_RETRY = Retry(total=5, connect=5, read=5, backoff_factor=2,
               status_forcelist=[408, 429, 500, 502, 503, 504], raise_on_status=False)
_ADAPTER = HTTPAdapter(max_retries=_RETRY)
_SESSION.mount("https://", _ADAPTER)
_SESSION.mount("http://", _ADAPTER)

# (connect, read) detik. Read panjang utk NCEI yg kadang lelet.
_TIMEOUT = (30, 150)


def _get(url, timeout=_TIMEOUT):
    r = _SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r


def _list_hrefs(url):
    return re.findall(r'href="([^"]+)"', _get(url).text)


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


def download_bytes(url):
    return _get(url).content


def fetch_text(url):
    return _get(url).text
