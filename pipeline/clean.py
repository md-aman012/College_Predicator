#!/usr/bin/env python3
"""
Clean raw JoSAA ORCR CSVs into a unified processed parquet/csv.

Usage:
    python pipeline\clean.py
    python pipeline\clean.py --raw data\raw --ref data\reference --out data\processed\orcr_clean

Steps:
1. Read all CSVs in data/raw
2. Drop exact duplicate rows (log count)
3. Recompute exam from Institute Type (IIT -> JEE Advanced, else JEE Main)
   - Override: IISc Bangalore uses JEE Advanced (already covered by rule)
4. Join branch_map on Academic Program Name → program_name
   - Columns: branch_norm, degree, duration_years, campus
5. Join institute_state on Institute
   - Columns: state, short_name, institute_type, quotas_seen, confidence, note
6. Add institute_key = short_name (group renamed institutes)
7. Split Seat Type into category and is_pwd
   - Values: OPEN (PwD), OBC-NCL (PwD), SC (PwD), EWS (PwD), ST (PwD)
   - category: part before " (PwD)" if present
   - is_pwd: True if "(PwD)" suffix present
8. Add is_female_only (Gender → 'Female-only' vs 'Gender-Neutral')
9. Parse ranks from Opening/Closing Rank strings
   - Detect P suffix (preparatory rank)
   - Parse numeric part into *_rank_num columns
   - Set is_preparatory_rank = 1 if P suffix detected
10. Add rank_list column
    - Use rank_list_hint from branch_map if available and not empty
    - Else use exam value
    - Architecture programs (is_barch=True) use "JEE Main Paper 2" rank list
11. Add is_final_round (True for max Round within each Year)
12. Build seat key: (institute_key, campus, branch_norm, degree, duration_years,
    quota, category, is_pwd, is_female_only)
13. Remove invalid rows (opening_rank_num > closing_rank_num) and log count
14. Fail loudly on any unmapped institute or branch
15. Write to parquet and csv in data/processed/

Tests for: P-rank parser, final-round logic, institute_key grouping, seat-key uniqueness.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

def parse_p_rank(rank_str) -> Tuple[int, int]:
    """Parse a rank string that may have a 'P' suffix (preparatory rank).

    Args:
        rank_str: Rank string (e.g., "50P", "50", or possibly NaN)

    Returns:
        Tuple[int, int]: (numeric_value, is_preparatory_rank)
        - numeric_value: Parsed integer part
        - is_preparatory_rank: 1 if 'P' suffix detected, else 0
    """
    if pd.isna(rank_str):
        return None, 0

    s = str(rank_str).strip()
    if not s:
        return None, 0

    # Check if ends with 'P' (case-insensitive)
    is_p = s.upper().endswith('P')
    # Extract numeric part
    num_part = s[:-1] if is_p else s

    try:
        return int(num_part), 1 if is_p else 0
    except ValueError:
        logger.warning(f"Could not parse rank string: {rank_str}")
        return None, 0

def split_seat_type(seat_type: str) -> Tuple[str, bool]:
    """Split Seat Type into category and is_pwd.

    Args:
        seat_type: Seat Type value (e.g., "OPEN", "OPEN (PwD)", "OBC-NCL")

    Returns:
        Tuple[str, bool]: (category, is_pwd)
        - category: Part before " (PwD)" if present
        - is_pwd: True if "(PwD)" suffix present
    """
    if pd.isna(seat_type):
        return None, False

    s = str(seat_type).strip()
    if not s:
        return None, False

    # Check if it ends with "(PwD)"
    is_pwd = s.upper().endswith('(PWD)')
    if is_pwd:
        category = s[:-5].strip()
    else:
        category = s

    return category, is_pwd

def derive_exam_from_institute_type(institute_type: str, institute: str) -> str:
    """Recompute exam column from Institute Type.

    Args:
        institute_type: Institute Type value (e.g., "Indian Institute of Technology")
        institute: Institute name (for IISc special handling)

    Returns:
        str: "JEE Advanced" for IITs, "JEE Main" for everything else
        - Override: IISc Bangalore uses JEE Advanced (already covered by IIT rule)
    """
    if pd.isna(institute_type):
        return "JEE Main"

    s = str(institute_type).strip()
    if not s:
        return "JEE Main"

    # IIT and IISc Bangalore are JEE Advanced
    # Note: The task mentions IISc Bangalore as an override, but
    # in the raw data IISc appears as "Indian Institute of Technology"
    # with exam "JEE Advanced", so the general rule already covers it
    if "Indian Institute of Technology" in s:
        return "JEE Advanced"

    return "JEE Main"

def derive_rank_list(rank_list_hint: str, exam: str, is_barch: bool) -> str:
    """Derive rank_list from rank_list_hint, exam, or is_barch.

    Args:
        rank_list_hint: Value from branch_map rank_list_hint column (may be None)
        exam: JEE Main or JEE Advanced
        is_barch: Whether this is an architecture program

    Returns:
        str: "JEE Main Paper 2" for architecture programs,
             rank_list_hint if available and not empty,
             otherwise exam value
    """
    # Architecture programs (B.Arch, B.Plan, B.Design, etc.) use JEE Main Paper 2
    if is_barch:
        return "JEE Main Paper 2"

    # Use rank_list_hint if provided and not empty
    if pd.notna(rank_list_hint) and str(rank_list_hint).strip():
        return str(rank_list_hint).strip()

    # Otherwise use exam value
    return exam

def main():
    parser = argparse.ArgumentParser(
        description="Clean JoSAA ORCR raw CSVs into unified processed format"
    )
    parser.add_argument(
        "--raw",
        default=str(ROOT / "data" / "raw"),
        help="Path to raw CSVs directory"
    )
    parser.add_argument(
        "--ref",
        default=str(ROOT / "data" / "reference"),
        help="Path to reference CSVs directory"
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "processed"),
        help="Path to output directory"
    )
    args = parser.parse_args()

    raw_dir = Path(args.raw)
    ref_dir = Path(args.ref)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Read all CSVs in data/raw
    logger.info(f"Reading all CSVs from {raw_dir}")
    csv_files = list(raw_dir.glob("*.csv"))
    if not csv_files:
        logger.error(f"No CSV files found in {raw_dir}")
        sys.exit(1)

    raw_dfs = []
    for f in csv_files:
        df = pd.read_csv(f)
        # Ensure required columns exist
        required = ["Year", "Round", "Institute Type", "Institute",
                   "Academic Program Name", "Quota", "Seat Type", "Gender",
                   "Opening Rank", "Closing Rank", "opening_rank_num",
                   "closing_rank_num", "is_preparatory_rank", "exam"]
        missing = [col for col in required if col not in df.columns]
        if missing:
            logger.error(f"File {f} missing columns: {missing}")
            sys.exit(1)
        raw_dfs.append(df)

    raw = pd.concat(raw_dfs, ignore_index=True)
    logger.info(f"Total raw rows: {len(raw):,}")

    # 2. Drop exact duplicate rows and log count
    before_dedup = len(raw)
    raw = raw.drop_duplicates()
    duplicates_dropped = before_dedup - len(raw)
    logger.info(f"Dropped {duplicates_dropped:,} exact duplicate rows")

    # 3. Recompute exam from Institute Type
    logger.info("Recomputing exam column from Institute Type")
    raw['exam_recomputed'] = raw.apply(
        lambda row: derive_exam_from_institute_type(row['Institute Type'], row['Institute']),
        axis=1
    )

    # 4. Join branch_map on Academic Program Name
    logger.info("Joining branch_map on Academic Program Name")
    branch_map = pd.read_csv(ref_dir / "branch_map.csv")
    # Rename program_name to branch_program_name for clarity
    branch_map = branch_map.rename(columns={"program_name": "branch_program_name"})

    # Merge to identify unmatched programs
    merged_check = raw.merge(
        branch_map[['branch_program_name', 'branch_norm', 'degree', 'duration_years', 'campus', 'is_barch']],
        how='left',
        left_on='Academic Program Name',
        right_on='branch_program_name'
    )

    unmatched = merged_check['branch_norm'].isna()
    if unmatched.any():
        logger.error(f"Failed to map {unmatched.sum():,} rows of Academic Program Name")
        logger.error("Unmatched program names:")
        for prog in merged_check.loc[unmatched, 'Academic Program Name'].unique()[:10]:
            logger.error(f"  - {prog}")
        sys.exit(1)

    raw = merged_check

    # 5. Join institute_state on Institute
    logger.info("Joining institute_state on Institute")
    institute_state = pd.read_csv(ref_dir / "institute_state.csv")

    merged_check = raw.merge(
        institute_state[['institute', 'state', 'short_name', 'institute_type', 'quotas_seen', 'confidence', 'note']],
        how='left',
        left_on='Institute',
        right_on='institute'
    )

    unmatched_institute = merged_check['state'].isna()
    if unmatched_institute.any():
        logger.error(f"Failed to map {unmatched_institute.sum():,} rows of Institute")
        logger.error("Unmatched institute names:")
        for inst in merged_check.loc[unmatched_institute, 'Institute'].unique()[:10]:
            logger.error(f"  - {inst}")
        sys.exit(1)

    raw = merged_check

    # 6. Add institute_key = short_name
    logger.info("Adding institute_key column")
    raw['institute_key'] = raw['short_name']

    # 7. Split Seat Type into category and is_pwd
    logger.info("Splitting Seat Type into category and is_pwd")
    seat_split = raw['Seat Type'].apply(lambda x: split_seat_type(x))
    raw['category'] = seat_split.apply(lambda x: x[0])
    raw['is_pwd'] = seat_split.apply(lambda x: x[1])

    # 8. Add is_female_only from Gender
    logger.info("Adding is_female_only column")
    gender_mapping = {
        'Female-only (including Supernumerary)': True,
        'Gender-Neutral': False
    }
    raw['is_female_only'] = raw['Gender'].map(gender_mapping)

    # 9. Parse ranks from Opening/Closing Rank strings and set is_preparatory_rank
    logger.info("Parsing ranks from Opening/Closing Rank strings")
    # Parse Opening Rank
    open_parsed = raw['Opening Rank'].apply(lambda x: parse_p_rank(x))
    raw['opening_rank_num_parsed'] = open_parsed.apply(lambda x: x[0])
    raw['is_preparatory_rank_opening'] = open_parsed.apply(lambda x: x[1])

    # Parse Closing Rank
    close_parsed = raw['Closing Rank'].apply(lambda x: parse_p_rank(x))
    raw['closing_rank_num_parsed'] = close_parsed.apply(lambda x: x[0])
    raw['is_preparatory_rank_closing'] = close_parsed.apply(lambda x: x[1])

    # Set final is_preparatory_rank column (max of opening and closing)
    raw['is_preparatory_rank'] = raw[['is_preparatory_rank_opening', 'is_preparatory_rank_closing']].max(axis=1)

    # Update *_rank_num columns with parsed values
    raw['opening_rank_num'] = raw['opening_rank_num_parsed']
    raw['closing_rank_num'] = raw['closing_rank_num_parsed']

    # 10. Add rank_list column
    logger.info("Adding rank_list column")

    # Check if branch_map has rank_list_hint column
    if 'rank_list_hint' in branch_map.columns:
        # Merge rank_list_hint into raw
        rank_hint = raw.merge(
            branch_map[['branch_program_name', 'rank_list_hint']],
            how='left',
            left_on='Academic Program Name',
            right_on='branch_program_name'
        )

        raw['rank_list'] = rank_hint.apply(
            lambda row: derive_rank_list(row['rank_list_hint'], row['exam_recomputed'], row['is_barch']),
            axis=1
        )
    else:
        # rank_list_hint not available, use derived logic based on is_barch
        raw['rank_list'] = raw.apply(
            lambda row: derive_rank_list(None, row['exam_recomputed'], row['is_barch']),
            axis=1
        )

    # 11. Add is_final_round
    logger.info("Adding is_final_round column")
    # Find max round for each year
    max_rounds = raw.groupby('Year')['Round'].max().reset_index()
    max_rounds.rename(columns={'Round': 'max_Round'}, inplace=True)
    raw = raw.merge(max_rounds, on='Year', how='left')
    raw['is_final_round'] = raw['Round'] == raw['max_Round']
    raw.drop(columns=['max_Round'], inplace=True)

    # 12. Build seat key
    logger.info("Building seat key column")
    seat_key_cols = ['institute_key', 'campus', 'branch_norm', 'degree',
                     'duration_years', 'Quota', 'category', 'is_pwd', 'is_female_only']
    raw['seat_key'] = raw[seat_key_cols].apply(lambda row: tuple(row), axis=1)

    # 13. Remove invalid rows (opening > closing) and log count
    logger.info("Removing invalid rows where opening_rank_num > closing_rank_num")
    invalid_before = len(raw)
    # Only remove if both ranks are numeric (not None/NaN)
    valid_ranks = raw['opening_rank_num'].notna() & raw['closing_rank_num'].notna()
    raw = raw[valid_ranks & (raw['opening_rank_num'] <= raw['closing_rank_num'])]
    invalid_dropped = invalid_before - len(raw)
    logger.info(f"Dropped {invalid_dropped:,} invalid rows (opening > closing)")

    # 14. Final checks
    logger.info("Checking for any remaining null values in critical columns")
    critical_cols = ['state', 'short_name', 'branch_norm', 'category',
                     'is_female_only', 'is_preparatory_rank', 'is_final_round']
    null_counts = raw[critical_cols].isna().sum()
    if null_counts.any():
        logger.warning("Some rows have null values in critical columns:")
        for col, count in null_counts.items():
            if count > 0:
                logger.warning(f"  {col}: {count:,}")

    # 15. Write output
    logger.info(f"Writing output to {out_dir}")
    output_name = "orcr_clean"

    # Drop helper columns
    cols_to_keep = [
        'Year', 'Round', 'Institute Type', 'Institute', 'state', 'short_name',
        'institute_key', 'Academic Program Name', 'branch_norm', 'branch_program_name',
        'degree', 'duration_years', 'campus', 'Quota', 'Seat Type', 'category',
        'is_pwd', 'Gender', 'is_female_only', 'Opening Rank', 'Closing Rank',
        'opening_rank_num', 'closing_rank_num', 'is_preparatory_rank', 'exam',
        'exam_recomputed', 'rank_list', 'is_final_round', 'seat_key'
    ]

    # Include rank_list_hint if it exists in branch_map
    if 'rank_list_hint' in branch_map.columns:
        cols_to_keep.append('rank_list_hint')

    # Only keep columns that actually exist
    cols_to_keep = [col for col in cols_to_keep if col in raw.columns]

    final_df = raw[cols_to_keep].copy()

    # Write parquet and csv
    parquet_path = out_dir / f"{output_name}.parquet"
    csv_path = out_dir / f"{output_name}.csv"

    final_df.to_parquet(parquet_path, index=False)
    final_df.to_csv(csv_path, index=False)

    logger.info(f"Successfully written {len(final_df):,} rows to:")
    logger.info(f"  Parquet: {parquet_path}")
    logger.info(f"  CSV: {csv_path}")

    # Log some statistics
    logger.info("\nStatistics:")
    logger.info(f"  Years: {sorted(raw['Year'].unique())}")
    logger.info(f"  Institutes: {raw['institute_key'].nunique()}")
    logger.info(f"  Programs: {raw['branch_norm'].nunique()}")
    logger.info(f"  Unique seat keys: {raw['seat_key'].nunique()}")
    logger.info(f"  Exam counts: {raw['exam'].value_counts().to_dict()}")
    logger.info(f"  Rank list values: {raw['rank_list'].value_counts().to_dict()}")

if __name__ == "__main__":
    main()