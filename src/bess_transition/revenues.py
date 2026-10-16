"""Annual market revenues per MW for every project, scenario setting and year.

Results are cached in results/dispatch_cache.csv because the full grid of
re-optimisations (reserve-price multipliers x grid-fee settings) takes several minutes.
"""

import pandas as pd

from . import config, data_io, dispatch


def variable_cost(country: str, ptype: str, grid_fee_mult: float = 1.0) -> float:
    p = config.PROJECTS[(country, ptype)]
    return p["var_om"] + p["grid_fee"] * grid_fee_mult


def settings():
    """All (country, ptype, grid_fee_mult, reserve_mult) combinations that are needed."""
    out = []
    for (country, ptype) in config.PROJECTS:
        for fm in [1.0]:
            for m in config.RESERVE_PRICE_GRID:
                out.append((country, ptype, fm, m))
    return out


def annual(daily: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in daily.columns if c not in ("day", "year")]
    return daily.groupby("year")[cols].sum()


def build_cache(path=None, verbose=True) -> pd.DataFrame:
    path = path or config.RESULTS_DIR / "dispatch_cache.csv"
    tables = {c: data_io.hourly_table(c) for c in config.COUNTRIES}
    rows = []
    for (country, ptype, fm, m) in settings():
        vc = variable_cost(country, ptype, fm)
        daily = dispatch.run(tables[country], country, vc, reserve_mult=m, mw=config.PROJECTS[(country, ptype)]["mw"])
        a = annual(daily).reset_index()
        a.insert(0, "reserve_mult", m)
        a.insert(0, "grid_fee_mult", fm)
        a.insert(0, "ptype", ptype)
        a.insert(0, "country", country)
        rows.append(a)
        if verbose:
            print(f"  {country} {ptype:<13} fee x{fm:.0f} reserves x{m:.1f}: "
                  f"{a['arbitrage'].mean() + a['reserves'].mean():,.0f} EUR/MW/yr", flush=True)
    # arbitrage-only reference (no reserve participation)
    for (country, ptype) in config.PROJECTS:
        daily = dispatch.run(tables[country], country, variable_cost(country, ptype), with_reserves=False,
                             mw=config.PROJECTS[(country, ptype)]["mw"])
        a = annual(daily).reset_index()
        a.insert(0, "reserve_mult", -1.0)          # -1 marks the arbitrage-only reference
        a.insert(0, "grid_fee_mult", 1.0)
        a.insert(0, "ptype", ptype)
        a.insert(0, "country", country)
        rows.append(a)
    cache = pd.concat(rows, ignore_index=True).fillna(0.0)
    cache.to_csv(path, index=False)
    return cache


def load_cache(path=None) -> pd.DataFrame:
    path = path or config.RESULTS_DIR / "dispatch_cache.csv"
    return pd.read_csv(path)


def lookup(cache, country, ptype, grid_fee_mult=1.0, reserve_mult=1.0) -> pd.DataFrame:
    q = cache[(cache.country == country) & (cache.ptype == ptype)
              & (cache.grid_fee_mult == grid_fee_mult) & (cache.reserve_mult.round(2) == round(reserve_mult, 2))]
    if q.empty:
        raise KeyError((country, ptype, grid_fee_mult, reserve_mult))
    return q.set_index("year")


def build_check(path=None, year=config.CHECK_YEAR, verbose=True) -> pd.DataFrame:
    """Out-of-sample year: observed prices only (reserve multiplier 1, baseline grid fees)."""
    path = path or config.RESULTS_DIR / f"dispatch_{year}.csv"
    rows = []
    for country in config.COUNTRIES:
        table = data_io.hourly_table(country, [year])
        for ptype in ("Centralised", "Decentralised"):
            vc = variable_cost(country, ptype)
            for mode, with_res in (("co-optimised", True), ("arbitrage-only", False)):
                daily = dispatch.run(table, country, vc, with_reserves=with_res, mw=config.PROJECTS[(country, ptype)]["mw"])
                a = annual(daily).reset_index()
                a.insert(0, "mode", mode)
                a.insert(0, "ptype", ptype)
                a.insert(0, "country", country)
                rows.append(a)
                if verbose:
                    print(f"  {year} {country} {ptype} {mode}: {a['arbitrage'].iloc[0] + a['reserves'].iloc[0]:,.0f} EUR/MW",
                          flush=True)
    out = pd.concat(rows, ignore_index=True).fillna(0.0)
    out.to_csv(path, index=False)
    return out
