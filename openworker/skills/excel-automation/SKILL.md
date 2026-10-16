---
name: excel-automation
description: Automate Excel operations including reading, writing, formatting, and formula manipulation
---

> **Setup:** If `import estimating_tools` fails, install the bundled wheels: `pip install "$(ls <resources_path>/../_dist/bimforge-*.whl | tail -1)" "$(ls <resources_path>/../_dist/estimating_tools-*.whl | tail -1)[plugin-core]"` — `<resources_path>` is the path `load_skill` returned for this skill. Then retry. (`openworker/install.py` normally does this at install time, so you should only need the fallback on a fresh or relocated Python env.)

# Excel Automation Skill

This skill provides comprehensive Excel automation capabilities using Python's openpyxl library.

## Capabilities

- **Read Excel files** - Extract data from worksheets, cells, ranges
- **Write Excel files** - Create new workbooks, add data, save files
- **Format cells** - Apply fonts, colors, borders, number formats
- **Formulas** - Insert and calculate formulas
- **Charts** - Create basic charts and graphs
- **Data validation** - Add dropdown lists and validation rules

## Prerequisites

The skill requires Python 3.7+ with the following packages:
- `openpyxl` - Excel file manipulation
- `pandas` - Data analysis and manipulation (optional but recommended)

Install the estimating_tools package (includes the excel extra):
```bash
pip install -e 'packages/estimating-tools[excel]'
```

## Usage Instructions

When a user requests Excel automation, follow this process:

### 1. Understand the Request
Clarify:
- What operation is needed (read, write, format, analyze)?
- Which file(s) are involved?
- What specific data or ranges?
- What is the desired output?

### 2. Use the In-Plugin Module

The Excel reader lives in the plugin at module path
`estimating_tools.excel.excel_reader` (public function: `read_excel`).

```bash
# Read data from an Excel file via the module entry point
python -m estimating_tools.excel.excel_reader --file "data.xlsx" --sheet "Sheet1" --range "A1:D10"
```

Or call the Python API directly:
```python
from estimating_tools.excel.excel_reader import read_excel

data = read_excel("data.xlsx", sheet="Sheet1", cell_range="A1:D10")
```

### 3. Execute Operations

Use openpyxl for write/format operations:

```python
import openpyxl

wb = openpyxl.load_workbook('output.xlsx')
ws = wb.active
ws['A1'] = 'Hello'
wb.save('output.xlsx')
```

### 4. Provide Results

- Show the user what was accomplished
- Provide file paths for generated files
- Explain any data transformations
- Suggest next steps if applicable

## Common Patterns

### Pattern 1: Read and Analyze
```python
from estimating_tools.excel.excel_reader import read_excel

# Read data using the in-plugin module
data = read_excel("data.xlsx", sheet="Sheet1")
print(f"Total rows: {len(data)}")
```

### Pattern 2: Create Report
```python
import openpyxl
from openpyxl.styles import Font, Alignment

# Create workbook
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Report"

# Add header
ws['A1'] = "Report Title"
ws['A1'].font = Font(size=14, bold=True)
ws['A1'].alignment = Alignment(horizontal='center')

# Add data
data = [["Name", "Value"], ["Item 1", 100], ["Item 2", 200]]
for row in data:
    ws.append(row)

wb.save('report.xlsx')
```

### Pattern 3: Formulas and Calculations
```python
import openpyxl

wb = openpyxl.load_workbook('budget.xlsx')
ws = wb['Budget']

# Add SUM formula
ws['D10'] = '=SUM(D2:D9)'

# Add formula for each row
for row in range(2, 10):
    ws[f'E{row}'] = f'=C{row}*D{row}'

wb.save('budget.xlsx')
```

### Pattern 4: Named Tables, XLOOKUP, and array formulas

Estimating workbooks live on named Excel **Tables** and `XLOOKUP` into
them (e.g. a takeoff sheet whose Width/Height cells are
`XLOOKUP($D2, tbl[H], tbl[W])` into a standard-plan section table, so the
estimator can flex a design H and watch every quantity reflow). Two traps:

