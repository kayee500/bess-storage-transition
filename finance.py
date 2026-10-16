"""Project cash flows, NPV, IRR, payback and LCOS (nominal terms, 15-year life).

Structure follows the thesis Excel model: revenue less fixed and variable costs gives
EBITDA; straight-line depreciation over the life; corporate tax on positive earnings
(no loss carry-forward); free cash flow = EBITDA - tax; discounting at the post-tax WACC.
Market revenues come from the dispatch optimisation (per MW), are expressed in 2024 euros
with the euro-area HICP, and are interpolated for any reserve-price multiplier between the
grid points that were solved. Revenues and operating costs escalate with config.INFLATION
from the 2024 price level, so cash flows, the WACC and the hurdle rate are all nominal.
"""

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from . import config

COMPONENTS = ["arbitrage", "reserves", "discharged_mwh", "charging_cost"]


def deflator(year: int) -> float:
    """Factor converting euros of ``year`` into euros of config.PRICE_YEAR."""
    return config.HICP[config.PRICE_YEAR] / config.HICP[int(year)]


def interp_components(cache: pd.DataFrame, country: str, ptype: str, fee_mult: float,
                      mult: float, years=None) -> dict:
    """Average annual per-MW components at reserve-price multiplier ``mult``.

    ``years`` selects which historical years are averaged (default: config.BASE_YEARS).
    """
    years = years or config.BASE_YEARS
    q = cache[(cache.country == country) & (cache.ptype == ptype) & (cache.grid_fee_mult == fee_mult)
              & (cache.year.isin(years)) & (cache.reserve_mult >= 0)]
    # the arbitrage-only reference is stored with reserve_mult 0 and grid_fee_mult 1 too; keep grid runs
    q = q.copy()
    defl = q["year"].map(deflator)
    for c in ("arbitrage", "reserves", "charging_cost"):
        q[c] = q[c] * defl
    q = q.groupby("reserve_mult")[COMPONENTS].mean().sort_index()
    m = float(np.clip(mult, q.index.min(), q.index.max()))
    return {c: float(np.interp(m, q.index.to_numpy(), q[c].to_numpy())) for c in COMPONENTS}


def lcos_reference(cache, country, ptype, years=None) -> dict:
    """Energy throughput and charging cost when the battery only shifts energy (LCOS basis)."""
    years = years or config.BASE_YEARS
    q = cache[(cache.country == country) & (cache.ptype == ptype) & (cache.reserve_mult == -1.0)
              & (cache.year.isin(years))]
    return {"discharged_mwh": float(q["discharged_mwh"].mean()),
            "charging_cost": float((q["charging_cost"] * q["year"].map(deflator)).mean())}


