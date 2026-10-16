"""Baseline results, stress scenarios, base-year sensitivity and Monte Carlo."""

import numpy as np
import pandas as pd

from . import config, finance

PROJECT_KEYS = list(config.PROJECTS)


def baseline(cache) -> pd.DataFrame:
    rows = []
    for (c, t) in PROJECT_KEYS:
        cf = finance.project_cash_flows(cache, c, t)
        rows.append({"country": c, "ptype": t, **finance.metrics(cf)})
    return pd.DataFrame(rows)


def baseline_cash_flows(cache) -> dict:
    return {(c, t): finance.project_cash_flows(cache, c, t) for (c, t) in PROJECT_KEYS}


def revenue_by_year(cache) -> pd.DataFrame:
    """Per-MW market revenue by historical year (co-optimised, reserve prices as observed,
    nominal euros of each year)."""
    q = cache[(cache.grid_fee_mult == 1.0) & (cache.reserve_mult == 1.0)].copy()
    res_cols = [c for c in q.columns if c.startswith("res_")]
    keep = ["country", "ptype", "year", "arbitrage", "reserves", "discharged_mwh"] + res_cols
    return q[keep].reset_index(drop=True)


def arbitrage_only(cache) -> pd.DataFrame:
    """Reference: per-MW margin when the battery only trades on the day-ahead market."""
    q = cache[cache.reserve_mult == -1.0]
    return q[["country", "ptype", "year", "arbitrage", "discharged_mwh"]].reset_index(drop=True)


def scenarios(cache) -> pd.DataFrame:
    rows = []
    for name, s in config.SCENARIOS.items():
        for (c, t) in PROJECT_KEYS:
            # a connection delay concerns grid-connected stand-alone projects, not behind-the-meter portfolios
            applies = s.get("country") in (None, c) and s.get("ptype") in (None, t)
            if applies:
                path = finance.reserve_path(s.get("reserve_decline", 0.0), s.get("decline_years", 1))
                arb = s.get("arbitrage_mult", 1.0)
                charge = bool(s.get("capacity_charge")) and c == "DE"
                delay = config.CONNECTION_DELAY_YEARS if s.get("delay") and c == "DE" else 0
            else:
                path, arb, charge, delay = None, 1.0, False, 0
            cf = finance.project_cash_flows(cache, c, t, reserve_path=path, arbitrage_mult=arb,
                                            capacity_charge=charge, delay=delay)
            rows.append({"scenario": name, "applies": applies, "country": c, "ptype": t, **finance.metrics(cf)})
    return pd.DataFrame(rows)


def base_year_sensitivity(cache) -> pd.DataFrame:
    """Results if the revenues of a single historical year persisted for the whole life."""
    rows = []
    for y in config.YEARS:
        for (c, t) in PROJECT_KEYS:
            cf = finance.project_cash_flows(cache, c, t, base_years=[y])
            rows.append({"base_year": y, "country": c, "ptype": t, **finance.metrics(cf)})
    return pd.DataFrame(rows)


def breakeven_reserve_mult(cache, target_irr=config.HURDLE_IRR) -> pd.DataFrame:
    """Constant reserve-price level (share of observed) at which IRR equals the hurdle rate."""
    rows = []
    for (c, t) in PROJECT_KEYS:
        f = lambda m: finance.metrics(finance.project_cash_flows(
            cache, c, t, reserve_path=np.full(config.LIFETIME, m)))["irr"]
        grid = np.linspace(0, 1, 101)
        vals = np.array([f(m) for m in grid])
        vals = np.where(np.isnan(vals), -1.0, vals)
        above = np.where(vals >= target_irr)[0]
        m_star = float(grid[above[0]]) if len(above) else np.nan
        # the same threshold expressed as reserve revenue relative to the base year
        r_star = finance.interp_components(cache, c, t, 1.0, m_star)["reserves"] if not np.isnan(m_star) else np.nan
        r_one = finance.interp_components(cache, c, t, 1.0, 1.0)["reserves"]
        rows.append({"country": c, "ptype": t, "breakeven_reserve_level": m_star,
                     "breakeven_reserve_revenue": r_star / r_one})
    return pd.DataFrame(rows)