- `openpyxl` writes formula **strings** and does not know function names —
  functions newer than the base file format need the `_xlfn.` prefix or
  Excel shows `#NAME?`: write `'=_xlfn.XLOOKUP(A2, tbl[H], tbl[W])'`,
  not `'=XLOOKUP(...)'`. (Same for `FILTER`, `LET`, `SEQUENCE`, ...)
- Formulas that are array formulas in an existing workbook load back as
  `openpyxl.worksheet.formula.ArrayFormula` objects, not `str` — write
  them back as `ArrayFormula(ref='E2', text='=...')` or the cell silently
  loses its array behavior on save.

```python
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.formula import ArrayFormula

# Named table over a standard-plan section grid (H, W, T columns)
table = Table(displayName="tbl", ref="A1:C20")
table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2",
                                      showRowStripes=True)
ws.add_table(table)

# XLOOKUP into it (note the _xlfn. prefix)
ws["E2"] = '=_xlfn.XLOOKUP($D2, tbl[H], tbl[W])'

# Round-trip an array formula
cell = ws["F2"].value                    # ArrayFormula object, not str
ws["F2"] = ArrayFormula(ref="F2", text=cell.text)
```

## Legacy `.xls` workbooks are DispatchEx-only

openpyxl handles `.xlsx` only — it cannot open a legacy `.xls`, and
converting through another library to round-trip one destroys the legacy
formatting the workbook exists to preserve. The field-proven technique for
editing a legacy `.xls` (e.g. an old estimate template the org still bids
from) is Excel COM automation via win32com:

```python
import win32com.client

excel = win32com.client.DispatchEx("Excel.Application")  # DispatchEx: a
# private Excel instance — never attach to (or clobber) the user's open one
```

- **Copy an existing tab as the format template** (`Worksheet.Copy`), so
  every border/font/column width carries over for free.
- **Clear the copy's contents**, keeping the formatting.
- **Write values by absolute address** (`ws.Range("B7").Value = ...`).
- **Repoint the summary formulas** at the new tab.

Constraint: this works only on Windows with Excel installed (COM drives the
real application). Quit the instance (`excel.Quit()`) in a `finally:` block
or orphaned `EXCEL.EXE` processes accumulate.

## openpyxl never evaluates formulas

openpyxl writes formula **strings**; it never computes them. A freshly
generated `.xlsx` has empty cached values for every formula cell until Excel
or LibreOffice opens the file and recalculates — so `data_only=True` on a
just-written workbook returns `None` for every total, and on a workbook
edited since its last Excel save it returns stale numbers. **Never read
totals out of a workbook you just wrote**, and never report a total you got
by parsing one.

For estimate-spec workbooks, get the number without opening Excel by pricing
the spec in pure Python — `est-estimate summarize <spec.yaml>` — and see the
"Verify before trusting the totals" section of the `build-estimate-workbook`
skill for the full rule.

## Error Handling

Always handle common errors:
- File not found
- Sheet doesn't exist
- Invalid cell reference
- Permission denied (file open in Excel)
- Data type mismatches

## Best Practices

1. **Backup files** before modifying existing workbooks
2. **Validate input** - check file exists, sheet names are correct
3. **Close files properly** - ensure workbooks are saved and closed
4. **Use data_only=True** when reading calculated values
5. **Consider memory** - for large files, use `read_only=True`

## Example Usage

**User Request:** "Read the quarterly sales data from Q4_Sales.xlsx and create a summary report"

**Your Response:**
1. Read the data using `python -m estimating_tools.excel.excel_reader`
2. Analyze the data (calculate totals, averages)
3. Create a new formatted summary report
4. Save as "Q4_Sales_Summary.xlsx"
5. Inform user of completion with file location

## Limitations

- Very large files (>100MB) may be slow
- Complex formatting may not be preserved perfectly
- Charts are basic - complex charts may require manual creation
- Macros (VBA) are not supported
- Legacy `.xls` cannot be opened or written — see the DispatchEx section above
- Formula results are never computed — see the evaluation section above

## Resources

- [openpyxl documentation](https://openpyxl.readthedocs.io/)
- [Excel formula reference](https://support.microsoft.com/en-us/excel)
