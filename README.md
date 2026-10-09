# Grid Processor Portal

A two-mode web portal for converting commission grid Excel files to structured CSV output — with column mapping, detriff range expansion, RTO code integration, transformations, and a dedicated SK Finance processor.

## Setup

### Requirements
- Python 3.8+
- pip

### Install dependencies
```bash
pip install flask pandas numpy openpyxl pyxlsb werkzeug
```

### Run the server
```bash
python app.py
```

Open **http://localhost:5050** in your browser.

---

## Modes

The portal has two independent processing modes, selectable from the sidebar:

| Mode | Purpose |
|------|---------|
| **Standard Grid** | General commission grid Excel → CSV with detriff expansion and column mapping |
| **SK Finance** | Structured SK Finance Excel sheets → normalized CSV with cell-coordinate config |

---

## Standard Grid — Step by Step

### Step 1 — Upload Files
- **Base Grid File** *(required)*: Commission grid in `.xlsx`, `.xlsb`, `.xls`, or `.csv` — up to 100 MB
- **RTO Cluster File** *(optional)*: Excel with columns `UW Budget Cluster` and `Code` on a sheet named `Data`, `RTOSRWithoutChannel`, `RTO`, or `Sheet1`

### Step 2 — Configure Source
Select a **preset** to auto-fill all settings, or configure manually:

| Field | Description |
|-------|-------------|
| Sheet Name | Sheet to read from the uploaded file |
| Header Row | Row number (1-indexed) containing column headers |
| Start Column | Column number (1-indexed) where data begins |
| Output Name | Base filename for the exported CSV |

Click **Load Preview** to inspect detected columns and confirm detriff detection before proceeding.

#### Available Presets

| Preset | Sheet | Header Row | Start Col |
|--------|-------|-----------|-----------|
| TATA PV | Sheet2 | 2 | 2 |
| TATA CV | Sheet1 | 2 | 2 |
| Banca Motor | Sheet1 | 2 | 2 |
| Hyundai | Sheet1 | 2 | 2 |
| Nissan / Renault | Sheet1 | 2 | 2 |
| OEM Other | Sheet1 | 2 | 2 |

Each preset pre-fills the sheet, header row, start column, target headers, column mapping JSON, and RTO cluster source column.

### Step 3 — Column Mapping
Define two things:

**Target Headers** — one output column name per line. These become the CSV headers.

**Column Mapping JSON** — maps each target column to a source column name or a special marker:

```json
{
  "Version Id*":       "__LITERAL__:my_grid_v1",
  "Biz Mix*":          "LOB",
  "Type Of Business*": "Old/New",
  "Comm Rate*":        "__DETRIFF_VALUE__",
  "Rto Code*":         "__RTO_CODES__",
  "Unique Id":         "__UNIQUE_ID__"
}
```

#### Special Markers

| Marker | Description |
|--------|-------------|
| `__DETRIFF_VALUE__` | Commission % value for the current detriff range row |
| `__DETRIFF_RANGE__` | The detriff range label (e.g. `6-10`) |
| `__RTO_CODES__` | Comma-separated RTO codes from the RTO file for this cluster |
| `__UNIQUE_ID__` | Auto-generated unique ID (`row_N_range`) |
| `__LITERAL__:value` | Hard-codes a fixed string (e.g. `__LITERAL__:TATA PV`) |

Any unmapped column that ends in `LL` / `UL` is auto-filled:
- `detriff` LL/UL → range bounds from the detriff expansion
- `capacity` / `weight` LL/UL → `-10,000,000` / `10,000,000`
- `total gwp` LL/UL → `-10,000,000` / `10,000,000`
- All other unmapped columns → `ANY`

### Step 4 — Transformations *(optional)*
Apply per-column post-processing operations. Each transformation targets one output column and supports chaining multiple ops:

| Operation | Description |
|-----------|-------------|
| `case` | `upper`, `lower`, or `title` case |
| `trim` | Strip surrounding whitespace |
| `strip_chars` | Strip specific characters |
| `replace` | Plain string find-and-replace |
| `regex_replace` | Regex find-and-replace |
| `value_map` | Map specific values to new values via a dictionary |
| `prefix` / `suffix` | Prepend or append a string |
| `default_if_empty` | Fill blank/null cells with a default value |
| `number_format` | Parse as number and round to N decimals |
| `conditional` | Apply changes to one column based on another column's value |

### Step 5 — Process & Export
- Click **Run Grid Processor** to generate the output CSV
- Review the row count, column count, and preview table
- Optionally click **Apply Detriff Merger** to merge rows that are identical except for their detriff range bounds — this compresses output significantly by combining consecutive ranges into a single row
- Download the final CSV

---

## SK Finance — Step by Step

### Step 1 — Upload Files
- **SK Finance File** *(required)*: The structured SK Finance `.xlsx` workbook
- **RTO Cluster File** *(optional)*: Same format as Standard Grid

