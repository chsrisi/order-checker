# Warehouse floor layout

Sources for the warehouse floor map (`docs/WAREHOUSE_MAP_SPEC.md`, decisions in
`docs/V2_STOCK_DELTA.md`).

| File | What it is |
|---|---|
| `Layout.xlsx` | The owner's floor plan: one sheet per floor (*Lantai 1–4*). The source of truth. |
| `layout_to_json.py` | Converts `Layout.xlsx` into `warehouse-layout.json` (schema v1). |
| `warehouse-layout.json` | The generated layout, committed as a test fixture. |

**Update:** edit `Layout.xlsx`, then from this directory:

```bash
uv run --with openpyxl python layout_to_json.py Layout.xlsx warehouse-layout.json
```

Commit both files. `openpyxl` is not a backend dependency (V2_STOCK_DELTA S7).

**Serving:** the backend serves the layout from a read-only `data/warehouse/` volume, not from this
directory (S4). Room assignments that override the location rule live there in `room-bins.json`,
so re-running the converter never overwrites them.

**Status:** the script still writes sample bins (`DEFAULT_BINS`) into the layout. T6.25 changes
that: the script writes `bins: []`, the samples move to a fixture, and the location rule
(`exact` or `prefix`) is added to the layout (V2_STOCK_DELTA R1.3).
