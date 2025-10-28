"""Utilities to recondition a DEM (digital elevation model) using a stream network.

This module provides a high-level function `recondition_dem` and several
helpers to prepare stream vectors, enforce CRS, build temporary walls at
catchment borders and perform DEM corrections.
"""

import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.features
from rasterio.crs import CRS
from rasterio.transform import rowcol
from shapely.geometry import Point, mapping
from pysheds.grid import Grid


def recondition_dem(
        dem_raster,
        streams_shp,
        output_dir,
        delta=0.0001,
        outlet_shp=None,
        catchment_shp=None,
        breaches_shp=None,
        walls_height=1000,
        epsg_code=None,
):
    """Recondition the DEM based on the stream network.

    Parameters
    ----------
    dem_raster : str
        Path to the DEM raster file.
    streams_shp : str
        Path to the streams shapefile.
    output_dir : str | Path
        Output directory.
    delta : float, optional
        Elevation difference used when lowering cells (default: 0.0001).
    outlet_shp : str, optional
        Outlet shapefile path. If provided, the catchment delineation is
        computed (default: None).
    catchment_shp : str, optional
        Catchment polygon shapefile. If provided, flow will be constrained to
        the catchment (default: None).
    breaches_shp : str, optional
        Breaches (lines) shapefile used to allow water leaving the catchment
        (required if `catchment_shp` is provided).
    walls_height : float, optional
        Height of temporary walls placed at the catchment border (default: 1000).
    epsg_code : int, optional
        EPSG code used to set CRS when missing (default: None).
    """

    if isinstance(output_dir, str):
        output_dir = Path(output_dir)

    if not output_dir.exists():
        output_dir.mkdir(parents=True)

    original_dem = _open_raster_check_crs(dem_raster, epsg_code)

    streams = _prepare_streams(streams_shp, output_dir)
    streams.to_file(output_dir / "streams.shp")

    # First pass correction following stream lines
    new_dem = _recondition_dem(original_dem, streams, delta)

    boundaries = None
    if catchment_shp:
        if not breaches_shp:
            raise ValueError(
                "A shapefile of breaches must be provided to allow water exiting the catchment."
            )
        new_dem, boundaries = _build_walls_at_catchment_borders(
            new_dem,
            catchment_shp,
            breaches_shp,
            streams_shp,
            original_dem,
            elevation_increase=int(walls_height),
        )
    else:
        if breaches_shp:
            # Provided breaches without a catchment is suspicious but not fatal
            raise Warning(
                "A shapefile of breaches was provided but no catchment shapefile was provided."
            )

    output_dem_path = output_dir / "corrected_dem_pre_pysheds.tif"
    with rasterio.open(output_dem_path, "w", **original_dem.profile) as dst:
        dst.write(new_dem, 1)

    # Use pysheds to fix pits/flats and compute flow fields
    pysheds_grid = Grid.from_raster(str(output_dem_path))
    pysheds_dem = pysheds_grid.read_raster(str(output_dem_path))
    pit_filled_dem = pysheds_grid.fill_pits(pysheds_dem)
    flooded_dem = pysheds_grid.fill_depressions(pit_filled_dem)
    inflated_dem = pysheds_grid.resolve_flats(flooded_dem)

    fdir = pysheds_grid.flowdir(inflated_dem, nodata_out=np.int64(0))
    acc = pysheds_grid.accumulation(fdir, nodata_out=np.float64(-9999))

    # Remove temporary walls before final save
    if catchment_shp and boundaries is not None:
        inflated_dem[boundaries] -= walls_height

    output_dem_path = output_dir / "corrected_dem_final.tif"
    with rasterio.open(output_dem_path, "w", **original_dem.profile) as dst:
        dst.write(inflated_dem, 1)

    if outlet_shp:
        outlet = gpd.read_file(outlet_shp)
        x, y = outlet.geometry.x[0], outlet.geometry.y[0]

        # Snap the outlet to a high accumulation cell and compute catchment
        x_snap, y_snap = pysheds_grid.snap_to_mask(acc > 10000, (x, y))
        catchment = pysheds_grid.catchment(x=x_snap, y=y_snap, fdir=fdir)

        output_catchment_path = output_dir / "catchment.tif"
        with rasterio.open(output_catchment_path, "w", **original_dem.profile) as dst:
            dst.write(catchment, 1)

    output_fdir_path = output_dir / "flow_direction.tif"
    with rasterio.open(output_fdir_path, "w", **original_dem.profile) as dst:
        dst.write(fdir, 1)

    output_acc_path = output_dir / "flow_accumulation.tif"
    with rasterio.open(output_acc_path, "w", **original_dem.profile) as dst:
        dst.write(acc, 1)

    original_dem.close()

    print(f"Corrected DEM saved to {output_dem_path}")