### Step 2 — Sheet Structure
Configure the cell coordinates that describe the sheet layout:

| Field | Default | Description |
|-------|---------|-------------|
| Sheet Name | `SK Finance` | Sheet to process |
| Agent Code Cell | Row 1, Col 2 | Cell containing the agent code |
| Relationship Code Cell | Row 3, Col 2 | Cell containing the relationship code |
| Payment Basis Row | 9 | Row with `on OD` / `on TP` headers |
| NCB Row | 10 | Row with NCB values |
| CC Row | 11 | Row with cubic capacity values |
| LOB Row | 12 | Row with line-of-business values |
| Data Start Row | 14 | First row of state/commission data |
| State Column | 1 | Column with state names |
| Cluster Column | 2 | Column with UW Budget Cluster values |
| Data Start Column | 3 | First column of commission rate data |
| Valid Payment Basis | `on OD`, `on TP` | Which payment basis columns to include |
| Version ID | *(blank)* | Optional version string written to every row |

Click **Load Sheet Preview** to see a snapshot of the first 15 rows and 14 columns to verify coordinates before processing.

### Step 3 — Output Mapping
Map output columns to source context keys extracted from the sheet:

#### Available Source Keys

| Key | Value |
|-----|-------|
| `__agent_code__` | Agent code from configured cell |
| `__relationship_code__` | Relationship code from configured cell |
| `__state__` | State name from the data row |
| `__cluster__` | UW Budget Cluster from the data row |
| `__rto_codes__` | RTO codes for this cluster (from RTO file) |
| `__comm_rate__` | Commission rate value from the data cell |
| `__cc_ll__` / `__cc_ul__` | Cubic capacity lower/upper limit |
| `__ncb_ll__` / `__ncb_ul__` | NCB percentage lower/upper limit |
| `__banca_outgo__` | Outgo type derived from payment basis (`OD` or `TP`) |
| `__lob__` | Line of business |
| `__payment_basis__` | Raw payment basis value |
| `__ncb__` | Raw NCB value |
| `__cc__` | Raw CC value |
| `__version_id__` | Version ID from sheet structure config |

CC values are parsed automatically: `<1000 CC` → `0–999`, `1000-1500 CC` → `1000–1500`, `>1500 CC` → `1501+`.
NCB values: `All` → `0–101`, `Yes` → `1–101`, `No` → `0–0`.

### Step 4 — Transformations *(optional)*
Same transformation engine as Standard Grid — see above.

### Step 5 — Process & Export
- Click **Run SK Finance Processor** to generate the output CSV
- The results panel shows agent code, relationship code, data column count, and a row preview
- Download the CSV

---

## Quality — Grid Checker & Checker Profiles

After processing and finishing the manual changes, open **Quality → Grid Checker**, upload the final CSV and run.
Every output row is traced to its source cell; generic checks and remark rules (disc caps, capping sentences,
"PTS will be GWP", vehicle age, CC text…) are applied per use case. Profiles are edited under
**Quality → Checker Profiles**. Details: `README_checker.md`.

---

## Detriff Ranges

The processor recognises the following range names as column headers in the source sheet and expands each into a separate output row:

`0`, `0.0`, `0-5`, `1-5`, `6-10`, `11-15`, `16-20`, `21-25`, `26-30`, `31-35`, `36-40`, `41-45`, `46-50`, `51-55`, `56-60`, `61-65`, `66-70`, `71-75`, `76-80`, `81-85`, `86-90`, `91-95`, `96-100`

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/upload` | Upload base grid + optional RTO file. Returns `session_id`, `filepath`, `sheets` |
| `POST` | `/api/preview` | Preview columns from uploaded file given sheet/header/start-col params |
| `POST` | `/api/process` | Run Standard Grid processor. Returns CSV path + preview rows |
| `POST` | `/api/merge_detriff` | Apply detriff merger to a previously processed CSV |
| `GET` | `/api/presets` | Fetch all built-in preset configurations |
| `POST` | `/api/sk_finance/preview` | Snapshot first 15×14 cells of an SK Finance sheet |
| `POST` | `/api/sk_finance/process` | Run SK Finance processor. Returns CSV path + meta |
| `GET` | `/api/sk_finance/default_config` | Fetch default SK Finance config and available source keys |
| `GET` | `/api/download/<filename>` | Download a generated output CSV |

---

## File Structure

```
grid_portal/
├── app.py               # Flask backend — all processing, transformation, and API logic
├── vertical_checker.py  # Grid checker (+ vc_core / vc_checks / vc_reconcile / vc_profiles)
├── checker_profiles/    # One checker profile per use case (JSON)
├── templates/
│   └── index.html       # Full portal UI (both modes, all steps)
├── uploads/             # Temp uploaded files (auto-created)
└── outputs/             # Generated CSV files (auto-created)
```
