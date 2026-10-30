#!/usr/bin/env python3
"""
Append data/reference/institute_state_additions.csv to data/reference/institute_state.csv.

institute_type and quotas_seen are filled from the raw CSVs in data/raw (the Institute Type that
the name actually has in the data, and the set of quota codes seen), so nothing is guessed.
Names already present in institute_state.csv are skipped. Run from anywhere:

    python pipeline\\append_institute_states.py
    python pipeline\\check_institute_state.py      # should now print OK
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "data" / "reference" / "institute_state.csv"
ADD = ROOT / "data" / "reference" / "institute_state_additions.csv"
RAW = ROOT / "data" / "raw"

TYPE = {"Indian Institute of Technology": "IIT", "National Institute of Technology": "NIT",
        "Indian Institute of Information Technology": "IIIT",
        "Government Funded Technical Institutions": "GFTI"}

for p in (REF, ADD):
    if not p.exists():
        sys.exit(f"Missing file: {p}")
files = sorted(RAW.glob("*.csv"))
if not files:
    sys.exit(f"No CSV files in {RAW}")

ref = pd.read_csv(REF)
add = pd.read_csv(ADD, dtype=str).fillna("")

raw = pd.concat((pd.read_csv(f, usecols=["Institute", "Institute Type", "Quota"]) for f in files),
                ignore_index=True).drop_duplicates()
itype = raw.groupby("Institute")["Institute Type"].agg(lambda s: s.mode().iat[0]).to_dict()
quotas = raw.groupby("Institute")["Quota"].agg(lambda s: "|".join(sorted(set(s)))).to_dict()

new_rows, skipped, problems = [], [], []
for r in add.to_dict("records"):
    name = r["institute"]
    if name in set(ref["institute"]):
        skipped.append(name)
        continue
    if name not in itype:
        problems.append(f"not found in raw data (check the spelling, it must match exactly): {name}")
        continue
    t = itype[name]
    r["institute_type"] = TYPE.get(t, t)
    if t not in TYPE:
        problems.append(f"unknown Institute Type {t!r} for {name}")
    r["quotas_seen"] = quotas[name]
    new_rows.append(r)

if problems:
    print("PROBLEMS:")
    for p in problems:
        print("  -", p)

if new_rows:
    out = pd.concat([ref, pd.DataFrame(new_rows)], ignore_index=True)
    out = out.sort_values(["institute_type", "state", "institute"]).reset_index(drop=True)
    out.to_csv(REF, index=False, encoding="utf-8")
    print(f"\nAppended {len(new_rows)} rows. institute_state.csv now has {len(out)} rows.")
    print(pd.DataFrame(new_rows)[["short_name", "state", "institute_type", "quotas_seen", "confidence"]]
          .to_string(index=False))
if skipped:
    print(f"\nSkipped {len(skipped)} already present.")
print("\nNext: python pipeline\\check_institute_state.py")
