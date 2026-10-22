# From a plan to a checked takeoff

Build an IFC model from a plan DXF with `est-bim`, check its dimensions by hand
in Blender with the Bonsai add-on, then turn it into a takeoff spreadsheet —
from the command line, or by asking an agent.

Every command and number below comes from a clean run of `estimating-tools`
and `bimforge` 0.1.94 from PyPI. The menu names come from Bonsai 0.8.5. The
files that run produced can be downloaded from
<https://www.anvilrockroad.com/guides/model-to-takeoff/>, or you can produce
them yourself with the commands below.

## 1. Install

`estimating-tools` brings `bimforge` with it, and the `[excel]` extra adds
`openpyxl`, which the audit workbook needs. Python 3.10 or later.

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS / Linux: source .venv/bin/activate
pip install "estimating-tools[excel]"
est-bim --help
```

For the checking step, install Blender, then Bonsai from
*Edit › Preferences › Get Extensions*.

## 2. The plan

The sample plan is a small DXF with five layers: a slab, an L-shaped wall, a
curb, a floor finish and four columns. `--with-configs` also writes the two
YAML files that drive the rest of the pipeline.

```bash
est-bim sample --with-configs
cp layer_map.example.yaml layer_map.yaml        # Windows: copy
cp takeoff_map.example.yaml takeoff_map.yaml
```

Edit `layer_map.yaml` for each project. Each DXF layer gets an IFC class, a
feature type, and the sizes the plan doesn't show:

- Closed outlines become `area` elements, given a thickness.
- Open polylines become `linear` elements, given a height and a width.
- Block inserts become `count` elements.

The takeoff groups elements by their classification code.

```yaml
units:
  dxf_length_unit: "mm"     # the DXF is drawn in millimetres; the IFC is in metres

layers:
  A-WALL:                   # the DXF layer name
    ifc_class: "IfcWall"
    feature: "linear"       # area | linear | count
    height: 3.0             # metres
    width: 0.2
    classification: { system: "Uniclass 2015", code: "EF_25_10", name: "Walls" }
```

## 3. The model

```bash
est-bim dxf2bim --dxf sample_plan.dxf --config layer_map.yaml --out sample.ifc
est-bim validate sample.ifc
```

```text
Extracted 8 features across 5 layers.
8 elements written to sample.ifc

CLASS                    COUNT
IfcBuildingElementProxy      1
IfcColumn                    4
IfcCovering                  1
IfcSlab                      1
IfcWall                      1
TOTAL                        8
schema issues: 0
```

`dxf2bim` writes each element's base quantities (length, width, height, area
and volume) into the IFC as quantity sets. If the element count comes up
short, either a DXF layer is missing from the layer map, or a layer holds the
wrong kind of geometry for its feature type.

## 4. The takeoff

`takeoff_map.yaml` sets three things for each classification code: which
quantity to sum, the pay unit, and the bid item it belongs to.

```yaml
codes:
  "EF_25_10":               # the classification code from layer_map.yaml
    measure: GrossVolume    # which quantity to sum
    unit: CY                # the pay unit, converted from SI
    item_number: "0020"     # the bid item it rolls up to
    schedule: "A"
