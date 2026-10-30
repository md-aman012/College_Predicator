#!/usr/bin/env python3
"""
Check that every institute name in the scraped CSVs exists in data/reference/institute_state.csv.

Usage (works from any folder; paths default to the project root = parent of pipeline/):
    python pipeline\\check_institute_state.py
    python pipeline\\check_institute_state.py --raw data\\raw --ref data\\reference\\institute_state.csv

For every name that is NOT in the reference file it prints the years it appears in, how many rows
use it, and the closest existing names (so you can tell a spelling variant from a new institute).
It also writes data/reference/institute_state_missing.csv with a ready-to-fill template.
Exit code is 1 if anything is missing, so it can be used as a pipeline gate.
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

import pandas as pd


def norm(s: str) -> str:
    """Case/spacing/punctuation-insensitive key, so trivial spelling differences still match."""
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


ROOT = Path(__file__).resolve().parents[1]  # project root (this file lives in pipeline/)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--ref", default=str(ROOT / "data" / "reference" / "institute_state.csv"))
    args = ap.parse_args()

    if not Path(args.ref).exists():
        sys.exit(f"Reference file not found: {args.ref}\n"
                 "Copy institute_state.csv into data\\reference\\ in your project and run again.")

    ref = pd.read_csv(args.ref)
    ref_keys = {norm(n): n for n in ref["institute"]}

    files = sorted(Path(args.raw).glob("*.csv"))
    if not files:
        sys.exit(f"No CSV files found in {args.raw}")
    df = pd.concat((pd.read_csv(f, usecols=["Year", "Institute", "Institute Type"]) for f in files),
                   ignore_index=True)

    g = (df.groupby(["Institute", "Institute Type"])
           .agg(rows=("Year", "size"), years=("Year", lambda s: ",".join(map(str, sorted(set(s))))))
           .reset_index())
    g["key"] = g["Institute"].map(norm)

    missing = g[~g["key"].isin(ref_keys)].copy()
    exact_variants = g[g["key"].isin(ref_keys) & ~g["Institute"].isin(ref["institute"])]

    print(f"Institutes in raw data: {g['Institute'].nunique()} | in reference: {len(ref)}")

    if len(exact_variants):
        print(f"\n{len(exact_variants)} name(s) match the reference only after ignoring case/punctuation "
              "(the cleaning step should join on the normalized key):")
        for r in exact_variants.itertuples():
            print(f"  {r.Institute!r}  ->  {ref_keys[r.key]!r}")

    if missing.empty:
        print("\nOK: every institute has a state.")
        return 0

    print(f"\n{len(missing)} institute name(s) have NO state yet:\n")
    ref_names = list(ref_keys.keys())
    rows = []
    for r in missing.sort_values(["Institute Type", "Institute"]).itertuples():
        close = difflib.get_close_matches(r.key, ref_names, n=2, cutoff=0.6)
        print(f"- {r.Institute}\n    type={r._2}  rows={r.rows}  years={r.years}")
        for c in close:
            print(f"    maybe the same as: {ref_keys[c]!r}")
        rows.append({"institute": r.Institute, "state": "", "short_name": "",
                     "institute_type": "", "quotas_seen": "", "confidence": "low",
                     "note": f"years {r.years}; similar to: {'; '.join(ref_keys[c] for c in close)}"})

    out = Path(args.ref).with_name("institute_state_missing.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\nTemplate written to {out}. Fill in state/short_name/institute_type, then append the rows "
          f"to {args.ref}. For a pure spelling variant of an existing institute, copy that institute's row.")
    return 1


if __name__ == "__main__":
    sys.exit(main())