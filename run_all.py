"""Reproduce every number, table and figure in the article.

    python run_all.py            # uses results/dispatch_cache.csv if present
    python run_all.py --rebuild  # re-solves all daily optimisations (about 40 minutes)
"""

import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
warnings.filterwarnings("ignore", category=UserWarning)

import numpy as np
import pandas as pd

from bess_transition import analysis, config, data_io, figures, revenues


def market_volumes() -> pd.DataFrame:
    """Average procured reserve volumes in 2025 (MW), as quoted in Sections 2.1 and 5.1."""
    rows = []
    rl = config.RL_DIR
    fcr = pd.read_excel(rl / "RESULT_OVERVIEW_CAPACITY_MARKET_FCR_2025-01-01_2025-12-31.xlsx")
    rows.append(("DE", "FCR demand (Germany)", pd.to_numeric(fcr["GERMANY_DEMAND_[MW]"], errors="coerce").mean(), "2025"))
    afrr = pd.read_excel(rl / "RESULT_OVERVIEW_CAPACITY_MARKET_aFRR_2025-01-01_2025-12-31.xlsx")
    afrr["v"] = pd.to_numeric(afrr["GERMANY_ALLOCATED_VOLUME_[MW]"], errors="coerce")
    afrr = afrr.dropna(subset=["v"])
    period = f"{pd.Timestamp(afrr.DATE_FROM.min()).date()} to {pd.Timestamp(afrr.DATE_FROM.max()).date()}"
    for d, lab in (("POS", "up"), ("NEG", "down")):
        rows.append(("DE", f"aFRR allocated volume {lab}", afrr[afrr.PRODUCT.str.startswith(d)].v.mean(), period))
    se = pd.read_csv(config.SVK_DIR / "FCR_prices_2025.csv", sep=";", dtype=str)
    se = se[se.iloc[:, 0].str.match(r"\d{4}-")]
    num = lambda c: pd.to_numeric(se[c].str.replace(",", ".", regex=False), errors="coerce")
    for tot, dk, lab in (("Total", "DK2 FCRN", "FCR-N"), ("Total FCRD upp", "DK2 FCRD upp", "FCR-D up"),
                         ("Total FCRD ned", "DK2 FCRD ned", "FCR-D down")):
        rows.append(("SE+DK2", f"{lab} procured volume", num(tot).mean(), "2025"))
        rows.append(("SE", f"{lab} procured volume, Swedish zones", (num(tot) - num(dk)).mean(), "2025"))
    return pd.DataFrame(rows, columns=["area", "item", "mean_mw", "period"]).round(1)


def main(rebuild: bool = False):
    config.RESULTS_DIR.mkdir(exist_ok=True)
    out = {}

    print("1/7 Data checks")
    descs = []
    for c in config.COUNTRIES:
        df = data_io.hourly_table(c, config.DESCRIPTIVE_YEARS[1:])
        cov = data_io.coverage(df, c)
        cov.to_csv(config.RESULTS_DIR / f"coverage_{c}.csv")
        y = df.time_local.dt.year
        spread = df.groupby("day")["da"].agg(lambda s: s.max() - s.min())
        desc = pd.concat([df.groupby(y)["da"].agg(["mean", "std"]),
                          spread.groupby(pd.to_datetime(spread.index).year).mean().rename("daily_spread"),
                          df.groupby(y)["da"].apply(lambda s: (s < 0).sum()).rename("neg_hours"),
                          # reserve prices averaged over all hours, zero where nothing was procured
                          df.groupby(y)[list(config.PRODUCTS[c])].apply(
                              lambda g: g.fillna(0).mean().where(g.notna().any(), np.nan))], axis=1)
        desc.insert(0, "country", c)
        descs.append(desc)
        da = data_io.load_day_ahead(c, config.DESCRIPTIVE_YEARS)
        out[f"day_ahead_{c}"] = da.groupby(da.time_local.dt.year)["da"].agg(["count", "mean", "std", "min", "max"]) \
            .round(2).reset_index().to_dict("records")

    pd.concat(descs).round(2).to_csv(config.RESULTS_DIR / "descriptives.csv")

    print("2/7 Daily dispatch (cached unless --rebuild)")
    cache_path = config.RESULTS_DIR / "dispatch_cache.csv"
    cache = revenues.build_cache() if rebuild or not cache_path.exists() else revenues.load_cache()
    check_path = config.RESULTS_DIR / f"dispatch_{config.CHECK_YEAR}.csv"
    check = revenues.build_check() if rebuild or not check_path.exists() else pd.read_csv(check_path)

    print("3/7 Revenues and baseline")
    analysis.revenue_by_year(cache).to_csv(config.RESULTS_DIR / "revenue_by_year.csv", index=False)
    analysis.arbitrage_only(cache).to_csv(config.RESULTS_DIR / "arbitrage_only.csv", index=False)
    base = analysis.baseline(cache)
    base.to_csv(config.RESULTS_DIR / "baseline.csv", index=False)
    for key, cf in analysis.baseline_cash_flows(cache).items():
        cf.to_csv(config.RESULTS_DIR / f"cash_flows_{key[0]}_{key[1]}.csv", index=False)

    print("4/7 Scenarios, base-year sensitivity, break-even")
    scen = analysis.scenarios(cache)
    scen.to_csv(config.RESULTS_DIR / "scenarios.csv", index=False)
    analysis.base_year_sensitivity(cache).to_csv(config.RESULTS_DIR / "base_year_sensitivity.csv", index=False)
    be = analysis.breakeven_reserve_mult(cache)
    be.to_csv(config.RESULTS_DIR / "breakeven.csv", index=False)

    print("5/7 Monte Carlo")
    mc, draws = analysis.monte_carlo(cache)
    mc.to_csv(config.RESULTS_DIR / "montecarlo.csv", index=False)
    mc_sat, _ = analysis.monte_carlo(cache, trend=config.RESERVE_TREND_SATURATION)
    mc_sat.to_csv(config.RESULTS_DIR / "montecarlo_saturation.csv", index=False)
    analysis.decentralised_sensitivity(cache).to_csv(config.RESULTS_DIR / "decentralised_sensitivity.csv", index=False)
    analysis.realisation_sensitivity(cache).to_csv(config.RESULTS_DIR / "realisation_sensitivity.csv", index=False)

    print("6/7 Out-of-sample check (2025)")
    oos = analysis.out_of_sample(cache, check)
    oos.to_csv(config.RESULTS_DIR / "out_of_sample.csv", index=False)
    analysis.persisted_2025(check).to_csv(config.RESULTS_DIR / "persisted_2025.csv", index=False)

    print("   Market volumes quoted in the text (2025)")
    market_volumes().to_csv(config.RESULTS_DIR / "market_volumes_2025.csv", index=False)

    out["wacc"] = {c: config.wacc(c) for c in config.COUNTRIES}
    (config.RESULTS_DIR / "summary.json").write_text(json.dumps(out, indent=2, default=str))

    print("7/7 Figures")
    figures.fig1_revenue_history(cache, check)
    figures.fig2_reserve_prices()
    figures.fig3_scenarios(scen)
    figures.fig4_montecarlo(draws)
    figures.fig5_thresholds(be, oos)
    print("Done. Results in results/, figures in figures/.")


if __name__ == "__main__":
    main(rebuild="--rebuild" in sys.argv)
