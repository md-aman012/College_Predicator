#!/usr/bin/env python3
"""
Readiness gate for Phase 3: checks data/processed/orcr_clean.(parquet|csv).

    python pipeline\\check_clean.py
    python pipeline\\check_clean.py --years 2019 2020 2021 2022 2023 2024 2025 2026

FAIL = must be fixed before Phase 3.  WARN = look at it, may be fine.  INFO = for your eyes.
Exit code is 1 if anything FAILs.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"

# logical name -> accepted column names (first one found is used)
COLS = {
    "year": ["Year", "year"], "round": ["Round", "round"],
    "institute": ["Institute", "institute"], "key": ["institute_key", "short_name"],
    "state": ["state", "institute_state"], "campus": ["campus"],
    "branch": ["branch_norm"], "degree": ["degree"], "duration": ["duration_years"],
    "quota": ["Quota", "quota"], "category": ["category"], "pwd": ["is_pwd"],
    "female": ["is_female_only"], "prep": ["is_prep_rank", "is_preparatory_rank"],
    "rank_list": ["rank_list"], "final": ["is_final_round"], "exam": ["exam"],
    "open": ["opening_rank_num"], "close": ["closing_rank_num"],
}
CATEGORIES = {"OPEN", "EWS", "OBC-NCL", "SC", "ST"}
QUOTAS = {"AI", "HS", "OS", "GO", "JK", "LA"}

fails, warns = [], []


def fail(msg): fails.append(msg); print(f"  FAIL  {msg}")
def warn(msg): warns.append(msg); print(f"  WARN  {msg}")
def ok(msg): print(f"  ok    {msg}")
def info(msg): print(f"  info  {msg}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="*", type=int, default=list(range(2019, 2027)))
    args = ap.parse_args()

    src = next((p for p in (PROC / "orcr_clean.parquet", PROC / "orcr_clean.csv") if p.exists()), None)
    if src is None:
        sys.exit(f"No cleaned table in {PROC}. Run the cleaning step (pipeline\\clean.py) first.")
    df = pd.read_parquet(src) if src.suffix == ".parquet" else pd.read_csv(src)
    print(f"Loaded {src.name}: {len(df):,} rows x {df.shape[1]} columns\n")

    print("1. Columns")
    c, missing = {}, []
    for name, options in COLS.items():
        hit = next((o for o in options if o in df.columns), None)
        if hit: c[name] = hit
        elif name != "campus": missing.append(f"{name} (one of {options})")
    if missing:
        fail("missing columns: " + "; ".join(missing))
        print("\nCannot continue until the columns exist. Fix clean.py first.")
        return 1
    ok("all required columns present")
    if "campus" not in c:
        df["campus"] = ""; c["campus"] = "campus"
        warn("no campus column: campus programs (e.g. Abu Dhabi) would be merged with the main campus")
    df[c["campus"]] = df[c["campus"]].fillna("")

    print("\n2. Years and final round")
    have = sorted(df[c["year"]].unique())
    gone = [y for y in args.years if y not in have]
    fail(f"missing years: {gone}") if gone else ok(f"years present: {have[0]}-{have[-1]} ({len(have)} years)")
    for y, g in df.groupby(c["year"]):
        top = g[c["round"]].max()
        marked = set(g.loc[g[c["final"]].astype(bool), c["round"]].unique())
        if marked != {top}:
            fail(f"{y}: is_final_round marks rounds {sorted(marked)} but the last round is {top}")
    last = df[df[c["year"]] == max(have)]
    info(f"{max(have)} last round in data = {last[c['round']].max()} (re-scrape later if JoSAA adds rounds)")

    print("\n3. Nulls in key columns")
    keys = ["key", "branch", "degree", "duration", "quota", "category", "pwd", "female", "exam", "close", "open"]
    bad = {k: int(df[c[k]].isna().sum()) for k in keys if df[c[k]].isna().any()}
    fail(f"nulls: {bad}") if bad else ok("no nulls in key columns")

    print("\n4. Allowed values")
    odd = set(df[c["category"]].unique()) - CATEGORIES
    fail(f"unexpected category values: {sorted(odd)}") if odd else ok("categories are OPEN/EWS/OBC-NCL/SC/ST")
    odd = set(df[c["quota"]].unique()) - QUOTAS
    warn(f"unexpected quota codes: {sorted(odd)}") if odd else ok(f"quotas: {sorted(df[c['quota']].unique())}")
    odd = set(df[c["exam"]].unique()) - {"JEE Advanced", "JEE Main"}
    fail(f"unexpected exam values: {sorted(odd)}") if odd else ok("exam is JEE Advanced / JEE Main")

    print("\n5. Home-state data")
    need = df[df[c["quota"]].isin(["HS", "OS", "GO", "JK", "LA"])]
    n = int(need[c["state"]].isna().sum())
    fail(f"{n} HS/OS/GO/JK/LA rows have no institute state") if n else ok("every state-dependent row has an institute state")
    info(f"{need[c['key']].nunique()} institutes have state-dependent quotas")

    print("\n6. Ranks")
    n = int((df[c["open"]] > df[c["close"]]).sum())
    fail(f"{n} rows with opening rank > closing rank") if n else ok("opening <= closing everywhere")
    real = df[~df[c["prep"]].astype(bool)]
    for ex, g in real.groupby(c["exam"]):
        info(f"{ex}: closing rank min {int(g[c['close']].min()):,}, median {int(g[c['close']].median()):,}, max {int(g[c['close']].max()):,}")
    adv_max = real.loc[real[c["exam"]] == "JEE Advanced", c["close"]].max()
    if pd.notna(adv_max) and adv_max > 80000:
        warn(f"JEE Advanced rows reach rank {int(adv_max):,}: some non-IIT institute may be labelled JEE Advanced")
    if "Institute Type" in df.columns:
        bad = df[(df["Institute Type"] == "Indian Institute of Technology") != (df[c["exam"]] == "JEE Advanced")]
        fail(f"{len(bad)} rows where exam disagrees with Institute Type") if len(bad) else ok("exam agrees with Institute Type")
    sci = df[df[c["institute"]].str.contains("Indian Institute of Science", na=False)]
    if len(sci):
        info(f"IISc rows: exam={sorted(sci[c['exam']].unique())}, closing ranks {int(sci[c['close']].min()):,}-{int(sci[c['close']].max()):,} (confirm this is the right rank list)")
    info(f"preparatory-rank rows: {df[c['prep']].astype(bool).mean():.2%}")

    print("\n7. Rank lists")
    vc = df[c["rank_list"]].value_counts(dropna=False)
    info("rank_list values: " + ", ".join(f"{k}: {v:,}" for k, v in vc.items()))
    if df[c["rank_list"]].astype(str).str.contains("VERIFY").any():
        warn("rank_list contains VERIFY rows (B.Des / B.Plan): decide how Phase 3 treats them")

    print("\n8. Duplicate seats (same seat twice in one round)")
    seat = [c[k] for k in ("key", "campus", "branch", "degree", "duration", "quota", "category", "pwd", "female")]
    dup = df.duplicated(subset=[c["year"], c["round"]] + seat, keep=False)
    if dup.any():
        fail(f"{int(dup.sum()):,} rows share a seat key within one Year+Round. Examples:")
        print(df[dup].sort_values([c["year"], c["round"]] + seat)[[c["year"], c["round"], c["institute"], c["branch"], c["quota"], c["category"]]].head(6).to_string(index=False))
    else:
        ok("seat key is unique within each Year+Round")

    print("\n9. History depth (final-round seats of the latest year)")
    fin = df[df[c["final"]].astype(bool)]
    ly = max(have)
    depth = fin.groupby(seat)[c["year"]].nunique()
    latest = fin[fin[c["year"]] == ly].set_index(seat).index.unique()
    d = depth.reindex(latest).fillna(0)
    for k in (1, 2, 3):
        info(f"{ly} seats with >= {k} year(s) of history: {(d >= k).mean():.0%}")
    if (d >= 3).mean() < 0.5:
        warn("fewer than half of the latest seats have 3 years of history: check branch_map / institute names across years")

    print(f"\nSummary: {len(fails)} FAIL, {len(warns)} WARN")
    print("READY for Phase 3." if not fails else "NOT ready: fix the FAIL lines first.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
