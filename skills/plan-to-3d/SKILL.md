---
name: plan-to-3d
description: Turn a 2D architectural plan sheet (DWF/DWFx, the format Autodesk products and Israeli iplan.gov.il permit files publish) into a measured, walkable 3D model of the apartments it draws - real metres, real areas, no invented rooms. Use when someone supplies a DWFx/DWF floor-plan set and wants a 3D simulation, a dollhouse view, a walkthrough, or per-apartment areas pulled straight from the drawing.
---

# Plan to 3D

Reads a plotted plan sheet and rebuilds, in three dimensions, only what the
drawing actually contains: the hatched area zones, the wall network, the
openings, and the spaces those walls enclose.

The one rule the pipeline never breaks: **every surface it emits is traced from
geometry that is on the sheet.** No room is invented to make a plan look tidy
and none is dropped because it was awkward. Areas are reported from the
drawing's own hatch triangles, never from the raster used to build the shell.

## When to use

- A DWF/DWFx plan set (permit sheets, area calculations, `iplan.gov.il`
  downloads, anything published from AutoCAD's ePlot).
- The ask is a 3D apartment simulation, a dollhouse model, a walkthrough, a
  per-floor area schedule, or a clean plan raster pulled out of a busy sheet.

Not for: 3D DWF, IFC/RVT, or raster PDFs. Those carry different data and need
a different reader.

## Pipeline

Three stages, each independently runnable and independently checkable.

```bash
python scripts/dwfx_extract.py  plan.dwfx --out extract/
python scripts/plan_to_model.py extract/  --out model.json
python scripts/build_viewer.py  model.json --out apartments.html
```

### 1. `dwfx_extract.py` - read the package

A DWFx is an OPC/XPS package. The stage unzips it, parses the `FixedPage`
markup into polylines and triangles, reads the `Glyphs` runs as placed text,
and pulls the layer table and named views out of the W2X extension.

It also recovers the drawing scale. A plotted sheet carries its own ruler:
every dimension string states the true length of the line it labels, so the
modal text-to-length ratio gives millimetres per drawing unit. The result is
snapped to the nearest round plot scale using the paper transform in the ePlot
descriptor, which is why the output says `1:100` rather than `1:97.3`.

Pass `--scale` to override when a sheet has no dimensions.

### 2. `plan_to_model.py` - understand the drawing

Per drawing frame (one plan on the sheet):

| step | how |
|---|---|
| colour roles | A colour drawn mostly as polylines is line work; a hatch whose triangles average between 0.2 and 3.5 m² is an area zone (coarser is a site block, finer is a fitting drawn solid). Override with `--zone-colors` / `--line-colors`. |
| frames | Hatch centroids clustered on gaps: each cluster is one plan on the sheet. |
| titles | The largest text under each frame, paired one-to-one with the frames. |
| area zones | Tested again per plan: a colour counts here only if it forms a region of at least `--min-zone` m² on *this* frame, since the same colour can be an area code on one floor and a stick of furniture on another. Each surviving colour becomes its own floor layer with its exact m², summed from the drawing's own triangles. |
| floor plate | Union of the zones, interior holes closed. |
| walls | Three sources unioned: parallel line pairs at wall thickness; thin ribbons the drawn lines leave between them; and the exterior ring implied by the gross-area outline. Junction gaps narrower than a door leaf are bridged; anything that is not connected to the wall network is furniture and is dropped. |
| glazing | Thin parallel pairs sitting *inside* the wall thickness - what separates a window symbol from the wall's own outline. |
| lintels | Doorways are already gaps in the wall network, so closing the network with a door-sized element finds exactly where a lintel belongs. |
| spaces | Free area pinched apart at anything narrower than a door, then grown back, so rooms do not leak into each other through their doorways. Each space records the hatch it sits on, so a balcony that the sheet gives its own area code keeps its own colour. `--outdoor-colors` marks those colours as open to the sky. |

Solids come out as horizontal caps plus only the vertical faces that are
actually exposed - extruding whole boxes would leave coincident faces between
neighbours, which is what makes extruded floor plans shimmer.

Useful flags: `--res` (raster mm/px, default 20), `--height`, `--ext-wall`,
`--door`, `--min-run`, `--min-zone`, `--outdoor-colors`, `--frames 1,4` to build
a subset.

Check the extraction before going 3D:

```bash
python scripts/preview_plan.py model.json --index 1 --out preview.png
```

### 3. `build_viewer.py` - one self-contained HTML file

Three.js from a CDN, the model inline, no build step. Dollhouse / walkthrough /
plan modes, a section-height slider, layer toggles, click a space for its area,
and an area schedule taken from the hatch geometry - each hatch colour listed
with its m² and switchable on its own.

Floors can be coloured three ways: per space, per area code in the drawing's own
hatch colours, or flat. Any space can be marked as a balcony from the readout,
which recolours it and opens the ceiling above it; the choice is remembered per
floor in the browser.

## Reading the result honestly

- Areas in the "שטחים לפי התוכנית" table are exact - they are the drawing's own
  hatch triangles.
- Space areas are measured off the reconstructed walls, so they follow the wall
  network the sheet actually draws. Where a plan is open-plan, or where a
  partition is drawn too faintly to separate from fittings, adjacent rooms will
  read as one space. That is visible in the preview PNG; say so rather than
  quietly splitting them.
- Ceiling height, sill and head are conventions (2.70 / 0.90 / 2.20 m), not
  measurements - a plan does not carry them. Set them with `--height` and edit
  `SILL`/`HEAD` when a section is available.
- Balconies are only separated where the sheet separates them, by giving them
  their own area code and therefore their own hatch colour. On a floor where the
  balcony is hatched together with the rooms, nothing in the file distinguishes
  it, and the viewer's manual balcony marking is the honest way to say so.
- One drawing can serve several storeys ("קומה 2 + 3"). It is listed once,
  under the sheet's own title, because that is all the sheet contains.

## Dependencies

`numpy`, `scipy`, `pillow`. Nothing else; the viewer needs only a browser.
