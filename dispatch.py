"""Daily co-optimisation of energy arbitrage and reserve capacity (per 1 MW / 2 MWh).

For every delivery day the battery chooses, with perfect foresight of that day's prices,
hourly charging and discharging on the day-ahead market and the MW offered in each
reserve product. Reserve commitments must be constant within a product block, fit inside
the power rating together with the energy schedule, not exceed the rated power in total per
direction, stay within a maximum share of the procured volume, and be backed by enough stored
energy (and empty capacity) to deliver for the product's required duration. Only capacity
payments are counted for reserves; activation energy is assumed to net to zero.
"""

from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

from . import config

P = 1.0                                   # MW
E = config.DURATION_H * P                 # MWh
S0 = config.INITIAL_SOC * E


def optimise_day(da: np.ndarray, res: dict, vc: float, products: dict, mw: float = 1.0) -> dict:
    """Solve one day.

    da       hourly day-ahead prices (EUR/MWh), length H
    res      {product: (hourly price EUR/MW/h, block labels, procured volume MW)}
    vc       variable cost per MWh discharged (O&M + grid fee)
    products config.PRODUCTS[country]
    mw       project power; the project may offer at most config.MAX_MARKET_SHARE of the
             procured volume of a product (scaled to this 1 MW unit)
    """
    H = len(da)
    eta = config.ETA
    # variable layout: c, d, s, z, then one variable per (product, block)
    rvars = []                                  # (product, block, hours mask, revenue coef, ub)
    for k, (price, blk, vol) in res.items():
        for b in pd.unique(blk):
            mask = blk == b
            p = price[mask]
            valid = ~np.isnan(p)
            coef = float(np.nansum(p)) if valid.any() else 0.0
            ub = P if valid.any() else 0.0
            v = vol[mask][valid] if valid.any() else np.array([])
            v = v[~np.isnan(v)]
            if len(v):
                ub = min(ub, config.MAX_MARKET_SHARE * float(v.min()) / mw)
            rvars.append((k, b, mask, coef, ub))
    n = 4 * H + len(rvars)
    ic, id_, is_, iz = 0, H, 2 * H, 3 * H

    cost = np.zeros(n)
    cost[ic:ic + H] = da                        # minimise -profit
    cost[id_:id_ + H] = -da + vc
    for j, (_, _, _, coef, _) in enumerate(rvars):
        cost[4 * H + j] = -coef

    lb = np.zeros(n)
    ub = np.concatenate([np.full(H, P), np.full(H, P), np.full(H, E), np.ones(H),
                         np.array([v[4] for v in rvars])])
    integrality = np.zeros(n)
    integrality[iz:iz + H] = 1

    rows = 11 * H + 2
    A = lil_matrix((rows, n))
    lo = np.full(rows, -np.inf)
    hi = np.full(rows, np.inf)
    r = 0
    for h in range(H):
        up = [4 * H + j for j, v in enumerate(rvars) if v[2][h] and products[v[0]]["dir"] in ("sym", "up")]
        dn = [4 * H + j for j, v in enumerate(rvars) if v[2][h] and products[v[0]]["dir"] in ("sym", "dn")]
        e_up = {4 * H + j: products[v[0]]["hours"] for j, v in enumerate(rvars) if 4 * H + j in up}
        e_dn = {4 * H + j: products[v[0]]["hours"] for j, v in enumerate(rvars) if 4 * H + j in dn}
        # power: upward and downward capability
        A[r, id_ + h] = 1; A[r, ic + h] = -1
        for v in up: A[r, v] = 1
        hi[r] = P; r += 1
        A[r, ic + h] = 1; A[r, id_ + h] = -1
        for v in dn: A[r, v] = 1
        hi[r] = P; r += 1
        # total reserve offered in each direction cannot exceed the rated power
        for v in up: A[r, v] = 1
        hi[r] = P; r += 1
        for v in dn: A[r, v] = 1
        hi[r] = P; r += 1
        # no simultaneous charging and discharging
        A[r, ic + h] = 1; A[r, iz + h] = -P; hi[r] = 0; r += 1
        A[r, id_ + h] = 1; A[r, iz + h] = P; hi[r] = P; r += 1
        # state of charge
        A[r, is_ + h] = 1; A[r, ic + h] = -eta; A[r, id_ + h] = 1 / eta
        if h > 0:
            A[r, is_ + h - 1] = -1; lo[r] = hi[r] = 0
        else:
            lo[r] = hi[r] = S0
        r += 1
        # energy headroom at the end and at the start of the hour
        A[r, is_ + h] = 1
        for v, e in e_up.items(): A[r, v] = -e
        lo[r] = 0; r += 1
        A[r, is_ + h] = 1
        for v, e in e_dn.items(): A[r, v] = e
        hi[r] = E; r += 1
        if h > 0:
            A[r, is_ + h - 1] = 1
            for v, e in e_up.items(): A[r, v] = -e
            lo[r] = 0
        else:
            for v, e in e_up.items(): A[r, v] = -e
            lo[r] = -S0
        r += 1
        if h > 0:
            A[r, is_ + h - 1] = 1
            for v, e in e_dn.items(): A[r, v] = e
            hi[r] = E
        else:
            for v, e in e_dn.items(): A[r, v] = e
            hi[r] = E - S0
        r += 1
    # daily discharge limit and end-of-day state of charge
    A[r, id_:id_ + H] = 1; hi[r] = config.CYCLES_PER_DAY * E; r += 1
    A[r, is_ + H - 1] = 1; lo[r] = hi[r] = S0; r += 1

    sol = milp(cost, constraints=LinearConstraint(A.tocsr(), lo, hi), integrality=integrality,
               bounds=Bounds(lb, ub), options={"mip_rel_gap": config.MILP_REL_GAP})
    if not sol.success:
        raise RuntimeError(f"MILP failed: {sol.message}")
    x = sol.x
    c, d = x[ic:ic + H], x[id_:id_ + H]
    out = {
        "arbitrage": float(da @ (d - c)),
        "charged_mwh": float(c.sum()),
        "discharged_mwh": float(d.sum()),
        "charging_cost": float(da @ c),
    }
    for k in res:
        out[f"res_{k}"] = 0.0
        out[f"mw_{k}"] = 0.0
    for j, (k, b, mask, coef, _) in enumerate(rvars):
        out[f"res_{k}"] += coef * x[4 * H + j]
        out[f"mw_{k}"] += x[4 * H + j] * mask.sum()       # MW-hours committed
    return out


