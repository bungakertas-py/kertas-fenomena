"""Sekali jalan (dev): poligon DARAT dari OSM (simplified land polygons, yang dipakai
OSM standard render di zoom <=9) -> frame 0-360 domain -> frontend/data/osm_land.geojson.

Data ini = coastline yang SAMA dengan tile basemap OSM di zoom kita, jadi mask data laut
ke poligon ini bikin tepi data NEMPEL PERSIS ke pantai basemap (nol jahitan).

Butuh: pyshp (shapefile), shapely. Sumber shapefile (EPSG:3857) di SHP (set env OSM_LAND_SHP).
Jalankan: python -m backend.pipeline.prep_osmland
"""
import json
import math
import os

import shapefile  # pyshp
from shapely.geometry import shape, box, mapping
from shapely.ops import unary_union, transform
from shapely.affinity import translate

from . import config as C

SHP = os.environ.get("OSM_LAND_SHP") or os.path.join(
    os.path.dirname(os.path.dirname(C.ROOT)), "simplified_land_polygons.shp")
OUT = os.path.join(C.ROOT, "frontend", "data", "osm_land.geojson")
SIMPLIFY = 0.008
R = 6378137.0


def m2ll(x, y, z=None):
    lon = x / R * 180.0 / math.pi
    lat = (2.0 * math.atan(math.exp(y / R)) - math.pi / 2.0) * 180.0 / math.pi
    return (lon, lat)


def main():
    box_e = box(C.LON_MIN, C.LAT_MIN, 180.0, C.LAT_MAX)            # 30..180
    box_w = box(-180.0, C.LAT_MIN, C.LON_MAX - 360.0, C.LAT_MAX)   # -180..-70
    parts = []
    sf = shapefile.Reader(SHP)
    n = 0
    for shp in sf.iterShapes():
        try:
            g = shape(shp.__geo_interface__)          # EPSG:3857
        except Exception:
            continue
        g = transform(m2ll, g)                        # -> lon/lat 4326
        if not g.is_valid:
            g = g.buffer(0)
        # cepat: lewati kalau di luar lintang domain
        miny, maxy = g.bounds[1], g.bounds[3]
        if maxy < C.LAT_MIN or miny > C.LAT_MAX:
            continue
        e = g.intersection(box_e)
        if not e.is_empty:
            parts.append(e)
        w = g.intersection(box_w)
        if not w.is_empty:
            parts.append(translate(w, xoff=360.0))
        n += 1
    print(f"proses {n} poligon dalam domain")
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
