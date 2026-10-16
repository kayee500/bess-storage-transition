"""Load and harmonise the raw market data into one hourly table per country.

Output columns (all prices in EUR; reserve prices are per MW per hour of commitment):
    time_local   wall-clock hour in CET/CEST (timezone-aware)
    da           day-ahead price, EUR/MWh
    <product>    reserve capacity price, EUR/MW/h (NaN = product not procured)
    blk_<group>  block label: hours that must carry the same reserve commitment
"""

import json
import re

import numpy as np
import pandas as pd

from . import config


# ---------------------------------------------------------------------------
# Day-ahead prices (Energy-Charts API, sourced from SMARD/ENTSO-E)
# ---------------------------------------------------------------------------
def load_day_ahead(country: str, years=config.DESCRIPTIVE_YEARS) -> pd.DataFrame:
    zone = config.BIDDING_ZONE[country]
    frames = []
    for y in years:
        d = json.loads((config.EC_DIR / f"price_{zone}_{y}.json").read_text())
        if len(d["unix_seconds"]) != len(d["price"]):
            raise ValueError(f"{zone} {y}: time and price arrays differ in length")
        frames.append(pd.DataFrame({"unix": d["unix_seconds"], "da": d["price"]}))
    df = pd.concat(frames, ignore_index=True).drop_duplicates("unix")
    # From 1 October 2025 the day-ahead market clears in 15-minute periods; use hourly means
    df["unix"] = df["unix"] // 3600 * 3600
    df = df.groupby("unix", as_index=False)["da"].mean()
    if df["da"].isna().any():
        raise ValueError(f"{zone}: missing day-ahead prices")
    if not (np.diff(df["unix"].to_numpy()) == 3600).all():
        raise ValueError(f"{zone}: day-ahead series is not continuous and hourly")
    df["time_local"] = pd.to_datetime(df["unix"], unit="s", utc=True).dt.tz_convert(config.LOCAL_TZ)
    return df[["time_local", "da"]]


def _wall(ts: pd.Series) -> pd.Series:
    """Naive local wall-clock time used to join files published in local time."""
    return ts.dt.tz_localize(None)