def _run_days(args):
    country, chunk, vc, mult, with_reserves, mw = args
    products = config.PRODUCTS[country]
    rows = []
    for day, g in chunk:
        res = {}
        if with_reserves:
            for k in products:
                vol = g[f"vol_{k}"].to_numpy(dtype=float) if f"vol_{k}" in g else np.full(len(g), np.nan)
                res[k] = (g[k].to_numpy(dtype=float) * mult, g[f"blk_{k}"].to_numpy(), vol)
        out = optimise_day(g["da"].to_numpy(dtype=float), res, vc, products, mw)
        out["day"] = day
        rows.append(out)
    return rows


def run(df: pd.DataFrame, country: str, vc: float, reserve_mult: float = 1.0,
        with_reserves: bool = True, workers: int = 2, mw: float = 1.0) -> pd.DataFrame:
    """Solve every day in ``df``; returns one row per day (values per MW)."""
    days = list(df.groupby("day", sort=True))
    chunks = [days[i::workers] for i in range(workers)]
    with ProcessPoolExecutor(workers) as ex:
        parts = ex.map(_run_days, [(country, ch, vc, reserve_mult, with_reserves, mw) for ch in chunks])
    out = pd.DataFrame([r for p in parts for r in p]).sort_values("day").reset_index(drop=True)
    res_cols = [c for c in out.columns if c.startswith("res_")]
    out["reserves"] = out[res_cols].sum(axis=1) if res_cols else 0.0
    out["year"] = pd.to_datetime(out["day"]).dt.year
    return out
