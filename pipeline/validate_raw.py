"""Validate JoSAA raw scraped data.

Loads every CSV in ``data/raw/``, concatenates them, recomputes the ``exam``
column from ``Institute Type`` (older scraped CSVs mislabel IITs as JEE
Main), and prints a validation report.

Exits with a non-zero status code if any of the following hard checks fail:

* a year has no rows,
* duplicate rows exist on the natural key, or
* rank columns contain missing values.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Directory containing the scraped CSVs, resolved relative to this file so the
# script works no matter what the current working directory is.
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

# Natural key: a row should be unique within a year/round on these columns.
NATURAL_KEY = [
    "Year",
    "Round",
    "Institute",
    "Academic Program Name",
    "Quota",
    "Seat Type",
    "Gender",
]

# Rank columns that must never be null — they drive model training.
RANK_COLUMNS = ["Opening Rank", "Closing Rank", "opening_rank_num", "closing_rank_num"]


def load_raw_data(raw_dir: Path) -> pd.DataFrame:
    """Load and concatenate every CSV in ``raw_dir``."""
    csv_files = sorted(raw_dir.glob("*.csv"))
    if not csv_files:
        print(f"ERROR: no CSV files found in {raw_dir}", file=sys.stderr)
        sys.exit(1)

    frames = []
    for path in csv_files:
        # Read everything as strings so missing/inconsistent rank values
        # survive as NaN rather than being coerced silently.
        df = pd.read_csv(path, dtype=str, keep_default_na=True)
        df["_source_file"] = path.name
        frames.append(df)

    return pd.concat(frames, ignore_index=True)


def recompute_exam(df: pd.DataFrame) -> pd.DataFrame:
    """Recompute ``exam`` from ``Institute Type``.

    Indian Institutes of Technology use JEE Advanced ranks; every other
    institute uses JEE Main ranks. Older scraped CSVs mislabel IITs as JEE
    Main, so we overwrite ``exam`` deterministically instead of trusting the
    scraped value.
    """
    df = df.copy()

    def _exam_for(institute_type: str) -> str:
        if str(institute_type).strip() == "Indian Institute of Technology":
            return "JEE Advanced"
        return "JEE Main"

    df["exam"] = df["Institute Type"].apply(_exam_for)
    return df


def print_report(df: pd.DataFrame) -> None:
    """Print the full validation report to stdout."""
    print("=" * 70)
    print("JoSAA raw data validation report")
    print("=" * 70)

    # ---- Totals ----
    print(f"\nTotal rows: {len(df):,}")
    print(f"Source files: {df['_source_file'].nunique()}")
    years_present = sorted(df["Year"].dropna().unique())
    print(f"Years present: {years_present}")

    # ---- Row counts per Year x Round x Institute Type ----
    print("\n-- Row counts per Year x Round x Institute Type --")
    counts = (
        df.groupby(["Year", "Round", "Institute Type"])
        .size()
        .reset_index(name="row_count")
        .sort_values(["Year", "Round", "Institute Type"])
    )
    print(counts.to_string(index=False))

    # ---- Null counts per column ----
    print("\n-- Null counts per column --")
    null_counts = df.isna().sum()
    null_counts = null_counts[null_counts > 0].sort_values(ascending=False)
    if null_counts.empty:
        print("No null values in any column.")
    else:
        print(null_counts.to_string())

    # ---- Duplicates on the natural key ----
    print(
        "\n-- Duplicates on (Year, Round, Institute, Academic Program Name, "
        "Quota, Seat Type, Gender) --"
    )
    dup_mask = df.duplicated(subset=NATURAL_KEY, keep=False)
    dup_count = int(dup_mask.sum())
    print(f"Duplicate rows: {dup_count:,}")
    if dup_count:
        print(df.loc[dup_mask, NATURAL_KEY + ["_source_file"]].to_string(index=False))

    # ---- Rows where opening rank exceeds closing rank ----
    print("\n-- Rows where opening_rank_num > closing_rank_num --")
    opening = pd.to_numeric(df["opening_rank_num"], errors="coerce")
    closing = pd.to_numeric(df["closing_rank_num"], errors="coerce")
    inverted = opening > closing
    inv_count = int(inverted.sum())
    print(f"Inverted-rank rows: {inv_count:,}")
    if inv_count:
        print(
            df.loc[
                inverted,
                NATURAL_KEY + ["opening_rank_num", "closing_rank_num", "_source_file"],
            ].to_string(index=False)
        )

    # ---- Share of preparatory (P) ranks per year ----
    print("\n-- Share of preparatory (P) ranks per year --")
    raw_prep = df["is_preparatory_rank"].astype(str).str.strip().str.upper()
    # Non-empty, non-"N" values count as preparatory ranks.
    is_prep = raw_prep.notna() & (raw_prep != "") & (raw_prep != "N")
    prep_share = (
        df.assign(_is_prep=is_prep)
        .groupby("Year")["_is_prep"]
        .agg(["sum", "count"])
    )
    prep_share["share_of_p_ranks"] = prep_share["sum"] / prep_share["count"]
    print(prep_share.to_string())

    # ---- Min and max rank per exam ----
    print("\n-- Min and max rank per exam --")
    df_num = df.assign(
        opening_rank_num=pd.to_numeric(df["opening_rank_num"], errors="coerce"),
        closing_rank_num=pd.to_numeric(df["closing_rank_num"], errors="coerce"),
    )
    rank_summary = (
        df_num.groupby("exam")
        .agg(
            min_opening_rank=("opening_rank_num", "min"),
            max_closing_rank=("closing_rank_num", "max"),
            rows=("opening_rank_num", "size"),
        )
        .sort_index()
    )
    print(rank_summary.to_string())

    # ---- Institutes present in some years but not others ----
    print("\n-- Institutes present in some years but not all --")
    all_years = set(df["Year"].dropna().unique())
    inst_years = df.groupby("Institute")["Year"].apply(set)
    missing_insts = {
        inst: sorted(all_years - years)
        for inst, years in inst_years.items()
        if years != all_years
    }
    if missing_insts:
        for inst, missing in sorted(missing_insts.items()):
            print(f"  {inst}: missing in {missing}")
    else:
        print("Every institute appears in all years.")

    # ---- Programs present in some years but not others ----
    print("\n-- Programs present in some years but not all --")
    prog_years = df.groupby("Academic Program Name")["Year"].apply(set)
    missing_progs = {
        prog: sorted(all_years - years)
        for prog, years in prog_years.items()
        if years != all_years
    }
    if missing_progs:
        for prog, missing in sorted(missing_progs.items()):
            print(f"  {prog}: missing in {missing}")
    else:
        print("Every program appears in all years.")


def validate(df: pd.DataFrame) -> bool:
    """Return True if all hard validation checks pass, False otherwise."""
    ok = True

    # A year with no rows.
    year_counts = df.groupby("Year").size()
    empty_years = [str(y) for y, c in year_counts.items() if c == 0]
    if empty_years:
        print(f"\nERROR: years with no rows: {empty_years}", file=sys.stderr)
        ok = False

    # Duplicates on the natural key.
    dup_count = int(df.duplicated(subset=NATURAL_KEY, keep=False).sum())
    if dup_count:
        print(f"\nERROR: {dup_count} duplicate rows on natural key", file=sys.stderr)
        ok = False

    # Missing rank values.
    existing_rank_cols = [c for c in RANK_COLUMNS if c in df.columns]
    if existing_rank_cols:
        rank_nulls = df[existing_rank_cols].isna().any(axis=1)
        null_count = int(rank_nulls.sum())
        if null_count:
            print(
                f"\nERROR: {null_count} rows with missing rank values",
                file=sys.stderr,
            )
            ok = False

    return ok


def main() -> None:
    df = load_raw_data(RAW_DIR)
    df = recompute_exam(df)

    print_report(df)

    if not validate(df):
        print("\nVALIDATION FAILED", file=sys.stderr)
        sys.exit(1)

    print("\nVALIDATION PASSED")


if __name__ == "__main__":
    main()