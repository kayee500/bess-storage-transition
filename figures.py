"""Figures 1-5 (PNG at 600 dpi and vector PDF)."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import config, data_io

BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
INK, MUTED = "#0b0b0b", "#52514e"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": "#e4e3df",
    "grid.linewidth": 0.6, "axes.axisbelow": True, "legend.frameon": False,
})
PROJECT_LABEL = {("DE", "Centralised"): "Germany, centralised", ("SE", "Centralised"): "Sweden, centralised",
                 ("DE", "Decentralised"): "Germany, decentralised", ("SE", "Decentralised"): "Sweden, decentralised"}


def _save(fig, name):
    config.FIGURES_DIR.mkdir(exist_ok=True)
    fig.savefig(config.FIGURES_DIR / f"{name}.png", dpi=600, bbox_inches="tight")
    fig.savefig(config.FIGURES_DIR / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


def fig1_revenue_history(cache, check):
    """Stacked perfect-foresight market revenue per MW by year and stream (centralised)."""
    rows = []
    q = cache[(cache.ptype == "Centralised") & (cache.grid_fee_mult == 1.0) & (cache.reserve_mult == 1.0)]
    k = check[(check.ptype == "Centralised") & (check["mode"] == "co-optimised")]
    for df in (q, k):
        for d in df.to_dict("records"):
            fcr = sum(float(d.get(c, 0.0) or 0.0) for c in ("res_FCR", "res_FCR-N", "res_FCR-D_up", "res_FCR-D_dn"))
            afrr = float(d.get("res_aFRR_up", 0.0) or 0.0) + float(d.get("res_aFRR_dn", 0.0) or 0.0)
            rows.append({"country": d["country"], "year": int(d["year"]), "arb": d["arbitrage"],
                         "fcr": fcr, "afrr": afrr})
    df = pd.DataFrame(rows).groupby(["country", "year"]).sum().reset_index()
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0), sharey=True)
    for ax, c, title in zip(axes, ["DE", "SE"], ["Germany (DE-LU)", "Sweden (SE3)"]):
        g = df[df.country == c].sort_values("year")
        x = np.arange(len(g))
        b = np.zeros(len(g))
        for col, color, lab in (("arb", BLUE, "Day-ahead arbitrage"), ("fcr", ORANGE, "FCR products"),
                                ("afrr", AQUA, "aFRR")):
            v = g[col].to_numpy() / 1000
            ax.bar(x, v, bottom=b, color=color, width=0.62, edgecolor="white", linewidth=0.8, label=lab)
            b += v
        for xi, tot in zip(x, b):
            ax.text(xi, tot + 15, f"{tot:,.0f}", ha="center", va="bottom", fontsize=7, color=INK)
        ax.set_xticks(x, [str(y) if y != config.CHECK_YEAR else f"{y}*" for y in g.year])
        ax.set_title(title, loc="left", color=INK)
    axes[0].set_ylabel("Market revenue (thousand EUR per MW-year)")
    axes[0].legend(loc="upper left", fontsize=7.5)
    fig.text(0.0, -0.04, "* 2025 is the out-of-sample year. Perfect-foresight daily co-optimisation, "
             "1 MW / 2 MWh, before realisation factors.", fontsize=7, color=MUTED)
    _save(fig, "fig1_revenue_history")


def fig2_reserve_prices():
    """Monthly mean reserve capacity prices (EUR per MW per hour)."""
    years = config.DESCRIPTIVE_YEARS[1:]
    de = data_io.hourly_table("DE", years)
    se = data_io.hourly_table("SE", years)
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.9), sharey=True)
    for ax, df, series, title in (
        (axes[0], de, [("FCR", ["FCR"], BLUE), ("aFRR (mean of up and down)", ["aFRR_up", "aFRR_dn"], ORANGE)],
         "Germany"),
        (axes[1], se, [("FCR-N", ["FCR-N"], BLUE), ("FCR-D (mean of up and down)", ["FCR-D_up", "FCR-D_dn"], ORANGE),
                       ("aFRR (mean of up and down)", ["aFRR_up", "aFRR_dn"], AQUA)], "Sweden")):
        m = df.set_index("time_local").copy()
        if title == "Sweden":
            # Swedish aFRR: hours without procurement count as zero (consistent with Table 1)
            for c in ("aFRR_up", "aFRR_dn"):
                m[c] = m[c].fillna(0.0)
        for lab, cols, color in series:
            s = m[cols].mean(axis=1, skipna=True).resample("MS").mean()
            ax.plot(s.index, s.values, color=color, lw=1.6, label=lab)
        ax.set_title(title, loc="left", color=INK)
        ax.axvspan(pd.Timestamp("2025-01-01", tz=config.LOCAL_TZ), pd.Timestamp("2025-12-31", tz=config.LOCAL_TZ),
                   color="#f1f0ec", zorder=0)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), fontsize=7, ncol=1)
    axes[0].set_ylabel("Capacity price (EUR per MW per hour)")
    fig.text(0.0, -0.22, "Monthly means; Swedish aFRR hours without procurement count as zero. Shaded: 2025. Sources: regelleistung.net; "
             "Svenska kraftnät (Mimer).", fontsize=7, color=MUTED)
    _save(fig, "fig2_reserve_prices")


def fig3_scenarios(scen):
    order = list(config.SCENARIOS)
    fig, axes = plt.subplots(1, 4, figsize=(7.2, 3.3), sharey=True)
    y = np.arange(len(order))[::-1]
    for ax, key in zip(axes, PROJECT_LABEL):
        g = scen[(scen.country == key[0]) & (scen.ptype == key[1])].set_index("scenario").loc[order]
        colors = [GREY if not a else (ORANGE if v < config.HURDLE_IRR else BLUE)
                  for a, v in zip(g.applies, g.irr)]
        ax.barh(y, g.irr * 100, color=colors, height=0.62, edgecolor="white")
        for yi, v in zip(y, g.irr * 100):
            ax.text(max(v, 0) + 1, yi, f"{0.0 if abs(v) < 0.05 else v:.1f}", va="center", fontsize=6.5, color=INK,
                    bbox=dict(facecolor="white", edgecolor="none", pad=0.6))
        ax.axvline(config.HURDLE_IRR * 100, color=INK, lw=0.9, ls="--")
        ax.set_xlim(0, max(g.irr.max() * 100 * 1.3, 15))
        ax.set_title(PROJECT_LABEL[key].replace(", ", ",\n"), loc="left", color=INK, fontsize=8)
        ax.set_xlabel("IRR (%)")
    axes[0].set_yticks(y, order)
    fig.text(0.0, -0.06, "Dashed line: 8% hurdle rate. Orange: below hurdle. Grey: scenario does not apply "
             "to this project (baseline shown).", fontsize=7, color=MUTED)
    fig.tight_layout()
    _save(fig, "fig3_scenarios")


def fig4_montecarlo(draws):
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 4.6))
    for ax, key in zip(axes.flat, PROJECT_LABEL):
        irr = draws[key]["irr"].dropna().to_numpy() * 100
        lo, hi = np.percentile(irr, [0.1, 99.5])
        ax.hist(irr, bins=60, range=(min(lo, config.HURDLE_IRR * 100 - 2), hi), color=BLUE,
                edgecolor="white", linewidth=0.3)
        ax.axvline(config.HURDLE_IRR * 100, color=INK, lw=0.9, ls="--")
        p = np.mean(np.nan_to_num(draws[key]["irr"].to_numpy(), nan=-1) < config.HURDLE_IRR)
        ax.set_title(f"{PROJECT_LABEL[key]}: P(IRR < 8%) = {p:.1%}", loc="left", color=INK, fontsize=8.5)
        ax.tick_params(axis="y", labelsize=7)
        ax.set_xlabel("Project IRR (%)")
        ax.set_ylabel("Number of draws")
    fig.tight_layout()
    _save(fig, "fig4_montecarlo")


def fig5_thresholds(breakeven, oos):
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    keys = list(PROJECT_LABEL)
    y = np.arange(len(keys))[::-1]
    for yi, key in zip(y, keys):
        b = breakeven[(breakeven.country == key[0]) & (breakeven.ptype == key[1])].breakeven_reserve_revenue.iloc[0]
        o = oos[(oos.country == key[0]) & (oos.ptype == key[1])].reserve_index.iloc[0]
        ax.plot([0, 1.5], [yi, yi], color="#e4e3df", lw=0.8, zorder=0)
        ax.plot([b * 100, o * 100], [yi, yi], color=MUTED, lw=1.2)
        ax.scatter(b * 100, yi, s=55, color=ORANGE, zorder=3, edgecolor="white", linewidth=1.5,
                   label="Break-even level (IRR = 8%)" if yi == y[0] else None)
        ax.scatter(o * 100, yi, s=55, color=BLUE, zorder=3, edgecolor="white", linewidth=1.5,
                   label="Observed 2025 level" if yi == y[0] else None)
    ax.axvline(100, color=INK, lw=0.8, ls=":")
    ax.set_yticks(y, [PROJECT_LABEL[k] for k in keys])
    ax.set_xlabel("Reserve revenue as % of 2024 level (2024 euros)")
    ax.set_xlim(0, 150)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2, fontsize=7.5)
    _save(fig, "fig5_thresholds")
