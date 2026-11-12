"""Costruisce la griglia a 0,25 gradi che copre il territorio italiano (terraferma e isole).

Input: shapefile ISTAT dei confini provinciali (ProvCM*_WGS84.shp, proiezione UTM 32N) e
regionali (Reg*_WGS84.dbf, solo per i nomi delle regioni).
Output: CSV con un punto per cella che interseca il territorio.

I punti sono sui multipli di 0,25 gradi (la griglia nativa di ERA5); la cella di un punto e'
il quadrato di lato 0,25 centrato sul punto. Per ogni cella si calcolano la quota di superficie
in territorio italiano (land_fraction) e la provincia/regione prevalente.

Solo numpy: lo shapefile e' letto a mano e le aree sono stimate rasterizzando i poligoni
con SUB x SUB pixel per cella.

Uso: python build_grid.py <cartella ISTAT estratta> <output.csv>
"""
import csv
import struct
import sys
from pathlib import Path

import numpy as np

STEP = 0.25
SUB = 20  # pixel per lato di cella
D = STEP / SUB
# Estensione del raster, allineata ai bordi delle celle (centri sui multipli di 0,25)
LON_MIN, LON_MAX = 6.0 - STEP / 2, 19.0 + STEP / 2
LAT_MIN, LAT_MAX = 35.0 - STEP / 2, 47.5 + STEP / 2
NX = round((LON_MAX - LON_MIN) / D)
NY = round((LAT_MAX - LAT_MIN) / D)


def read_dbf(path: Path) -> list[dict]:
    raw = path.read_bytes()
    n_records, header_len, record_len = struct.unpack("<IHH", raw[4:12])
    fields, offset = [], 32
    while raw[offset] != 0x0D:
        name = raw[offset:offset + 11].split(b"\x00")[0].decode("ascii")
        fields.append((name, raw[offset + 16]))
        offset += 32
    rows = []
    for i in range(n_records):
        record = raw[header_len + i * record_len: header_len + (i + 1) * record_len]
        position, row = 1, {}
        for name, length in fields:
            chunk = record[position:position + length]
            try:
                row[name] = chunk.decode("utf-8").strip()
            except UnicodeDecodeError:
                row[name] = chunk.decode("cp1252").strip()
            position += length
        rows.append(row)
    return rows


def read_shp(path: Path) -> list[list[np.ndarray]]:
    """Restituisce, per ogni record, la lista dei suoi anelli come array (n, 2) di coordinate."""
    raw = path.read_bytes()
    shapes, offset = [], 100
    while offset < len(raw):
        (content_words,) = struct.unpack(">i", raw[offset + 4:offset + 8])
        content = raw[offset + 8: offset + 8 + content_words * 2]
        offset += 8 + content_words * 2
        (shape_type,) = struct.unpack("<i", content[:4])
        if shape_type == 0:
            shapes.append([])
            continue
        if shape_type not in (5, 15, 25):
            raise ValueError(f"tipo di shape non gestito: {shape_type}")
        n_parts, n_points = struct.unpack("<ii", content[36:44])
        parts = np.frombuffer(content, dtype="<i4", count=n_parts, offset=44)
        points = np.frombuffer(content, dtype="<f8", count=n_points * 2, offset=44 + 4 * n_parts)
        points = points.reshape(-1, 2)
        bounds = list(parts) + [n_points]
        shapes.append([points[bounds[i]:bounds[i + 1]] for i in range(n_parts)])
    return shapes


def utm32n_to_lonlat(easting: np.ndarray, northing: np.ndarray):
    """Inversa della Mercatore trasversa (serie di Krueger), WGS84, zona 32N."""
    a, f, k0, lon0 = 6378137.0, 1 / 298.257223563, 0.9996, np.radians(9.0)
    n = f / (2 - f)
    big_a = a / (1 + n) * (1 + n**2 / 4 + n**4 / 64)
    beta = (n / 2 - 2 * n**2 / 3 + 37 * n**3 / 96, n**2 / 48 + n**3 / 15, 17 * n**3 / 480)
    delta = (2 * n - 2 * n**2 / 3 - 2 * n**3, 7 * n**2 / 3 - 8 * n**3 / 5, 56 * n**3 / 15)
    xi = northing / (k0 * big_a)
    eta = (easting - 500000.0) / (k0 * big_a)
    xi_p, eta_p = xi.copy(), eta.copy()
    for j, b in enumerate(beta, start=1):
        xi_p -= b * np.sin(2 * j * xi) * np.cosh(2 * j * eta)
        eta_p -= b * np.cos(2 * j * xi) * np.sinh(2 * j * eta)
    chi = np.arcsin(np.sin(xi_p) / np.cosh(eta_p))
    lat = chi + sum(d * np.sin(2 * j * chi) for j, d in enumerate(delta, start=1))
    lon = lon0 + np.arctan2(np.sinh(eta_p), np.cos(xi_p))
    return np.degrees(lon), np.degrees(lat)


