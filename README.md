# Financing the storage transition: battery stranding risk in Germany and Sweden

[![DOI](https://zenodo.org/badge/1421678225.svg)](https://doi.org/10.5281/zenodo.23410601)

Code, processed results and the document register for the article:

> John, K. S. (2026). *Financing the storage transition: Reserve-market saturation, policy risk
> and the stranding of battery investments in Germany and Sweden.* Manuscript submitted for
> publication.

The code reproduces every number, table and figure in the article from public market data.

## What the model does

1. **Market data (2019 to 2025).** Hourly day-ahead prices for DE-LU and SE3 (Energy-Charts),
   German FCR and aFRR capacity prices (regelleistung.net) and Swedish FCR-N, FCR-D and aFRR
   prices (Svenska kraftnät, Mimer), harmonised to EUR per MW per hour.
2. **Daily co-optimisation.** For every day, a mixed-integer linear programme (SciPy / HiGHS)
   chooses hourly day-ahead charging and discharging and the MW offered in each reserve
   product for a 1 MW / 2 MWh battery (90% round-trip efficiency, one cycle per day), with
   power headroom, energy headroom for each product's required duration, block structure, total
   reserve offers per direction capped at the rated power, and each offer capped at 20% of the
   volume procured by the system operator (scaled to project size).
3. **Project finance.** Four projects (centralised 50 MW / 100 MWh and decentralised
   5 MW / 10 MWh, in Germany and Sweden): 15-year nominal cash flows (market revenues in 2024
   euros via the euro-area HICP, 2% inflation), degradation, tax, straight-line depreciation,
   post-tax WACC, NPV, IRR, payback and LCOS. Baseline = 2024 market conditions with capture
   factors of 85% (arbitrage) and 75% (reserves). The German centralised project is exempt from
   network charges.
4. **Stress tests.** Seven scenarios (including a German capacity charge and a two-year grid
   connection delay), base-year sensitivity, break-even reserve-price and reserve-revenue levels
   for an 8% IRR, and sensitivities for the reserve realisation factor and the decentralised
   assumptions. The dispatch is re-solved at 11 reserve-price levels (0% to 100%).
5. **Monte Carlo.** 10,000 draws (seed `20261015`): CAPEX, capture factors, reserve-price
   drift and a year bootstrap of 2020 to 2024 revenues around the 2024 level, plus a
   saturation variant with a stronger downward drift.
6. **Out-of-sample comparison.** The same dispatch on 2025 data, compared with the scenarios
   and the break-even levels.

## How to cite the code

> John, K. S. (2026). *Code and results for: Financing the storage transition* (Version v1.0.0)
> [Software]. Zenodo. https://doi.org/10.5281/zenodo.23410602

The DOI above refers to the version submitted with the article. The badge at the top
(https://doi.org/10.5281/zenodo.23410601) always points to the latest version.

## Quick start

```bash
git clone https://github.com/kayee500/bess-storage-transition.git
cd bess-storage-transition
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python download_day_ahead.py         # day-ahead prices
# download the German and Swedish reserve files as described in data/README.md
python run_all.py                    # uses the cached dispatch results (about 1 minute)
python run_all.py --rebuild          # re-solves every daily optimisation (about 40 minutes)
```

## Repository structure

```
bess-storage-transition/
├── run_all.py                    # runs everything, in order
├── download_day_ahead.py         # Energy-Charts download
├── requirements.txt              # package versions used
├── src/bess_transition/
│   ├── config.py                 # every assumption in one place
│   ├── data_io.py                # load and harmonise the market data
│   ├── dispatch.py               # daily co-optimisation (Eqs. 1 to 4)
│   ├── revenues.py               # annual revenues for all settings (cached)
│   ├── finance.py                # cash flows, NPV, IRR, payback, LCOS (Eqs. 5 to 7)
│   ├── analysis.py               # baseline, scenarios, break-even, Monte Carlo, 2025 comparison
│   └── figures.py                # Figures 1 to 5
├── docs/document_register.csv    # the 20 documents and their theme coding (Appendix B)
├── data/README.md                # how to download the raw data
├── results/                      # CSV and JSON outputs
└── figures/                      # PNG (600 dpi) and PDF figures
```

## Where each article result comes from

| Article item | Output file |
|---|---|
| Table 1 (market data) | `results/descriptives.csv` |
| Table 3, Fig. 1 (revenues by year) | `results/revenue_by_year.csv`, `results/arbitrage_only.csv`, `results/dispatch_2025.csv` |
| Table 4 (baseline) | `results/baseline.csv`, `results/cash_flows_*.csv` |
| Table 5, Fig. 3 (scenarios, break-even) | `results/scenarios.csv`, `results/breakeven.csv` |
| Table 6, Fig. 4 (Monte Carlo) | `results/montecarlo.csv` |
| Table 6 (saturation variant) | `results/montecarlo_saturation.csv` |
| Table 7 (sensitivities) | `results/realisation_sensitivity.csv`, `results/decentralised_sensitivity.csv` |
| Table 8, Fig. 5 (2025 comparison) | `results/out_of_sample.csv`, `results/persisted_2025.csv` |
| Table 9, Appendix B (documents) | `docs/document_register.csv` |
| Table C.1 (base-year sensitivity) | `results/base_year_sensitivity.csv` |
| Fig. 2 (reserve prices) | built directly from the raw data |

## Notes

- All assumptions are in `src/bess_transition/config.py`.
- Revenues are perfect-foresight upper bounds per MW; the capture factors in `config.py`
  convert them into expected revenues in the financial model.
- `results/dispatch_cache.csv` stores the annual results of the 48 five-year dispatch runs
  (4 projects x 11 reserve-price levels, plus 4 arbitrage-only runs), and
  `results/dispatch_2025.csv` the 8 runs for 2025, so that the analysis can be reproduced
  quickly; `--rebuild` recreates both from the raw data.
- Tested with Python 3.13, NumPy 2.5.3, pandas 3.0.5, SciPy 1.18.1, matplotlib 3.11.2 and
  openpyxl 3.1.5.

## Data licences

The raw data are not included. German day-ahead prices are CC BY 4.0 (Bundesnetzagentur |
SMARD.de). Other sources are subject to their providers' terms of use; see `data/README.md`.
The code is released under the MIT licence.

## Contact

Kayode Solomon John, Umeå University, Sweden. ORCID: 0009-0002-6413-8554.