# ---------------------------------------------------------------------------
# Sweden: Svenska kraftnat Mimer exports (semicolon CSV, decimal comma, local time)
# ---------------------------------------------------------------------------
def _read_mimer(path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", decimal=",", encoding="utf-8-sig", dtype=str)
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    df = df[~df.iloc[:, 0].str.startswith("Summa")]
    df["wall"] = pd.to_datetime(df.iloc[:, 0])
    return df


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce")


def load_se_reserves() -> pd.DataFrame:
    """Swedish reserve prices (EUR/MW/h) and procured volumes (MW, columns vol_<product>).

    Prices in hours with no procured volume are set to NaN (no market in that hour).
    FCR volumes are not published in the 2019-2020 export; for those years the hourly
    volume is set to the 2021 mean of each product (used only for the participation cap).
    """
    fcr, afrr = [], []
    for path in sorted(config.SVK_DIR.glob("*.csv")):
        df = _read_mimer(path)
        if "FCR-N Pris (EUR/MW)" in df.columns:
            vol = lambda c: _num(df[c]) if c in df.columns else pd.Series(np.nan, index=df.index)
            fcr.append(pd.DataFrame({
                "wall": df["wall"],
                "FCR-N": _num(df["FCR-N Pris (EUR/MW)"]),
                "FCR-D_up": _num(df["FCR-D upp Pris (EUR/MW)"]),
                "FCR-D_dn": _num(df["FCR-D ned Pris (EUR/MW)"]),
                "vol_FCR-N": vol("Total"),
                "vol_FCR-D_up": vol("Total FCRD upp"),
                "vol_FCR-D_dn": vol("Total FCRD ned"),
            }))
        elif "aFRR Upp Pris (EUR/MW)" in df.columns:
            area = df["Elområde"].fillna("")
            keep = area.eq("") if area.eq("").all() else area.eq(config.SE_AFRR_AREA)
            df = df[keep]
            afrr.append(pd.DataFrame({
                "wall": df["wall"],
                "aFRR_up": _num(df["aFRR Upp Pris (EUR/MW)"]),
                "aFRR_dn": _num(df["aFRR Ned Pris (EUR/MW)"]),
                "vol_aFRR_up": _num(df["aFRR Upp Volym (MW)"]),
                "vol_aFRR_dn": _num(df["aFRR Ned Volym (MW)"]),
            }))
    fcr = pd.concat(fcr).drop_duplicates("wall").set_index("wall").sort_index()
    afrr = pd.concat(afrr).drop_duplicates("wall").set_index("wall").sort_index()
    out = fcr.join(afrr, how="outer")
    # FCR volumes missing in the 2019-2020 export: use the 2021 mean as a proxy for the cap
    for k in ("FCR-N", "FCR-D_up", "FCR-D_dn"):
        mean21 = out.loc["2021", f"vol_{k}"].mean()
        out.loc[out.index.year <= 2020, f"vol_{k}"] = mean21
    # no procured volume (or a zero price) means no market in that hour
    for k in config.PRODUCTS["SE"]:
        none = (out[f"vol_{k}"].fillna(1) <= 0) | (out[k] <= 0)
        out.loc[none, k] = np.nan
    return out


# ---------------------------------------------------------------------------
# Germany: regelleistung.net tender results (XLSX, one row per day and product block)
# ---------------------------------------------------------------------------
def _block_hours(name: str) -> tuple[int, int]:
    a, b = re.findall(r"(\d\d)_(\d\d)$", name)[0]
    return int(a), int(b)


def _read_rl(kind: str) -> pd.DataFrame:
    frames = []
    for path in sorted(config.RL_DIR.glob(f"RESULT_OVERVIEW_CAPACITY_MARKET_{kind}_*.xlsx")):
        df = pd.read_excel(path)
        if df.empty:
            continue
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def load_de_reserves() -> pd.DataFrame:
    rows = []
    # FCR: settlement price per MW for the product block; main auction only (tender 1)
    fcr = _read_rl("FCR")
    col = fcr["DE_SETTLEMENTCAPACITY_PRICE_[EUR/MW]"] if "DE_SETTLEMENTCAPACITY_PRICE_[EUR/MW]" in fcr else None
    if "GERMANY_SETTLEMENTCAPACITY_PRICE_[EUR/MW]" in fcr:
        col = fcr["GERMANY_SETTLEMENTCAPACITY_PRICE_[EUR/MW]"] if col is None else col.fillna(fcr["GERMANY_SETTLEMENTCAPACITY_PRICE_[EUR/MW]"])
    dem = fcr["DE_DEMAND_[MW]"] if "DE_DEMAND_[MW]" in fcr else None
    if "GERMANY_DEMAND_[MW]" in fcr:
        dem = fcr["GERMANY_DEMAND_[MW]"] if dem is None else dem.fillna(fcr["GERMANY_DEMAND_[MW]"])
    fcr = fcr.assign(price=pd.to_numeric(col, errors="coerce"), vol=pd.to_numeric(dem, errors="coerce"))
    fcr = fcr[fcr["TENDER_NUMBER"] == 1].drop_duplicates(["DATE_FROM", "PRODUCTNAME"])
    for r in fcr.itertuples(index=False):
        h0, h1 = _block_hours(r.PRODUCTNAME)
        rows.append(("FCR", pd.Timestamp(r.DATE_FROM).normalize(), h0, h1, r.price / (h1 - h0), r.vol))
    # aFRR: pay-as-bid, average accepted capacity price. Units changed in 2021:
    # EUR/MW per 4-hour block until 2020, EUR/MW per hour from 2021.
    afrr = _read_rl("aFRR")
    per_block = afrr["GERMANY_AVERAGE_CAPACITY_PRICE_[EUR/MW]"] if "GERMANY_AVERAGE_CAPACITY_PRICE_[EUR/MW]" in afrr else pd.Series(np.nan, index=afrr.index)
    per_hour = afrr["GERMANY_AVERAGE_CAPACITY_PRICE_[(EUR/MW)/h]"]
    afrr = afrr.assign(pb=pd.to_numeric(per_block, errors="coerce"), ph=pd.to_numeric(per_hour, errors="coerce"))
    afrr = afrr.drop_duplicates(["DATE_FROM", "PRODUCT"])
    for r in afrr.itertuples(index=False):
        h0, h1 = _block_hours(r.PRODUCT)
        price = r.ph if not np.isnan(r.ph) else r.pb / (h1 - h0)
        prod = "aFRR_up" if r.PRODUCT.startswith("POS") else "aFRR_dn"
        # aFRR volumes are not published for most of the period; no participation cap
        rows.append((prod, pd.Timestamp(r.DATE_FROM).normalize(), h0, h1, price, np.nan))
    blocks = pd.DataFrame(rows, columns=["product", "day", "h0", "h1", "price", "vol"])
    if blocks.duplicated(["product", "day", "h0"]).any():
        raise ValueError("German reserve data contain duplicate blocks")
    return blocks


# ---------------------------------------------------------------------------
# Combined hourly table
# ---------------------------------------------------------------------------
def hourly_table(country: str, years=None) -> pd.DataFrame:
    years = years or config.YEARS
    df = load_day_ahead(country, years)
    df["wall"] = _wall(df["time_local"])
    df["day"] = df["wall"].dt.normalize()
    df["hour"] = df["wall"].dt.hour
    if country == "SE":
        res = load_se_reserves()
        df = df.merge(res, left_on="wall", right_index=True, how="left")
        for prod in config.PRODUCTS["SE"]:
            df[f"blk_{prod}"] = df["hour"]           # hourly products
    else:
        blocks = load_de_reserves()
        for prod in config.PRODUCTS["DE"]:
            b = blocks[blocks["product"] == prod]
            # expand each block to its hours
            exp = b.loc[b.index.repeat(b["h1"] - b["h0"])].copy()
            exp["hour"] = exp["h0"] + exp.groupby(level=0).cumcount()
            exp = exp.rename(columns={"price": prod, "vol": f"vol_{prod}"})
            exp[f"blk_{prod}"] = exp["h0"]
            df = df.merge(exp[["day", "hour", prod, f"vol_{prod}", f"blk_{prod}"]], on=["day", "hour"], how="left")
            df[f"blk_{prod}"] = df[f"blk_{prod}"].fillna(df["hour"]).astype(int)
    df = df.drop(columns=["wall"])
    return df.reset_index(drop=True)


def coverage(df: pd.DataFrame, country: str) -> pd.DataFrame:
    """Share of hours with a reserve price, by year and product."""
    prods = list(config.PRODUCTS[country])
    g = df.groupby(df["time_local"].dt.year)
    return pd.DataFrame({p: g[p].apply(lambda s: s.notna().mean()) for p in prods})