def rasterize(rings_lonlat: list[np.ndarray]) -> np.ndarray:
    """Maschera (NY, NX) dei pixel il cui centro cade nel poligono (regola pari-dispari)."""
    counts = np.zeros((NY, NX + 1), dtype=np.int32)
    for ring in rings_lonlat:
        u = (ring[:, 0] - LON_MIN) / D - 0.5  # coordinate in unita' di pixel, centri sugli interi
        v = (ring[:, 1] - LAT_MIN) / D - 0.5
        u1, v1, u2, v2 = u[:-1], v[:-1], u[1:], v[1:]
        low = np.ceil(np.minimum(v1, v2)).astype(np.int64)
        high = np.ceil(np.maximum(v1, v2)).astype(np.int64) - 1
        n_rows = np.maximum(high - low + 1, 0)
        if not n_rows.any():
            continue
        edge = np.repeat(np.arange(len(u1)), n_rows)
        starts = np.cumsum(n_rows) - n_rows
        row = low[edge] + (np.arange(len(edge)) - starts[edge])
        cross = u1[edge] + (row - v1[edge]) / (v2[edge] - v1[edge]) * (u2[edge] - u1[edge])
        column = np.clip(np.ceil(cross).astype(np.int64), 0, NX)
        keep = (row >= 0) & (row < NY)
        np.add.at(counts, (row[keep], column[keep]), 1)
    return (np.cumsum(counts, axis=1)[:, :NX] % 2).astype(bool)


def main(istat_dir: str, output: str):
    base = Path(istat_dir)
    prov_shp = next(base.glob("ProvCM*/*.shp"))
    provinces = read_dbf(prov_shp.with_suffix(".dbf"))
    regions = {int(r["COD_REG"]): r["DEN_REG"] for r in read_dbf(next(base.glob("Reg*/*.dbf")))}
    shapes = read_shp(prov_shp)
    assert len(shapes) == len(provinces)

    n_cx, n_cy = NX // SUB, NY // SUB
    prov_raster = np.zeros((NY, NX), dtype=np.int16)  # indice provincia + 1, 0 = fuori
    vertex_hits = {}  # (iy, ix) -> indice provincia, per le isole piu' piccole di un pixel
    for index, rings in enumerate(shapes):
        rings_ll = []
        for ring in rings:
            lon, lat = utm32n_to_lonlat(ring[:, 0].copy(), ring[:, 1].copy())
            rings_ll.append(np.column_stack([lon, lat]))
            ix = np.floor((lon - LON_MIN) / STEP).astype(int)
            iy = np.floor((lat - LAT_MIN) / STEP).astype(int)
            if ix.min() < 0 or iy.min() < 0 or ix.max() >= n_cx or iy.max() >= n_cy:
                raise ValueError("territorio fuori dall'estensione del raster")
            for cell in set(zip(iy.tolist(), ix.tolist())):
                vertex_hits.setdefault(cell, index)
        prov_raster[rasterize(rings_ll)] = index + 1

    cells = prov_raster.reshape(n_cy, SUB, n_cx, SUB).transpose(0, 2, 1, 3).reshape(n_cy, n_cx, SUB * SUB)
    rows = []
    for iy in range(n_cy):
        for ix in range(n_cx):
            pixels = cells[iy, ix]
            land = pixels[pixels > 0]
            if len(land):
                prov_index = int(np.bincount(land).argmax()) - 1
            elif (iy, ix) in vertex_hits:
                prov_index = vertex_hits[(iy, ix)]
            else:
                continue
            lat = LAT_MIN + STEP / 2 + iy * STEP
            lon = LON_MIN + STEP / 2 + ix * STEP
            prov = provinces[prov_index]
            cod_reg = int(prov["COD_REG"])
            rows.append({
                "grid_id": f"{lat:.2f}_{lon:.2f}",
                "latitude": f"{lat:.2f}",
                "longitude": f"{lon:.2f}",
                "land_fraction": f"{len(land) / (SUB * SUB):.4f}",
                "cod_reg": cod_reg,
                "den_reg": regions[cod_reg],
                "cod_prov": int(prov["COD_PROV"]),
                "den_prov": prov["DEN_UTS"],
                "sigla_prov": prov["SIGLA"],
            })

    with open(output, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} punti scritti in {output}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