def monte_carlo(cache, n=config.MC_DRAWS, seed=config.MC_SEED,
                trend=config.RESERVE_TREND_TRIANGLE) -> tuple[pd.DataFrame, dict]:
    """Stochastic lifetime cash flows (nominal, as in finance.project_cash_flows).

    Each draw samples a CAPEX multiplier, an arbitrage capture factor, a reserve realisation
    factor and an annual drift in reserve prices (triangular), and, for each of the 15
    operating years, one historical market year (2020-2024) whose revenues relative to the
    2020-2024 mean are applied around the base-year level (year bootstrap). The same draws are
    used for all four projects. ``trend`` sets the drift distribution (min, mode, max).
    """
    rng = np.random.default_rng(seed)
    T = config.LIFETIME
    capex_m = rng.triangular(*config.CAPEX_TRIANGLE, size=n)
    capture = rng.triangular(*config.ARBITRAGE_CAPTURE_TRIANGLE, size=n)
    real = rng.triangular(*config.RESERVE_REALISATION_TRIANGLE, size=n)
    drift = rng.triangular(*trend, size=n)
    year_idx = rng.integers(0, len(config.YEARS), size=(n, T))
    t = np.arange(T)
    mult = np.clip((1 + drift[:, None]) ** t[None, :], 0, 1)         # n x T reserve multipliers
    esc = (1 + config.INFLATION) ** (t + 1)
    cap = (1 - config.DEGRADATION) ** t[None, :]

    summaries, draws = [], {}
    for (c, ptype) in PROJECT_KEYS:
        p = config.PROJECTS[(c, ptype)]
        mw = p["mw"]
        capex0 = p["capex_kwh"] * mw * config.DURATION_H * 1000
        fixed = p["fixed_om_kw"] * mw * 1000
        vc = p["var_om"] + p["grid_fee"]
        rate = config.wacc(c)
        tax = config.TAX_RATE[c]
        q = cache[(cache.country == c) & (cache.ptype == ptype) & (cache.grid_fee_mult == 1.0)]
        q = q[q.reserve_mult >= 0].copy()
        for k in ("arbitrage", "reserves"):
            q[k] = q[k] * q["year"].map(finance.deflator)
        grid = np.array(sorted(q.reserve_mult.unique()))
        comp = {k: np.array([[q[(q.year == y) & (q.reserve_mult == m)][k].iloc[0] for m in grid]
                             for y in config.YEARS]) for k in ("arbitrage", "reserves", "discharged_mwh")}
        base = np.array([config.YEARS.index(y) for y in config.BASE_YEARS])
        for k in comp:
            mean = comp[k].mean(axis=0, keepdims=True)
            level = comp[k][base].mean(axis=0, keepdims=True)
            ratio = np.divide(comp[k], mean, out=np.ones_like(comp[k]), where=mean > 0)
            comp[k] = level * ratio

        def at(k):
            tab = comp[k][year_idx]                              # n x T x len(grid)
            pos = np.interp(mult, grid, np.arange(len(grid)))
            lo = np.floor(pos).astype(int)
            hi = np.minimum(lo + 1, len(grid) - 1)
            w = pos - lo
            a_ = np.take_along_axis(tab, lo[..., None], 2)[..., 0]
            b_ = np.take_along_axis(tab, hi[..., None], 2)[..., 0]
            return a_ * (1 - w) + b_ * w

        arb = at("arbitrage") * cap * capture[:, None] * mw * esc
        res = at("reserves") * cap * real[:, None] * mw * esc
        dis = at("discharged_mwh") * cap * mw
        market = arb + res
        if ptype == "Decentralised":
            market = market * (1 - config.AGGREGATOR_FEE) \
                + config.PEAK_SHAVING_EUR_KW[c] * 1000 * mw * config.PEAK_SHAVING_SHARE * esc
        ebitda = market - (fixed + vc * dis) * esc
        capex = capex0 * capex_m
        ebt = ebitda - capex[:, None] / T
        fcf = ebitda - np.maximum(0, ebt * tax)
        disc = (1 + rate) ** (t + 1)
        npv = -capex + (fcf / disc).sum(axis=1)
        irr = np.array([finance.irr(k_, f) for k_, f in zip(capex, fcf)])
        draws[(c, ptype)] = pd.DataFrame({"npv": npv, "irr": irr})
        summaries.append({
            "country": c, "ptype": ptype,
            "npv_median": float(np.median(npv)), "npv_p05": float(np.percentile(npv, 5)),
            "npv_p95": float(np.percentile(npv, 95)),
            "irr_median": float(np.nanmedian(irr)),
            "prob_npv_negative": float((npv < 0).mean()),
            "prob_irr_below_hurdle": float(np.mean(np.nan_to_num(irr, nan=-1) < config.HURDLE_IRR)),
        })
    return pd.DataFrame(summaries), draws


