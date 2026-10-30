# JoSAA College Predictor

Web app that tells Indian engineering aspirants which JoSAA institutes and branches they can likely get,
from their rank, category, gender and home state.

## Data
- Raw scraped ORCR CSVs are in data/raw (archive 2019-2025 plus the 2026 page). Columns: Year, Round,
  Institute Type, Institute, Academic Program Name, Quota, Seat Type, Gender, Opening Rank, Closing Rank,
  opening_rank_num, closing_rank_num, is_preparatory_rank, exam.
- Reference tables in data/reference: institute_state.csv, branch_map.csv, unique_programs.csv.
- Cleaned table (output of pipeline/clean.py): data/processed/orcr_clean.parquet and orcr_clean.csv.
- The raw and cleaned files are large. Never print or cat them; inspect with pandas (head, nunique, value_counts).

## Rules
@docs/business_rules.md

## Stack and conventions
- Python 3.11+, pandas, scikit-learn, LightGBM, FastAPI, pytest. Frontend: React + Vite + TypeScript + Tailwind.
- The developer uses Windows PowerShell: give PowerShell commands and use backslash paths in commands.
- Write clean, commented, tested code. Say exactly which files you create or change.
- Layout: scraper/, pipeline/, predictor/, api/, web/, tests/, data/, models/, docs/.
- Never store or log a user's rank or personal data.