def _open_raster_check_crs(raster_path, epsg_code):
    """Open a raster and ensure CRS is defined (or set it).

    Returns a rasterio DatasetReader.
    """
    src = rasterio.open(raster_path)

    if not src.crs:
        if not epsg_code:
            raise ValueError(f"The CRS of the raster {raster_path} is not defined.")
        src.crs = CRS.from_epsg(code=epsg_code)
    elif epsg_code:
        if src.crs.to_epsg() != epsg_code:
            src.crs = CRS.from_epsg(code=epsg_code)

    return src


def _open_vector_check_crs(shapefile_path, epsg_code):
    """Open a vector file and ensure CRS is defined (or set it).

    Returns a GeoDataFrame with the expected CRS.
    """
    gdf = gpd.read_file(shapefile_path)

    if not gdf.crs:
        if not epsg_code:
            raise ValueError(
                f"The CRS of the shapefile {shapefile_path} is not defined.")
        gdf.set_crs(epsg=epsg_code, inplace=True)
    elif epsg_code:
        if gdf.crs.to_epsg() != epsg_code:
            gdf = gdf.to_crs(epsg=epsg_code)

    return gdf


def _prepare_streams(streams_shp, output_dir):
    """Prepare the streams by adding a rank to each stream.

    The function writes `streams.shp` to `output_dir` and returns the
    GeoDataFrame with an added integer `rank` column.
    """
    print("Preparing streams...")

    streams = gpd.read_file(streams_shp)

    # Keep only geometry column
    streams = streams[["geometry"]]

    _, stream_ends = extract_stream_starts_ends(streams, output_dir)

    streams["rank"] = 0
    for _idx, row in stream_ends.iterrows():
        rank = 1
        start_point = row.geometry
        streams_near = list(streams.sindex.nearest(start_point))
        streams_idx = [i for i in streams_near[1] if
                       start_point.touches(streams.geometry[i])]
        streams_connected = streams.loc[streams_idx]

        _iterate_stream_rank(streams, streams_connected, rank)

    streams = streams.sort_values(by="rank", ascending=False)

    return streams


def _iterate_stream_rank(streams, streams_touching, rank):
    """Recursively set a rank for connected stream segments."""
    streams.loc[streams_touching.index, "rank"] = rank
    rank += 1

    for _idx, stream in streams_touching.iterrows():
        start_point = Point(stream.geometry.coords[0])

        streams_near = list(streams.sindex.nearest(start_point))
        streams_idx = [i for i in streams_near[1] if
                       start_point.touches(streams.geometry[i])]
        streams_connected = streams.loc[streams_idx]

        streams_connected = streams_connected[streams_connected["rank"] == 0]

        if not streams_connected.empty:
            _iterate_stream_rank(streams, streams_connected, rank)


def _recondition_dem(original_dem, streams, delta):
    """Correct the DEM based on the stream network.

    This walks ordered cells along each stream and ensures a downslope
    progression by lowering neighbouring cells when needed.
    """
    print("Correcting DEM...")

    resol = original_dem.res[0]
    distances = resol * np.array(
        [
            [math.sqrt(2), 1, math.sqrt(2)],
            [1, 1, 1],  # center cell uses 1 to avoid division by zero
            [math.sqrt(2), 1, math.sqrt(2)],
        ]
    )

    new_dem = original_dem.read(1).copy()

    for line in streams.geometry:
        if not line or not line.is_valid:
            continue

        cell_ids = _get_ordered_cells(line, original_dem.transform, original_dem.shape,
                                      resol / 2)

        for idx in range(len(cell_ids) - 1):
            i, j = cell_ids[idx]
            if i == 0 or j == 0 or i == new_dem.shape[0] - 1 or j == new_dem.shape[
                1] - 1:
                continue

            tile_dem = new_dem[i - 1: i + 2, j - 1: j + 2]

            i_next, j_next = cell_ids[idx + 1]
            row_next, col_next = i_next - i + 1, j_next - j + 1

            slope = (tile_dem - tile_dem[1, 1]) / distances

            if slope[row_next, col_next] > slope.min():
                delta_z = slope.min() * distances[row_next, col_next]
                new_dem[i_next, j_next] = tile_dem[1, 1] + delta_z - delta

            if new_dem[i_next, j_next] >= tile_dem[1, 1]:
                new_dem[i_next, j_next] = tile_dem[1, 1] - delta

    return new_dem


