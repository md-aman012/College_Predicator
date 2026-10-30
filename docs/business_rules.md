# JoSAA business rules (single source of truth for the predictor)

Everything below must be confirmed against the current JoSAA information bulletin before launch.
Anything marked **VERIFY** is not yet confirmed from an official source.

## 1. Which rank list applies
- **IIT seats** use **JEE Advanced** ranks. **NIT, IIIT and GFTI seats** use **JEE Main** ranks.
  In the data this is the `exam` column, derived from `Institute Type`
  (`Indian Institute of Technology` -> JEE Advanced, everything else -> JEE Main).
- **B.Arch / B.Planning programs** use the JEE Main **Paper 2** rank, a different list from the Paper 1
  rank used for B.Tech. Keep them separate (`rank_list` column). VERIFY the exact program types affected.

## 2. Which rank to compare for a given seat (the `Seat Type` column)
| Seat is | Candidate rank to compare |
|---|---|
| OPEN | Common rank list (CRL) |
| EWS, OBC-NCL, SC, ST | The candidate's rank within that category |
| Any of the above marked PwD | The candidate's PwD rank (within that category list) |

- **Reserved candidates also compete for OPEN seats** using their CRL. A reserved-category user must see
  both the OPEN (CRL) results and the results for their own category.
- VERIFY: whether PwD candidates may also be allotted non-PwD seats of their category (so the app should
  also show those seats to PwD users).
- Check the exact `Seat Type` strings with `value_counts()` before writing the parser.

## 3. Quota and home state (the `Quota` column)
| Quota | Candidate is eligible when |
|---|---|
| AI | Always (all-India) |
| HS | Candidate home state == institute state |
| OS | Candidate home state != institute state |
| GO | Candidate home state is Goa |
| JK | Candidate home state is Jammu and Kashmir |
| LA | Candidate home state is Ladakh |

- The institute state comes from `data/reference/institute_state.csv`. Use the state names exactly as
  written there (for example `Jammu and Kashmir`).
- The home-state dropdown in the app must include **Ladakh** (no institute is located there, but NIT Srinagar
  has an LA quota).
- In the 2025 data only 41 of 128 institutes have HS/OS seats (all NITs plus 9 GFTIs). The other 87 are AI only,
  so state matters for relatively few institutes.
- Quota combinations seen in 2025: NIT Goa has GO + HS + OS; NIT Srinagar has JK + LA + OS (no HS).
  VERIFY how GO differs from HS at NIT Goa and how HS/JK/LA work at NIT Srinagar.
- Rows flagged `confidence = medium` in `institute_state.csv` need a manual check of how HS is defined.

## 4. Gender
- **Female-only** seats are for women only. Women may also take **gender-neutral** seats.
- Men see only gender-neutral seats.
- Check the exact `Gender` strings with `value_counts()`; derive `is_female_only` from them.

## 5. Ranks and rounds
- A rank with suffix **P** comes from the preparatory rank list. Parse it into `*_rank_num`, set
  `is_preparatory_rank = 1`, and keep it out of normal comparisons for real-rank users.
- **Final round:** the last round of each year is the real closing rank. Compute it as the maximum
  `Round` within each `Year`. Never hard-code round 6.
- Drop (and log) rows where `opening_rank_num > closing_rank_num`.

## 6. Presenting predictions
- Chance labels (Safe / Likely / Borderline / Reach) are estimates from past data, not guarantees and
  not official JoSAA advice. The band thresholds live in one config dict and are tuned from the Phase 4
  calibration check.
- Never store or log a user's rank or personal data.
