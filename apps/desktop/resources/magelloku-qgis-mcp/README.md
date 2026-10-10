# Bundled QGIS MCP plugin

`magelloku_mcp-1.0.15.zip` is the installable Magelloku MCP plugin package built
from the source in this folder. The desktop installer copies the same plugin
source into the active QGIS profile. On first run,
Magelloku detects the user's QGIS profile and copies the plugin into
`<QGIS profile>/python/plugins/magelloku_mcp` if it is not installed yet.

The plugin is not started silently. After installation, the user opens QGIS
and clicks **Plugins → QGIS MCP → Start Server**. The desktop then probes the
local socket at `127.0.0.1:9876`.

Version 1.0.15 makes CSV header handling explicit: `inspect_csv` requires
`has_header`. For headerless survey data, use `has_header=false` and optionally
`column_names` in the supplied column order. The first record is counted as data.
`get_project_info` and `save_project` report `is_dirty` so callers can verify
that changes after opening/updating 3D were saved before isolated export.
The matching desktop harness can recover an unsaved-project capture precondition
through the ordinary save/approval flow; transport failures are not replayed.
Update the desktop, API and plugin together for the UJI 9 harness fixes.

Version 1.0.14 adds `inspect_csv` (one selected file, streaming statistics),
`prepare_structure_lines` (selection-preserving LineZ recovery to a verified
permanent GPKG), and `inspect_structure_lines` (membership/geometry/Z preflight).
Degenerate lines require an explicit exclusion option and each exclusion is
reported. Preparation never silently changes the input selection or skips an
invalid feature. Writer verification closes its private OGR handle before atomic
rename, including on Windows. Runtime validation now respects comprehension
scope when field and feature variables share a name.

Isolated 3D export fits a local perspective DEM bounding box to the requested
aspect ratio and orientation with a margin when no distance is specified.
Elevation scale/offset and the scene's world origin are respected. Set
`fit_to_extent=false` to preserve the live camera, or provide an explicit
`distance` to use the chosen export camera. Unsupported terrain/projection types
keep the existing camera and report `fit_to_extent=false`; the live view is never
resized or moved. Returned receipts distinguish preview from an explicit saved
`path`. Extra 3D objects outside the terrain extent still require visual review.

Version 1.0.13 adds free layout composition controls: paper/orientation, explicit
map and legend layers, label geometry/typography, and update/remove item tools.
`get_layout_info` and previews include text, layers, CRS, scale, shader ranges,
legend contents, overflow errors and overlap/readability warnings. Intentional
overlays are reviewed visually rather than automatically rejected. Continuous
raster legends can use `add_layout_color_ramp`, an embedded SVG generated from
the actual shader values/colors, without changing the project renderer or names.
NaN default legends are refused. Source style changes invalidate embedded ramps.
These are components, not a prescribed ROM/mining page template. The desktop
agent reviews each changed layout/page against the user's request; a 3D/canvas
image cannot satisfy a print-page review. Layouts containing live 3D map items
must use the isolated scene export as a picture, not a second main-process engine.

Version 1.0.12 adds `capture_3d_view`; `get_3d_screenshot` uses the same new path.
It exports the current scene with the official `QgsLayoutItem3DMap` renderer
in a separate QGIS Python process. No foreground window, screen pixels or live
window resizing is required. `width`/`height` set PNG pixels (default 1500×1000);
`pitch`, `heading` and `distance` affect only the export camera. Lighting, terrain
and layer settings come from the current view. Save the project and persist
memory source layers first: an isolated renderer cannot use in-memory live data.
The worker has a deadline and checks PNG size/content. Its failure cannot invoke
Qt3D teardown in the main process, and `path` is replaced atomically only after
validation. Rendering still depends on the installed QGIS/OpenGL runtime.

Read-only PyQGIS preflight includes a conservative `needs_project_checkpoint`
hint. Known inspection scripts do not snapshot the project, but still go through
workspace validation and script review. Unknown or mutating calls retain the
snapshot. Explicit `import qgis.utils` overrides the legacy injected enum alias.

`calculate_raster_volume` reads a DEM without Processing or project changes.
It reports positive volume above the base, positive volume below the base and
their signed difference separately, using the GDAL mask and actual affine pixel
area. XY units must be meters; Z units are explicitly assumed to be meters.
`set_category_visibility` changes categorized symbology without changing the
provider subset or interpolation input. Existing filters are reported, never
silently cleared. Close live 3D views before changing symbology.

For a manual `execute_code` capture, direct `pixmap = screen.grabWindow(...)`
followed by `pixmap.save(path)` can return verified image metadata when the
window is an existing visible 3D canvas and saved PNG pixels equal the pixmap.
This lets the desktop display/check the actual 3D image and clear an earlier
capture-failure status. Unrecognized script shapes retain the ordinary script
result; they do not fabricate capture success.

The plugin also protects the live 3D scene during Processing and layer changes.
Use `close_3d_view` with the title returned by `create_3d_view` before replacing
terrain sources. Finish Processing, loading, styling and saving before reopening
3D. The plugin drains deferred widget deletion before reporting a closed view.
Script preflight rejects additional offscreen 3D renderers and known access to
project-owned layer objects after removal. The export worker alone owns the
additional 3D layout engine; it never shares native objects with live QGIS.