```

```bash
est-bim takeoff --ifc sample.ifc --map takeoff_map.yaml --out takeoff.json --csv takeoff.csv
```

```text
Item   Cost code    Description                         Qty Unit  Sched
------------------------------------------------------------------------
0010   03 30 00     Cast-in-Place Concrete            15.70 CY    A
0050   05 12 00     Structural Steel Framing           4.00 EA    A
0030   32 16 13     Curbs and Gutters                 32.81 LF    A
0020   EF_25_10     Walls                             12.56 CY    A
0040   EF_25_30     Floor finishes                    64.58 SF    A
```

The wall's 12.56 CY is its 16.0 m centreline × 3.0 m × 0.2 m = 9.6 m³,
converted to cubic yards. `takeoff.json` records the elements behind each row
by IFC GlobalId, so every quantity can be traced back to the objects it came
from.

## 5. Check in Blender

1. **Open the model.** Choose *File › Open IFC Project* and pick
   `sample.ifc`.
2. **Read in feet.** In *Scene Properties › Units*, set the unit system to
   Imperial and length to Feet. This changes only what Blender displays; the
   IFC stays in metres.
3. **See what the takeoff used.** Select an element and open
   *Object Properties › Quantity Sets*. These are the values the takeoff
   summed. For the wall they are `Length 16`, `Height 3` and `Width 0.2`.
4. **Measure.** With the cursor over the 3D viewport, press <kbd>Shift</kbd>
   <kbd>M</kbd> for Bonsai's Measure Tool.
   - Its tool settings switch between Single, Polyline, Polyline Area and
     Face Area.
   - It snaps to vertices and edges, and the status bar walks you through
     each pick.
5. **Cross-check a volume.** Open *Scene Properties › Quantity Take-off ›
   Simple Quantity Calculator*.
   - It has Calculate Object Volumes, Face Areas and Edge Lengths, computed
     from the mesh of whatever is selected.
   - Volumes come back in cubic metres. The slab reads 12, which matches the
     takeoff's 15.70 CY.

Measure these, in feet:

| Element      | Measure            | Tool                 | Expect             |
| ------------ | ------------------ | -------------------- | ------------------ |
| Slab         | Length × width     | Single               | 32.81 × 19.69 ft   |
| Slab         | Thickness          | Single, vertical edge| 0.66 ft            |
| Slab         | Top area           | Face Area            | 645.83 SF          |
| Wall         | Height × thickness | Single               | 9.84 × 0.66 ft     |
| Wall         | Length             | Polyline, both faces | 52.49 ft, averaged |
| Curb         | Length             | Single               | 32.81 ft           |
| Floor finish | Top area           | Face Area            | 64.58 SF           |
| Columns      | Count, height      | Count by eye, Single | 4, 9.84 ft         |

> **Where a hand check goes wrong.** Measured along its outside face, the wall
> totals 33.14 + 20.01 = 53.15 ft. Along its inside face it totals 32.48 +
> 19.36 = 51.84 ft. Neither matches the takeoff's 52.49 ft, because a wall's
> length is measured on its centreline, the average of the two faces. Corners
> are where most linear quantities drift, so measure both faces and average
> them.

The audit in step 6 repeats the volume check automatically: it meshes every
element and compares the result with the element's quantity set. It can't
tell you whether the model matches the structure on the drawings. That's the
check worth doing by hand: compare a few of these dimensions with the
dimension strings on the sheets, not with the model.

Close Blender without saving. The check only reads the model, and saving an
edit would change the quantities the takeoff reads.

## 6. The spreadsheet

### The CSV

Step 4 already wrote `takeoff.csv`, one row per bid item. It opens in Excel or
can be pasted into an estimate.

### The audit workbook

```bash
est-takeoff audit --takeoff takeoff.json --ifc sample.ifc
```

```text
takeoff.audit.xlsx: 5 item(s), 8 element(s), 0 exception(s) — legs: IFC, MESH
  mesh leg: 8 meshed, 0 qto-only, 0 unclassified — 0 item(s) at GEOM VARIANCE (tol ±0.5%)
```

`takeoff.audit.xlsx` re-reads the IFC independently of the takeoff and
reconciles the two. It has four sheets:

| Sheet      | Contents |
| ---------- | -------- |
| Summary    | Each bid item's takeoff quantity beside the IFC's and the measured mesh, with a status |
| Elements   | Every element behind every item |
| Geometry   | Each element's mesh volume, plan area and extents in feet |
| Exceptions | Anything outside tolerance |

With `--strict`, the audit exits non-zero when there are exceptions, so it can
gate a push.

### Ask an agent

In Claude Code, the `dxf-to-bim`, `bim-to-takeoff` and `audit-quantities`
skills run steps 2 to 6 for you. If you want the sheet in your own layout,
describe it:

```text
Read takeoff.json and sample.ifc and build takeoff.xlsx with two sheets.

Takeoff: one row per bid item — item, cost code, description, quantity,
unit, schedule, element count.

Check: one row per dimension I can measure by hand in Blender — every
element's length, width and height in feet, and the top area in square
feet for slabs and finishes. Use the wall's centreline length from its
quantity set, not its bounding box. Fill in the model's value, leave a
highlighted "Your Blender reading" column empty, and add the difference,
the percentage, and a status that says CHECK when it is off by more than 1%.

Keep the script you write next to the workbook so it can be re-run.
```

The agent writes a short `openpyxl` script that reads the IFC and the takeoff.
The resulting workbook has two sheets:

- **Takeoff:** the bid items.
- **Check:** eighteen dimensions you can measure, each with the model's value
  filled in and a yellow column for your reading. When you type in your
  Blender readings, each row turns OK or CHECK.

If you ask the agent to keep the script, it can rebuild the same sheet when
the model changes.

## 7. Your drawings

1. **Layers.** Rename the keys in `layer_map.yaml` to your CAD standard's
   layer names, and give each one the IFC class it really is.
2. **Units and location.** Set `dxf_length_unit` to the unit the DXF is drawn
   in. Set `crs_epsg` to its coordinate system, or null to skip
   georeferencing.
3. **Codes.** Use your own cost codes as the classification codes, and point
   each one at its bid item in `takeoff_map.yaml`. One code can pay several
   items, such as piling furnished by the foot and driven each, from the same
   elements.
4. **Check, then trust.** Before relying on the rollup, measure a handful of
   elements in Blender and compare them with the drawings. Do it again
   whenever the layer map changes.

Structures that aren't plain extrusions, such as retaining walls, piles and
headwalls, are built from a spec with `est-bim build` instead.
