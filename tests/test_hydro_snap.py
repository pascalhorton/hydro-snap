import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from hydro_snap.hydro_snap import (
    _get_ordered_cells,
    _interpolate_points,
    _recondition_dem,
)


def test_interpolate_points_basic():
    line = LineString([(0, 0), (3, 0)])
    pts = _interpolate_points(line, 1.0)
    # points at 0,1,2,3 -> 4 points
    assert len(pts) == 4
    assert pts[0].x == 0.0 and pts[-1].x == 3.0


def test_get_ordered_cells_and_bounds():
    # Create a diagonal line across a 5x5 raster with unit pixels
    line = LineString([(0.5, 4.5), (4.5, 0.5)])
    transform = from_origin(0, 5, 1, 1)  # maps pixel centers like (0.5,4.5)
    shape = (5, 5)

    cells = _get_ordered_cells(line, transform, shape, 0.5)
    assert isinstance(cells, list)
    assert len(cells) > 0
    for r, c in cells:
        assert 0 <= r < shape[0]
        assert 0 <= c < shape[1]


def test_recondition_dem_changes_cells(tmp_path):
    # Create a small 5x5 DEM raster
    dem_path = tmp_path / "test_dem.tif"
    width = height = 5
    transform = from_origin(0, 5, 1, 1)

    base = np.full((height, width), 100.0, dtype="float32")
    # Make upstream higher so algorithm may need to lower next cells
    base[0, 0] = 200.0

    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "nodata": None,
        "width": width,
        "height": height,
        "count": 1,
        "crs": "EPSG:4326",
        "transform": transform,
    }

    with rasterio.open(dem_path, "w", **profile) as dst:
        dst.write(base, 1)

    # Create a stream going from top-left to bottom-right
    line = LineString([(0.5, 4.5), (4.5, 0.5)])
    streams = gpd.GeoDataFrame(geometry=[line], crs="EPSG:4326")

    src = rasterio.open(dem_path)
    new_dem = _recondition_dem(src, streams, delta=0.1)

    # The result should be a numpy array and should differ from the original
    assert isinstance(new_dem, np.ndarray)
    assert new_dem.shape == base.shape
    # At least one cell modified
    assert not np.allclose(new_dem, base)
    src.close()


def test_get_ordered_cells_reversed():
    line = LineString([(0.5, 4.5), (4.5, 0.5)])
    line_reversed = LineString([(4.5, 0.5), (0.5, 4.5)])
    transform = from_origin(0, 5, 1, 1)
    shape = (5, 5)

    cells = _get_ordered_cells(line, transform, shape, 0.5)
    cells_reversed = _get_ordered_cells(line_reversed, transform, shape, 0.5)

    assert cells[0] == cells_reversed[-1]
    assert cells[-1] == cells_reversed[0]
