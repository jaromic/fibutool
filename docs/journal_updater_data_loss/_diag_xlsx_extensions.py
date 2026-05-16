import sys, zipfile, openpyxl, re

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


try:
    before_file=sys.argv[1]
    after_file=sys.argv[2]
except:
    print(f"usage: {sys.argv[0]} <before_file> <after_file>")

before = extract_extensions(before_file)

# --- simulate what openpyxl does ---

wb = openpyxl.load_workbook(before_file)
wb.save(after_file)

after = extract_extensions(after_file)

# compare
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