def out_of_sample(cache, check: pd.DataFrame) -> pd.DataFrame:
    """Compare the 2025 out-of-sample year with the base year and the scenario paths.

    reserve_index = 2025 reserve revenue / base-year reserve revenue (co-optimised, per MW).
    The scenario columns give the reserve-price multiplier each scenario assumed for year 1.
    2025 values are converted to 2024 euros with the HICP before the ratios are formed.
    """
    base = cache[(cache.reserve_mult == 1.0) & (cache.grid_fee_mult == 1.0) & (cache.year.isin(config.BASE_YEARS))]
    base = base.groupby(["country", "ptype"])[["arbitrage", "reserves"]].mean()
    chk = check[check["mode"] == "co-optimised"].set_index(["country", "ptype"])[["arbitrage", "reserves"]]
    chk = chk * finance.deflator(config.CHECK_YEAR)          # 2025 euros -> 2024 euros
    out = pd.DataFrame({
        "arbitrage_base": base["arbitrage"], "reserves_base": base["reserves"],
        "arbitrage_2025": chk["arbitrage"], "reserves_2025": chk["reserves"],
    })
    out["market_base"] = out.arbitrage_base + out.reserves_base
    out["market_2025"] = out.arbitrage_2025 + out.reserves_2025
    out["reserve_index"] = out.reserves_2025 / out.reserves_base
    out["market_index"] = out.market_2025 / out.market_base
    for name, s in config.SCENARIOS.items():
        if "reserve_decline" in s:
            out[f"y1_{name}"] = finance.reserve_path(s["reserve_decline"], s["decline_years"])[0]
    return out.reset_index()


def persisted_2025(check: pd.DataFrame) -> pd.DataFrame:
    """Financial metrics if 2025 market conditions persisted for the whole life."""
    rows = []
    for (c, t) in PROJECT_KEYS:
        q = check[(check.country == c) & (check.ptype == t)]
        co = q[q["mode"] == "co-optimised"].iloc[0]
        ar = q[q["mode"] == "arbitrage-only"].iloc[0]
        fake = pd.DataFrame([
            {"country": c, "ptype": t, "grid_fee_mult": 1.0, "reserve_mult": 1.0, "year": config.CHECK_YEAR,
             "arbitrage": co.arbitrage, "reserves": co.reserves, "discharged_mwh": co.discharged_mwh,
             "charging_cost": co.charging_cost},
            {"country": c, "ptype": t, "grid_fee_mult": 1.0, "reserve_mult": -1.0, "year": config.CHECK_YEAR,
             "arbitrage": ar.arbitrage, "reserves": 0.0, "discharged_mwh": ar.discharged_mwh,
             "charging_cost": ar.charging_cost}])
        cf = finance.project_cash_flows(fake, c, t, base_years=[config.CHECK_YEAR])
        rows.append({"country": c, "ptype": t, **finance.metrics(cf)})
    return pd.DataFrame(rows)


def decentralised_sensitivity(cache) -> pd.DataFrame:
    """Which assumptions drive the decentralised result (baseline IRR under alternatives)."""
    cases = {
        "Baseline": {},
        "No peak shaving": {"peak_shaving_share": 0.0},
        "Aggregator fee 10%": {"aggregator_fee": 0.10},
        "CAPEX per kWh as centralised": {"capex_kwh": "central"},
        "Aggregator fee 10% and CAPEX as centralised": {"aggregator_fee": 0.10, "capex_kwh": "central",
                                                          "peak_shaving_share": config.PEAK_SHAVING_SHARE},
    }
    rows = []
    for name, kw in cases.items():
        for c in config.COUNTRIES:
            kw2 = dict(kw)
            if kw2.get("capex_kwh") == "central":
                kw2["capex_kwh"] = config.PROJECTS[(c, "Centralised")]["capex_kwh"]
            cf = finance.project_cash_flows(cache, c, "Decentralised", **kw2)
            m = finance.metrics(cf)
            rows.append({"case": name, "country": c, "irr": m["irr"], "npv": m["npv"]})
    return pd.DataFrame(rows)


def realisation_sensitivity(cache) -> pd.DataFrame:
    """Baseline IRR for alternative reserve realisation factors."""
    rows = []
    for a in (0.50, 0.75, 1.00):
        for (c, t) in PROJECT_KEYS:
            m = finance.metrics(finance.project_cash_flows(cache, c, t, reserve_realisation=a))
            rows.append({"reserve_realisation": a, "country": c, "ptype": t, "irr": m["irr"], "npv": m["npv"]})
    return pd.DataFrame(rows)
