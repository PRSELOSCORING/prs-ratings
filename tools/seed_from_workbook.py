"""
One-time: build data/seed.json (season-starting ratings) from the Excel workbook.

    pip install openpyxl
    python tools/seed_from_workbook.py "Buschman Rating 2026.xlsx" "2025 Finale"

Reads the Ratings sheet's Name column and the given rating column. When a name appears more
than once (usually a copy containing an invisible non-breaking space), the highest rating wins.
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import openpyxl
from names import key

path, column = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "2025 Finale"
rows = list(openpyxl.load_workbook(path, read_only=True, data_only=True)["Ratings"].iter_rows(values_only=True))
c_name, c_rating = rows[0].index("Name"), rows[0].index(column)

seed = {}
for r in rows[1:]:
    name, rating = r[c_name], r[c_rating]
    if name and isinstance(rating, (int, float)):
        k = key(str(name))
        if k not in seed or rating > seed[k]["rating"]:
            seed[k] = {"name": " ".join(str(name).split()), "rating": rating}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "seed.json")
json.dump({"source": f"{os.path.basename(path)} / Ratings / {column}", "shooters": dict(sorted(seed.items()))},
          open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(f"wrote {len(seed)} shooters to {os.path.normpath(out)}")
