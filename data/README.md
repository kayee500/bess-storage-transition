# Data

The raw market data are public but are not redistributed in this repository. Download them
into the three folders below. The loaders recognise files by their content, so file names
only matter where stated.

## 1. Day-ahead prices: `data/raw/energy_charts/`

Run `python download_day_ahead.py`. It saves `price_DE-LU_<year>.json` and
`price_SE3_<year>.json` for 2019 to 2025 from the Energy-Charts API (Fraunhofer ISE).
German prices are published under CC BY 4.0 (Bundesnetzagentur | SMARD.de). From
1 October 2025 the API returns 15-minute prices; the code averages them to hourly values.

## 2. German FCR and aFRR: `data/raw/regelleistung/`

<https://www.regelleistung.net/apps/datacenter/tendering-files/>

Filter: product type **FCR** and **aFRR**, market **Capacity**, file type **Results**,
delivery period 2019-01 to 2025-12. Download the yearly files

- `RESULT_OVERVIEW_CAPACITY_MARKET_FCR_<year>-01-01_<year>-12-31.xlsx`
- `RESULT_OVERVIEW_CAPACITY_MARKET_aFRR_<year>-01-01_<year>-12-31.xlsx`

for 2019 to 2025 and keep the original names. If a yearly file is unavailable, the twelve
monthly files for that year can be used instead. German FCR results start on 1 July 2019.

## 3. Swedish FCR and aFRR: `data/raw/svk_mimer/`

Svenska kraftnät, Mimer. Set the period, then "Spara som CSV".

| Product | Period | Page |
|---|---|---|
| FCR | 2019 to 2020 | <https://mimer.svk.se/Primaryregulation/HistoryIndex> |
| FCR | 2021 to January 2024 | <https://mimer.svk.se/Primaryregulation/HistoryIndex2023> |
| FCR | February 2024 to 2025 | <https://mimer.svk.se/PrimaryRegulation/NavigateBySortOrder?parentSortOrder=2&itemSortOrder=3> |
| aFRR | 2020 to 10 May 2022 (national) | <https://mimer.svk.se/AutomaticFrequencyRestorationReserve/HistoryIndex> |
| aFRR | 11 May 2022 to 2025 (by area; SE3 = SN3) | <https://mimer.svk.se/AutomaticFrequencyRestorationReserve/NavigateBySortOrder?parentSortOrder=2&itemSortOrder=4> |

Swedish aFRR prices on Mimer start in January 2020.

## Checks

`run_all.py` writes `results/coverage_DE.csv` and `results/coverage_SE.csv` (share of hours
with a price for each product and year). Every product is complete for 2020 to 2025, except
Swedish FCR-D down, which was not procured in 2020 and 2021, and German FCR on 3 October 2021,
when the main auction has no settlement price (FCR is treated as unavailable that day).
