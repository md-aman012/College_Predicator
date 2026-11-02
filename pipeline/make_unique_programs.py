#!/usr/bin/env python3
"""
Create data/reference/unique_programs.csv: every unique 'Academic Program Name' found in all
CSVs in data/raw, with row counts and the first/last year it appears.

Run from anywhere:
    python pipeline\\make_unique_programs.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]  # project root (this file lives in pipeline/)
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "reference" / "unique_programs.csv"

files = sorted(RAW.glob("*.csv"))
if not files:
    sys.exit(f"No CSV files found in {RAW}")

parts = []
for f in files:
    d = pd.read_csv(f, usecols=["Year", "Institute Type", "Academic Program Name"])
    print(f"{f.name}: {len(d):,} rows, years {sorted(d['Year'].unique())}")
    parts.append(d)
df = pd.concat(parts, ignore_index=True).drop_duplicates()

g = (df.groupby("Academic Program Name")
       .agg(rows=("Year", "size"), first_year=("Year", "min"), last_year=("Year", "max"))
       .reset_index()
       .sort_values("Academic Program Name"))

OUT.parent.mkdir(parents=True, exist_ok=True)
g.to_csv(OUT, index=False, encoding="utf-8")
print(f"\n{len(g)} unique program names written to {OUT}")
