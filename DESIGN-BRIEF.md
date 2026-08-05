# Kertas Fenomena - Design Brief

Turunan iklim dari Kertas Cuaca. Fokus: mode iklim skala besar (bukan cuaca titik).
Acuan visual: gaya neubrutalist Kertas Cuaca (border ink 3px, hard-shadow tanpa blur,
biru #0029d7 + lime #d2ed26, font Archivo Black / Space Grotesk / JetBrains Mono).

## Keputusan (disepakati 2026-08-05)

1. **ENSO/IOD/MJO = monitoring kini + tumpang prakiraan resmi** (CPC/IRI/BoM).
   Kita TIDAK bikin prakiraan musiman sendiri (CFSv2 = Fase 2 opsional, berat).
2. **Lapis iklim global = resolusi 1 derajat** (mode planet, tak butuh halus).
3. **Arsitektur dua lapis** (lihat bawah).
4. **Repo baru terpisah**, akun personal, live sendiri. Tidak menimpa kertas-cuaca.

## Prinsip inti

- **Dua jam**: skala cuaca (jam s/d 2 minggu, GFS) vs skala iklim (minggu s/d musim, laut).
- **Deteksi vs prakiraan**: ENSO/IOD/MJO = kita deteksi keadaan kini + tampilkan prakiraan
  resmi lembaga lain. GFS tidak bisa memprakirakan mode laut.
- **Anomali**: semua mode iklim = selisih dari normal. Butuh baseline klimatologi
  (mis. 1991-2020) di-bundle sekali sebagai aset statis.
- **Frame awal tetap fokus Indonesia** (VIEW_CORE seperti kertas-cuaca), data diperluas.

## Domain

- Bujur: hampir global, ~20E (Afrika Barat / kutub barat IOD) ke timur sampai 80W
  (Niño 1+2). Garis tanggal di tengah, Indonesia tetap sentral.
- Lintang: 70N (Siberia) sampai 50S (Australia penuh + Samudra Selatan).
- Zona ENSO tercakup: Niño 1+2, 3, 3.4, 4. Kutub IOD barat (50E) & timur (90-110E).

## Arsitektur dua lapis

1. **Lapis IKLIM (global, 1 derajat)**: SST + anomali SST, OLR, angin 850 & 200,
   untuk ENSO, IOD, MJO. Frame sedikit (kini + langkah harian s/d 10-16 hari).
2. **Lapis CUACA (regional, 0.25 derajat)**: domain mirip kertas-cuaca (boleh dilebarkan),
   untuk ITCZ, Monsun, Cold Surge, Borneo Vortex, Siklon Tropis.
3. **Indeks** (ONI/Niño3.4, DMI, RMM): file teks/JSON mungil. Niño & DMI dihitung sendiri
   dari SST; RMM ditumpang dari BoM.
4. **Klimatologi baseline**: aset statis, sekali unduh, tidak diulang tiap hari.

## Parameter

Wajib: SST + anomali, OLR, angin 850, angin 200, hujan/precipitable water, MSLP,
vortisitas 925/850.
Di-cut: Skew-T / profil 22 level, kelembapan 2m, tutupan awan, CAPE. (Stratosfer 70 hPa /
QBO = opsional, sebenarnya relevan untuk MJO.)

## Fenomena: deteksi & prakiraan

| Fenomena | Deteksi kini | Prakiraan |
|---|---|---|
| ITCZ | ya (GFS konvergensi/OLR) | GFS s/d ~10 hari |
| Cold Surge | ya (angin v LCS, MSLP) | GFS s/d ~7-10 hari |
| Borneo Vortex | ya (vortisitas 925) | GFS s/d ~7 hari |
| Monsun | ya (angin 850, hujan) | aliran s/d 2 minggu |
| Siklon Tropis | ya (vortisitas, MSLP) | jalur s/d ~7 hari |
| MJO | ya (RMM + OLR/chi200) | GFS chi200 ~2 minggu / tumpang RMM BoM |
| ENSO | ya (anomali SST Niño) | tumpang plume CPC/IRI |
| IOD | ya (DMI dari SST) | tumpang outlook BoM |

## Sumber data (gratis, otomatis)

- GFS 0.25 (NOMADS) - atmosfer, sudah dipakai kertas-cuaca.
- NOAA OISST v2.1 daily - SST untuk ENSO/IOD (butuh netCDF/xarray).
- NOAA interpolated OLR (PSL) - MJO/konveksi (atau ULWRF dari GFS).
- Indeks teks: ONI/Niño3.4 (CPC), DMI, RMM (BoM). Kecil.
- Klimatologi OISST 1991-2020 (PSL) untuk anomali.

## Risiko / catatan CI

- Dependency baru (xarray, netCDF4, mungkin windspharm) WAJIB masuk requirements.txt
  (pelajaran contourpy di kertas-cuaca).
- Sumber non-GFS lebih rawan gagal di Actions, perlu retry/fallback.
- Update harian sudah cukup, mode iklim bergerak lambat.

## Status

- Belum ada kode. Menunggu desain UI dari Google Stitch (user kerjakan dulu).
