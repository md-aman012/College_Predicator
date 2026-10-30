# JoSAA Predictor

Predict JoSAA (Joint Seat Allocation for Engineering) opening/closing ranks for
Indian engineering aspirants.

## Overview

Given a candidate's JEE Main / JEE Advanced rank, category, quota, gender, and
home state, predict which NITs/IIITs/GFTIs/IITs they have a realistic chance of
getting into.

## Folder Structure

```
josaa-predictor/
├── data/
│   ├── raw/            # Scraped CSVs: JoSAA archive (2019-2025) + current 2026 page
│   ├── reference/      # Quota / round / seat-type metadata and static mappings
│   └── processed/      # Cleaned features (parquet), ignored by git
├── scraper/            # JoSAA scrapers (archive page + current 2026 page)
├── pipeline/           # Validation, cleaning, feature engineering
├── predictor/          # Model training (LightGBM) and prediction entry point
├── api/                # FastAPI prediction API
├── web/                # React + Vite + TypeScript + Tailwind frontend
├── tests/              # pytest test suite
├── models/             # Trained model artifacts (.pkl), ignored by git
├── .gitignore
├── README.md
├── requirements.txt
└── tasks.ps1
```

## Tech Stack

- Python 3.11, pandas, scikit-learn, LightGBM
- FastAPI + Uvicorn for the backend API
- React + Vite + TypeScript + Tailwind CSS for the frontend
- pytest for tests

## Getting Started

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install dependencies
python -m pip install -r requirements.txt
```

## Pipeline

| Step | Command | Output |
|------|---------|--------|
| Scrape | `.\tasks.ps1 -Task scrape` | `data/raw/josaa_*.csv` |
| Validate | `.\tasks.ps1 -Task validate` | validated raw CSVs |
| Clean | `.\tasks.ps1 -Task clean` | `data/processed/*.parquet` |
| Train | `.\tasks.ps1 -Task train` | `models/josaa_predictor.pkl` |
| Serve | `.\tasks.ps1 -Task serve` | FastAPI at `http://localhost:8000` |
| Test | `.\tasks.ps1 -Task test` | pytest results |

## Rules of Thumb (applied in cleaning/training)

- IITs use JEE Advanced ranks; all other institutes use JEE Main ranks.
- OPEN seats use CRL rank; EWS/OBC-NCL/SC/ST seats use category ranks; PwD seats use PwD ranks.
- Quotas (AI / HS / OS / GO / JK / LA) depend on the candidate's home state.

## Roadmap

- [ ] Scraper for JoSAA archive page (2019-2025) and 2026 page
- [ ] Data validation: rank ranges, year/round/institute completeness
- [ ] Cleaning: normalize institute/program names, map quotas and seat types
- [ ] Feature engineering + LightGBM training
- [ ] FastAPI prediction endpoint
- [ ] React + Vite frontend
- [ ] End-to-end tests

## License
MIT