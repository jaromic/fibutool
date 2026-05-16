# openpyxl Extension Loss — Investigation Notes

## Background

openpyxl emits these warnings when reading `.xlsx` files that contain Excel 2010+ extensions it does not support:

```
UserWarning: Unknown extension is not supported and will be removed
UserWarning: Conditional Formatting extension is not supported and will be removed
```

The extensions are silently dropped on write. This document records what was found and whether it matters for this project.

---

## Diagnostic Script

Excel files are ZIP archives of XML. The script below extracts all `ext` element URIs before and after an openpyxl round-trip and diffs them.

```python
import zipfile, re
import openpyxl

def extract_extensions(xlsx_path):
    """Return dict of {filename: [uri, ...]} for all ext elements in the xlsx."""
    exts = {}
    with zipfile.ZipFile(xlsx_path) as z:
        for name in z.namelist():
            if not name.endswith('.xml'):
                continue
            content = z.read(name).decode('utf-8', errors='replace')
            uris = re.findall(r'<ext\b[^>]*uri="([^"]+)"', content)
            if uris:
                exts[name] = uris
    return exts

before = extract_extensions("your_file.xlsx")

wb = openpyxl.load_workbook("your_file.xlsx")
wb.save("your_file_after.xlsx")

after = extract_extensions("your_file_after.xlsx")

all_files = set(before) | set(after)
for f in sorted(all_files):
    b = set(before.get(f, []))
    a = set(after.get(f, []))
    lost = b - a
    gained = a - b
    if lost:
        print(f"LOST   in {f}: {lost}")
    if gained:
        print(f"GAINED in {f}: {gained}")
if not any((set(before.get(f, [])) - set(after.get(f, []))) for f in all_files):
    print("No extensions lost.")
```

---

## Findings on the Journal File

Running the script against the project's journal Excel file produced:

```
LOST in xl/pivotCache/pivotCacheDefinition1.xml: {'{725AE2AE-9491-48be-B2B4-4EB974FC3084}'}
LOST in xl/pivotTables/pivotTable1.xml: {'{962EF5D1-5CA2-4c93-8EF4-DBF5C05439D2}', '{747A6164-185A-40DC-8AA5-F01512510D54}'}
LOST in xl/styles.xml: {'{EB79DEF2-80B8-43e5-95BD-54CBDDF9020C}', '{9260A510-F301-46a8-8635-F512D64BE5F5}'}
LOST in xl/workbook.xml: {'{B58B0392-4F1F-4190-BB64-5DF3571DCE5F}'}
LOST in xl/worksheets/sheet{4,8,11,15,19,20,21,22}.xml: {'{B025F937-C7B1-47D3-B67F-A62EFF666E3E}', '{78C0D931-6437-407d-A8EE-F0AAD7539E65}'}
```

---

## URI Reference Table

| URI | Feature | Impact |
|-----|---------|--------|
| `{78C0D931-6437-407d-A8EE-F0AAD7539E65}` | Sparklines (x14) | Tiny inline charts disappear completely |
| `{B025F937-C7B1-47D3-B67F-A62EFF666E3E}` | Enhanced Conditional Formatting (x14) | Basic CF survives; enhanced variants (solid data bars, v2 icon sets) degrade |
| `{EB79DEF2-80B8-43e5-95BD-54CBDDF9020C}` | Slicer styles (x14) | Slicer appearance reverts to default |
| `{9260A510-F301-46a8-8635-F512D64BE5F5}` | Timeline styles (x15) | Timeline slicer appearance reverts to default |
| `{B58B0392-4F1F-4190-BB64-5DF3571DCE5F}` | Workbook-level slicer/timeline registration | Slicers may stop functioning |
| `{725AE2AE-9491-48be-B2B4-4EB974FC3084}` | Pivot cache extensions (x14) | Enhanced pivot cache features lost |
| `{962EF5D1-5CA2-4c93-8EF4-DBF5C05439D2}` | Pivot table extensions (x14) | Enhanced pivot interactivity lost |
| `{747A6164-185A-40DC-8AA5-F01512510D54}` | Pivot table extensions (x14) | Enhanced pivot interactivity lost |

**Note:** Regular column dropdown filters (AutoFilter) are standard OOXML — not extensions — and are fully preserved by openpyxl. Slicers are a separate, more visual filter panel attached to Tables or Pivot Tables; they are distinct from ordinary column filters.

---

## Verdict

None of the lost extensions are used in this project:

- **Sparklines** — not used
- **Slicers / Timelines** — not used (user unfamiliar with the feature)
- **Pivot tables** — not intentionally present; the pivot XML may be a template artefact
- **Enhanced CF** — basic conditional formatting is preserved and visually verified as correct

**The warnings are safe to ignore.** No functional or visible data loss occurs for this project's journal file.

---

## Related

- Memory entry: `project_openpyxl_extlst.md` — tracks this as a known open issue
- openpyxl issue tracker: the x14 extLst limitation is a long-standing known gap with no fix planned
