# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`hydro-snap` is a Python package for DEM (Digital Elevation Model) reconditioning — it aligns DEMs with mapped stream networks to ensure accurate hydrological flow paths while minimizing terrain alteration.

## Commands

```bash
# Install in development mode
pip install -e .

# Run tests
pytest tests/

# Run a single test
pytest tests/test_hydro_snap.py::test_name

# Format code
black .
isort .

# Build package
python -m build
```

Code style: Black with line-length 88, isort with profile "black" (configured in `pyproject.toml`).

## Architecture

The package has a single public API function (`recondition_dem`) and a single implementation module:

```
hydro_snap/
├── __init__.py       # exports recondition_dem
└── hydro_snap.py     # all implementation (~500 lines)
```

**Public API:** `recondition_dem(dem_path, streams_path, output_dir, ...)` — takes a DEM raster and stream network shapefile, outputs 7 files: corrected DEM, flow direction, flow accumulation, catchment delineation, ranked streams, and stream start/end points.

**Data flow:**
1. Load and CRS-validate DEM (rasterio) + streams (geopandas/fiona)
2. `_prepare_streams()` — adds hierarchical rank to stream segments
3. `_recondition_dem()` — walks stream lines in rank order, enforces monotonically decreasing elevation along each stream
4. `_build_walls_at_catchment_borders()` — optionally adds elevation barriers at catchment boundaries
5. pysheds `Grid` — pit-filling, flat resolution, flow direction/accumulation computation

**Key dependencies:** `rasterio`, `geopandas`, `fiona`, `shapely`, `numpy`, `pysheds`, `affine`

**CRS handling:** All inputs must share the same CRS — both `_open_raster_check_crs()` and `_open_vector_check_crs()` validate against the reference CRS and raise errors on mismatch.

**Stream ranking:** Streams are processed from highest rank (main stems) down to tributaries so that main channels take priority during DEM correction.
