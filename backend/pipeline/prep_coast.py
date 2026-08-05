"""Sekali jalan: bikin garis pantai domain (0-360) dari world_countries.geojson.

Sumber = geojson dunia milik kertas-cuaca (Natural Earth). Dipotong ke domain di
DUA belahan (timur 30..180, barat -180..-70) lalu belahan barat digeser +360,
sehingga hasil ada di frame 0-360 kontinu (30..290) TANPA artefak garis nyebrang
antimeridian/prime-meridian. Output frontend/data/coast.geojson (kecil), di-commit.

Jalankan: python -m backend.pipeline.prep_coast
"""
import json
import os

from shapely.geometry import shape, box, mapping
from shapely.affinity import translate
from shapely.ops import unary_union

from . import config as C

# Sumber geojson dunia (punya kertas-cuaca; dev-time saja, tak perlu di repo ini)
SRC = os.path.join(os.path.dirname(C.ROOT), "kertas-cuaca", "frontend", "data", "world_countries.geojson")
OUT = os.path.join(C.ROOT, "frontend", "data", "coast.geojson")
SIMPLIFY = 0.04  # derajat, perkecil ukuran


def main():
    with open(SRC, "r", encoding="utf-8") as f:
        gj = json.load(f)

    box_e = box(C.LON_MIN, C.LAT_MIN, 180.0, C.LAT_MAX)          # 30..180
    box_w = box(-180.0, C.LAT_MIN, C.LON_MAX - 360.0, C.LAT_MAX)  # -180..-70

    parts = []
    for feat in gj.get("features", []):
        try:
            g = shape(feat["geometry"])
        except Exception:
            continue
        if not g.is_valid:
            g = g.buffer(0)
        e = g.intersection(box_e)
        if not e.is_empty:
            parts.append(e)
        w = g.intersection(box_w)
        if not w.is_empty:
            parts.append(translate(w, xoff=360.0))  # geser ke 0-360

    merged = unary_union(parts).simplify(SIMPLIFY, preserve_topology=True)

    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": mapping(merged)}
    ]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(fc, f)
    print(f"Simpan {OUT}  ({os.path.getsize(OUT):,} bytes)")


if __name__ == "__main__":
    main()