def _build_walls_at_catchment_borders(
        dem,
        catchment_shp,
        breaches_shp,
        streams_shp,
        original_dem,
        elevation_increase=1000,
):
    """Raise DEM along catchment borders (except breaches) to contain flow.

    Returns the modified DEM and a boolean mask identifying boundary cells.
    """
    print("Building walls at catchment borders...")

    catchment = gpd.read_file(catchment_shp)

    catchment_boundary = catchment.geometry.boundary
    boundaries = rasterio.features.geometry_mask(
        [mapping(geom) for geom in catchment_boundary],
        transform=original_dem.transform,
        all_touched=True,
        invert=True,
        out_shape=dem.shape,
    )

    catchment_rasterized = rasterio.features.geometry_mask(
        [mapping(geom) for geom in catchment.geometry],
        transform=original_dem.transform,
        invert=True,
        out_shape=dem.shape,
    )

    rivers = gpd.read_file(streams_shp)

    rivers_rasterized = rasterio.features.geometry_mask(
        [mapping(geom) for geom in rivers.geometry],
        transform=original_dem.transform,
        all_touched=True,
        invert=True,
        out_shape=dem.shape,
    )

    overlap_mask = boundaries & rivers_rasterized
    overlap_indices = np.argwhere(overlap_mask)

    for i_o, j_o in overlap_indices:
        for i in range(i_o - 1, i_o + 2):
            for j in range(j_o - 1, j_o + 2):
                if rivers_rasterized[i, j]:
                    boundaries[i, j] = False
                    continue
                if not catchment_rasterized[i, j] and not boundaries[i, j]:
                    boundaries[i, j] = True

    breaches = gpd.read_file(breaches_shp)
    breaches_rasterized = rasterio.features.geometry_mask(
        [mapping(geom) for geom in breaches.geometry],
        transform=original_dem.transform,
        all_touched=True,
        invert=True,
        out_shape=dem.shape,
    )
    boundaries[breaches_rasterized] = False

    dem[boundaries] += elevation_increase

    return dem, boundaries


def _get_ordered_cells(line, transform, shape, resolution):
    """Return ordered raster cell (row, col) indices overlapped by the line."""
    cell_ids = []

    points = _interpolate_points(line, resolution)

    last_cell = None
    for point in points:
        row, col = rowcol(transform, point.x, point.y)

        if (row, col) == last_cell:
            continue

        if 0 <= row < shape[0] and 0 <= col < shape[1]:
            cell_ids.append((row, col))
            last_cell = (row, col)

    # Ensure the end point cell is included
    row, col = rowcol(transform, line.coords[-1][0], line.coords[-1][1])
    if cell_ids and (row, col) != cell_ids[-1]:
        cell_ids.append((row, col))

    return cell_ids


def _interpolate_points(line, distance):
    """Interpolate points along a LineString at a given distance interval."""
    current_distance = 0.0
    coords = []

    while current_distance <= line.length:
        point = line.interpolate(current_distance)
        coords.append(point)
        current_distance += distance

    return coords


def extract_stream_starts_ends(streams, output_dir, save_to_shapefile=True):
    """Extract stream segment start/end points that are not connected to others.

    Returns two GeoDataFrames: (unconnected_start_gdf, unconnected_end_gdf).
    If `save_to_shapefile` is True the points are written to the `output_dir`.
    """
    print("Finding stream starts/ends...")

    stream_starts_shp = output_dir / "stream_starts.shp"
    stream_ends_shp = output_dir / "stream_ends.shp"

    sindex = streams.sindex

    unconnected_start = []
    unconnected_end = []

    for line in streams.geometry:
        if not line or not line.is_valid:
            continue

        start_point = Point(line.coords[0])
        end_point = Point(line.coords[-1])

        start_neighbors = list(sindex.nearest(start_point))
        end_neighbors = list(sindex.nearest(end_point))

        start_connected = any(
            start_point.touches(streams.geometry[i]) for i in start_neighbors[1] if
            streams.geometry[i] != line
        )
        end_connected = any(
            end_point.touches(streams.geometry[i]) for i in end_neighbors[1] if
            streams.geometry[i] != line
        )

        if not start_connected:
            unconnected_start.append(start_point)
        if not end_connected:
            unconnected_end.append(end_point)

    unconnected_start_gdf = gpd.GeoDataFrame(geometry=unconnected_start)
    unconnected_end_gdf = gpd.GeoDataFrame(geometry=unconnected_end)

    if save_to_shapefile:
        unconnected_start_gdf.to_file(str(stream_starts_shp), crs=streams.crs,
                                      engine="fiona")
        unconnected_end_gdf.to_file(str(stream_ends_shp), crs=streams.crs,
                                    engine="fiona")

    return unconnected_start_gdf, unconnected_end_gdf
