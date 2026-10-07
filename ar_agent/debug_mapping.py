import os

import normalize

for f in os.listdir("sample_data"):
    if not f.endswith((".csv", ".xlsx", ".docx", ".txt", ".pdf")):
        continue
    path = os.path.join("sample_data", f)
    try:
        df, warns = normalize.read_records(path)
        print(f"===== {f} ({len(df)} rows) =====")
        for c in df.columns:
            vals = ", ".join(str(v)[:18] for v in df[c].head(6))
            print(f"   {c:<16} -> {vals}")
    except ValueError as e:
        print(f"===== {f} ERROR: {e} =====")
    print()