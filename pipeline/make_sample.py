#!/usr/bin/env python3
"""
Make a small sample of the cleaned table so it can be shared with Claude without the huge file.

    python pipeline\\make_sample.py            # 300 rows
    python pipeline\\make_sample.py --rows 500

Reads data/processed/orcr_clean.parquet (or orcr_clean.csv), writes data/processed/orcr_clean_sample.csv,
spread across years and exams, and prints the columns, dtypes and value counts of the key fields.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

ap = argparse.ArgumentParser()
ap.add_argument("--rows", type=int, default=300)
args = ap.parse_args()

src = next((p for p in (PROC / "orcr_clean.parquet", PROC / "orcr_clean.csv") if p.exists()), None)
if src is None:
    sys.exit(f"No cleaned table found in {PROC}. Finish Phase 2 first (python pipeline\\clean.py).")

df = pd.read_parquet(src) if src.suffix == ".parquet" else pd.read_csv(src)
print(f"Loaded {src.name}: {len(df):,} rows x {df.shape[1]} columns\n")

# stratified sample: roughly equal rows per (Year, exam) group
keys = [c for c in ("Year", "exam") if c in df.columns]
if keys:
    per = max(1, args.rows // df.groupby(keys).ngroups)
    # shuffle, then keep the first `per` rows of each group (keeps every column on all pandas versions)
    sample = df.sample(frac=1, random_state=1).groupby(keys).head(per).sort_values(keys)
else:
    sample = df.sample(min(len(df), args.rows), random_state=1)

out = PROC / "orcr_clean_sample.csv"
sample.to_csv(out, index=False)
print(f"Wrote {len(sample)} rows to {out}\n")

print(df.dtypes.to_string(), "\n")
for c in ("Year", "Round", "exam", "Quota", "category", "is_pwd", "Gender", "is_female_only",
          "Seat Type", "rank_list", "is_final_round"):
    if c in df.columns:
        print(f"--- {c}\n{df[c].value_counts(dropna=False).head(12).to_string()}\n")
