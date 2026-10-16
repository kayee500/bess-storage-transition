"""Download hourly day-ahead prices (DE-LU and SE3, 2019-2025) from the Energy-Charts API.

    python download_day_ahead.py

Files are saved as data/raw/energy_charts/price_<zone>_<year>.json.
"""
import json
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "raw" / "energy_charts"
OUT.mkdir(parents=True, exist_ok=True)
for zone in ("DE-LU", "SE3"):
    for year in range(2019, 2026):
        url = f"https://api.energy-charts.info/price?bzn={zone}&start={year}-01-01&end={year}-12-31"
        with urllib.request.urlopen(url, timeout=120) as r:
            data = json.loads(r.read())
        (OUT / f"price_{zone}_{year}.json").write_text(json.dumps(data))
        print(zone, year, len(data["price"]), "values")
