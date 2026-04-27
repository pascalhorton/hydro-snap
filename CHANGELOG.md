# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog(https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning(https://semver.org/spec/v2.0.0.html).


## 1.0.3 - 2026-04-27

### Fixed

- When no breach or stream intersects a catchment polygon boundary, the automatic
  fallback now opens the full 3×3 neighborhood around the lowest-elevation boundary
  cell instead of a single pixel, ensuring an opening.


## 1.0.2 - 2026-04-23

### Added

- Add `simplification_tolerance` parameter to `recondition_dem` to reduce
  vertex density of stream, breach, and catchment geometries before processing.   
  Improves performance on high-resolution datasets.


## 1.0.1 - 2026-04-23

### Changed

- Enable BigTIFF support for output rasters to handle files larger than 4 GB.
- Enable ZSTD compression for all output rasters to reduce disk usage.


## 1.0.0 - 2026-04-20

### Added

- Add support for stream orientation in DEM reconditioning.
- Automatically identifies and opens the lowest-elevation boundary cell for catchment 
  polygons lacking an intersecting breach or stream to ensure drainage.

### Changed

- Make breach shapefiles optional for catchment-based DEM reconditioning.
- Various code improvements.


## 0.1.5 - 2025-10-28

### Changed

- Updating code style and module configuration.
- Upgrading minimum Python version to 3.10.


## 0.1.4 - 2024-08-29

### Added

- Adding a check of the CRS (Coordinate Reference System) validity of the input data.
- Adding an option to specify the CRS.

### Changed

- Dropping stream network fields in the generated shapefile.
- Reducing the default delta value.

### Fixed

- Fixing the issue with pixels at the edge of the DEM.


## 0.1.3 - 2024-08-23

### Added

- A changelog file.
- Requirements for the package in the setup file.
- Adding a check of the validity of the lines in the stream network shapefile.


## 0.1.2 - 2024-08-20

Linking with zenodo.


## 0.1.1 - 2024-08-20

### Added

- Examples in the readme.


## 0.1.0 - 2024-08-20
First preliminary release.