def project_cash_flows(cache, country, ptype, *, base_years=None, reserve_path=None,
                       fee_mult=1.0, arbitrage_mult=1.0, capex_mult=1.0,
                       arbitrage_capture=config.ARBITRAGE_CAPTURE,
                       reserve_realisation=config.RESERVE_REALISATION,
                       capacity_charge=False, delay=0, aggregator_fee=None,
                       peak_shaving_share=None, capex_kwh=None) -> pd.DataFrame:
    """Annual cash-flow table for one project (nominal euros).

    reserve_path: reserve-price multipliers for operating years 1..LIFETIME (default all 1).
    capacity_charge: add a network charge of config.CAPACITY_CHARGE_EUR_KW per kW-year.
    delay: years between the investment and the start of operation (no cash flow meanwhile).
    aggregator_fee, peak_shaving_share, capex_kwh: overrides for sensitivity analysis.
    """
    p = config.PROJECTS[(country, ptype)]
    mw = p["mw"]
    mwh = mw * config.DURATION_H
    T = config.LIFETIME
    path = np.ones(T) if reserve_path is None else np.asarray(reserve_path, dtype=float)
    capex = (capex_kwh if capex_kwh is not None else p["capex_kwh"]) * mwh * 1000 * capex_mult
    fixed0 = p["fixed_om_kw"] * mw * 1000
    charge0 = config.CAPACITY_CHARGE_EUR_KW * mw * 1000 if capacity_charge else 0.0
    vc0 = p["var_om"] + p["grid_fee"] * fee_mult
    fee = config.AGGREGATOR_FEE if aggregator_fee is None else aggregator_fee
    share = config.PEAK_SHAVING_SHARE if peak_shaving_share is None else peak_shaving_share
    tax = config.TAX_RATE[country]
    ref = lcos_reference(cache, country, ptype, base_years)
    rows = [{"year": t, "operating": False} for t in range(1, delay + 1)]
    for k in range(1, T + 1):
        t = delay + k                                  # calendar year after investment
        esc = (1 + config.INFLATION) ** t              # 2024 euros -> nominal euros of year t
        comp = interp_components(cache, country, ptype, fee_mult, path[k - 1], base_years)
        cap = (1 - config.DEGRADATION) ** (k - 1)      # remaining energy capacity
        arb = comp["arbitrage"] * cap * arbitrage_mult * arbitrage_capture * mw * esc
        res = comp["reserves"] * cap * reserve_realisation * mw * esc
        market = arb + res
        if ptype == "Decentralised":
            agg = market * fee
            peak = config.PEAK_SHAVING_EUR_KW[country] * 1000 * mw * share * esc
        else:
            agg, peak = 0.0, 0.0
        discharged = comp["discharged_mwh"] * cap * mw
        var_cost = vc0 * discharged * esc
        fixed = fixed0 * esc
        charge = charge0 * esc
        revenue = market - agg + peak
        ebitda = revenue - fixed - var_cost - charge
        dep = capex / T
        ebt = ebitda - dep
        tx = max(0.0, ebt * tax)
        rows.append({"year": t, "operating": True, "arbitrage": arb, "reserves": res, "peak_shaving": peak,
                     "aggregator_fee": -agg, "revenue": revenue, "fixed_om": fixed,
                     "variable_cost": var_cost, "capacity_charge": charge,
                     "ebitda": ebitda, "depreciation": dep, "tax": tx, "fcf": ebitda - tx,
                     "discharged_mwh": discharged,
                     "lcos_mwh": ref["discharged_mwh"] * cap * mw,
                     "lcos_charging": ref["charging_cost"] * cap * mw * esc,
                     "lcos_var": vc0 * ref["discharged_mwh"] * cap * mw * esc})
    df = pd.DataFrame(rows).fillna(0.0)
    df.attrs.update(capex=capex, rate=config.wacc(country), country=country, ptype=ptype)
    return df


def npv(capex, fcf, rate):
    t = np.arange(1, len(fcf) + 1)
    return -capex + float(np.sum(np.asarray(fcf) / (1 + rate) ** t))


def irr(capex, fcf):
    f = lambda r: npv(capex, fcf, r)
    if f(-0.99) * f(5.0) > 0:
        return np.nan
    return float(brentq(f, -0.99, 5.0))


def payback(capex, fcf, rate=0.0):
    cum = -capex
    for t, cf in enumerate(fcf, start=1):
        prev = cum
        cum += cf / (1 + rate) ** t
        if cum >= 0:
            return t - 1 + (-prev) / (cf / (1 + rate) ** t)   # fractional year
    return np.nan


def lcos(cf: pd.DataFrame, rate):
    """Levelised cost of storage for energy-shifting operation (arbitrage-only dispatch):
    discounted CAPEX, fixed O&M, network charges, variable cost and charging cost per
    discounted MWh discharged (nominal levelised)."""
    t = cf["year"].to_numpy()
    disc = (1 + rate) ** t
    costs = cf.attrs["capex"] + np.sum((cf["fixed_om"] + cf["capacity_charge"] + cf["lcos_var"]
                                        + cf["lcos_charging"]) / disc)
    energy = np.sum(cf["lcos_mwh"] / disc)
    return float(costs / energy) if energy > 0 else np.nan


def metrics(cf: pd.DataFrame) -> dict:
    capex, rate = cf.attrs["capex"], cf.attrs["rate"]
    fcf = cf["fcf"].to_numpy()
    return {
        "capex": capex,
        "wacc": rate,
        "npv": npv(capex, fcf, rate),
        "irr": irr(capex, fcf),
        "payback": payback(capex, fcf),
        "discounted_payback": payback(capex, fcf, rate),
        "lcos": lcos(cf, rate),
        "revenue_y1": float(cf.loc[cf.operating.astype(bool), "revenue"].iloc[0]),
        "fcf_y1": float(cf.loc[cf.operating.astype(bool), "fcf"].iloc[0]),
        "below_hurdle": bool(np.nan_to_num(irr(capex, fcf), nan=-1.0) < config.HURDLE_IRR),
    }


def reserve_path(decline: float = 0.0, years: int = 1) -> np.ndarray:
    """Linear decline of reserve prices: full decline reached after ``years`` years."""
    T = config.LIFETIME
    t = np.arange(1, T + 1)
    return 1 - decline * np.minimum(t / years, 1.0)
