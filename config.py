"""Model assumptions for the Germany-Sweden battery storage investment analysis.

Every number reported in the article is produced from these values.
Change a value here and rerun ``run_all.py`` to regenerate all results.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
EC_DIR = RAW_DIR / "energy_charts"        # day-ahead prices (Energy-Charts API JSON)
SVK_DIR = RAW_DIR / "svk_mimer"           # Swedish FCR and aFRR (Svenska kraftnat Mimer CSV)
RL_DIR = RAW_DIR / "regelleistung"        # German FCR and aFRR (regelleistung.net XLSX)
RESULTS_DIR = ROOT / "results"
FIGURES_DIR = ROOT / "figures"

# ---------------------------------------------------------------------------
# Study period and markets
# ---------------------------------------------------------------------------
COUNTRIES = ["DE", "SE"]
BIDDING_ZONE = {"DE": "DE-LU", "SE": "SE3"}
SE_AFRR_AREA = "SN3"                      # Mimer area code for SE3
YEARS = [2020, 2021, 2022, 2023, 2024]    # complete reserve data in both countries
CHECK_YEAR = 2025                         # out-of-sample check (not used in calibration)
BASE_YEARS = [2024]                       # market conditions assumed to persist in the baseline
DESCRIPTIVE_YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
LOCAL_TZ = "Europe/Berlin"                # CET/CEST, identical to Europe/Stockholm

# Reserve products: direction ('sym' = both directions at once, 'up', 'dn') and the
# energy (hours at full commitment) the battery must hold in reserve per MW committed.
PRODUCTS = {
    "DE": {
        "FCR": {"dir": "sym", "hours": 0.25},
        "aFRR_up": {"dir": "up", "hours": 1.0},
        "aFRR_dn": {"dir": "dn", "hours": 1.0},
    },
    "SE": {
        "FCR-N": {"dir": "sym", "hours": 1.0},
        "FCR-D_up": {"dir": "up", "hours": 1 / 3},
        "FCR-D_dn": {"dir": "dn", "hours": 1 / 3},
        "aFRR_up": {"dir": "up", "hours": 1.0},
        "aFRR_dn": {"dir": "dn", "hours": 1.0},
    },
}

# ---------------------------------------------------------------------------
# Battery technology (thesis Table 3.4; both project types have a 2-hour duration)
# ---------------------------------------------------------------------------
DURATION_H = 2.0
ROUND_TRIP_EFFICIENCY = 0.90
ETA = ROUND_TRIP_EFFICIENCY ** 0.5        # charge = discharge efficiency
INITIAL_SOC = 0.5                         # start and end of each day, share of energy capacity
CYCLES_PER_DAY = 1.0                      # max energy discharged per day / energy capacity
DEGRADATION = 0.02                        # annual loss of energy capacity
LIFETIME = 15
MILP_REL_GAP = 1e-6

PROJECTS = {
    # key: (country, type)
    # German grid-scale storage commissioned before 4 August 2029 is exempt from network
    # charges for 20 years (Section 118(6) EnWG), so the baseline grid fee is zero.
    ("DE", "Centralised"): {"mw": 50.0, "capex_kwh": 300.0, "fixed_om_kw": 10.0, "var_om": 2.5, "grid_fee": 0.0},
    ("SE", "Centralised"): {"mw": 50.0, "capex_kwh": 320.0, "fixed_om_kw": 12.0, "var_om": 2.5, "grid_fee": 5.0},
    ("DE", "Decentralised"): {"mw": 5.0, "capex_kwh": 450.0, "fixed_om_kw": 15.0, "var_om": 3.0, "grid_fee": 8.0},
    ("SE", "Decentralised"): {"mw": 5.0, "capex_kwh": 480.0, "fixed_om_kw": 17.0, "var_om": 3.0, "grid_fee": 3.0},
}
# Decentralised portfolios trade through an aggregator and also cut the owners' peak demand.
AGGREGATOR_FEE = 0.20                     # share of market revenue retained by the aggregator
PEAK_SHAVING_EUR_KW = {"DE": 40.0, "SE": 35.0}   # demand-charge saving per kW, thesis Table 4.2
PEAK_SHAVING_SHARE = 0.50                 # share of power available for peak shaving alongside markets

# ---------------------------------------------------------------------------
# Financing (thesis Table 4.1 and Excel model)
# ---------------------------------------------------------------------------
DEBT_SHARE = 0.70
COST_OF_DEBT = {"DE": 0.050, "SE": 0.045}
COST_OF_EQUITY = 0.11
TAX_RATE = {"DE": 0.298, "SE": 0.206}
HURDLE_IRR = 0.08                         # nominal stranding threshold used in the thesis
INFLATION = 0.02                          # annual escalation of revenues and costs (nominal model)
# Euro-area (EA20) HICP, annual average index (Eurostat prc_hicp_aind); deflates each
# historical market year to 2024 euros
HICP = {2019: 104.79, 2020: 105.05, 2021: 107.77, 2022: 116.83, 2023: 123.17, 2024: 126.08, 2025: 128.76}
PRICE_YEAR = 2024
CAPACITY_CHARGE_EUR_KW = 10.0             # Policy shock A: network charge per kW-year (Germany)
CONNECTION_DELAY_YEARS = 2                # Policy shock C: delayed grid connection (Germany)


def wacc(country: str) -> float:
    """Post-tax weighted average cost of capital."""
    return (DEBT_SHARE * COST_OF_DEBT[country] * (1 - TAX_RATE[country])
            + (1 - DEBT_SHARE) * COST_OF_EQUITY)


# ---------------------------------------------------------------------------
# Stress scenarios (thesis Table 3.6). Multipliers apply to reserve capacity prices.
# ---------------------------------------------------------------------------
MAX_MARKET_SHARE = 0.20                   # max share of a product's procured volume per hour
RESERVE_PRICE_GRID = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]
SCENARIOS = {
    "Baseline": {},
    "Market saturation A": {"reserve_decline": 0.30, "decline_years": 3},
    "Market saturation B": {"reserve_decline": 0.60, "decline_years": 5},
    "Policy shock A (DE capacity charge)": {"capacity_charge": True, "country": "DE"},
    "Policy shock C (DE connection delay)": {"delay": True, "country": "DE", "ptype": "Centralised"},
    "Policy shock B (SE reserve redesign)": {"reserve_decline": 0.40, "decline_years": 1, "country": "SE"},
    "Technology displacement": {"reserve_decline": 0.20, "decline_years": 5, "arbitrage_mult": 0.80},
    "Combined stress": {"reserve_decline": 0.60, "decline_years": 5, "capacity_charge": True, "arbitrage_mult": 0.80},
}

# Share of the perfect-foresight optimum that a real operator captures
ARBITRAGE_CAPTURE = 0.85                  # forecast errors on the day-ahead market
RESERVE_REALISATION = 0.75                # bid acceptance, pay-as-bid discounts, availability

# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------
MC_DRAWS = 10_000
MC_SEED = 20261015
CAPEX_TRIANGLE = (0.85, 1.00, 1.20)
ARBITRAGE_CAPTURE_TRIANGLE = (0.70, 0.85, 1.00)
RESERVE_REALISATION_TRIANGLE = (0.40, 0.75, 1.00)
RESERVE_TREND_TRIANGLE = (-0.10, -0.04, 0.00)  # annual drift in reserve revenue
RESERVE_TREND_SATURATION = (-0.30, -0.10, 0.00)  # variant: persistent saturation
