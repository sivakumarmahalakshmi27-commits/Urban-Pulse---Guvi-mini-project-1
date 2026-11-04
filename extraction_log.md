# Extraction Log - Urban Pulse NYC

This log records how the raw NYC 311 data was obtained, so the extraction can be understood and repeated.

## 1. Summary

| Item | Value |
|---|---|
| Extraction date | 30 October 2026 (morning) |
| Source | NYC Open Data - 311 Service Requests from 2020 to Present (dataset `erm2-nwe9`) |
| Endpoint | `https://data.cityofnewyork.us/resource/erm2-nwe9.json` (Socrata API, called with Python `requests`) |
| Extraction window | The last 12 full calendar months before the run date: October 2025 to September 2026 (`created_date` from 2025-10-01 to 2026-09-30) |
| Sampling method | Systematic sample of about 3%: only requests whose `unique_key` ends in 07, 37 or 67 (3 of every 100 identifiers). The same rule was applied to every month, with no per-month cap. |
| Fields requested | 23 |
| Rows extracted | **118,866** |
| Notebook | `Project.ipynb` (Google Colab). The final extraction is the cell headed "New 3rd code for extraction - monthly trend". |
| Raw snapshot | `nyc311_raw.csv` (saved in Colab as `nyc311_raw Final.csv` and renamed), kept separately from the cleaned file `data/clean/nyc311_clean.csv` |

## 2. Request design

- **One request per calendar month**, filtered with `$where` on `created_date` (start of month inclusive, start of next month exclusive) and on the `unique_key` suffix rule. This replaces offset-based pagination: each month is small enough to come back in a single response.
- **Ordering:** `created_date DESC`.
- **Row limit:** `$limit = 50000` per request. The code prints a warning if a month reaches this limit. No month did: monthly row counts are roughly 9,000 to 10,500, far below the limit, so no month is truncated.
- **Timeout and retries:** 120-second timeout; up to 3 attempts per month with waiting between attempts (5, 10 and 15 seconds).
- **Politeness:** a 1-second pause between monthly requests.
- **Error handling:** an HTTP 400 response stops the run and prints the API message so the query can be fixed.

## 3. Earlier attempts (not used in the analysis)

The same notebook also contains two earlier extraction attempts, kept for transparency:

1. A first test download of 100,000 rows with 10 fields.
2. A 23-field download of the most recent 100,000 records using offset pagination (batches of 10,000, a fixed cut-off date so new records could not shift the pages, ordering by `created_date` and `unique_key`).

Both pulled only the newest records, which cover a short recent period and do not support a month-by-month trend. They were replaced by the monthly sampling design in section 2. Only the final extraction produced the data analysed in this project.

## 4. Fields requested (23)

`unique_key`, `created_date`, `closed_date`, `due_date`, `agency`, `agency_name`, `complaint_type`, `descriptor`, `location_type`, `incident_zip`, `incident_address`, `street_name`, `city`, `borough`, `status`, `resolution_description`, `resolution_action_updated_date`, `community_board`, `open_data_channel_type`, `facility_type`, `park_borough`, `latitude`, `longitude`.

## 5. Outcome

- 118,866 rows x 23 columns in the raw extract.
- After cleaning, the file still has 118,866 rows (no duplicates found) and 39 columns (the 23 source columns plus 16 derived columns). See `cleaning_log.csv` and `docs/data_dictionary.csv`.
- Row counts were compared across raw, cleaned and MySQL data: 118,866 in each (`logs/validation_log.csv`).

## 6. Limitations of this extraction

- **A sample, not the full dataset.** Counts are about 3% of the true NYC totals, so trends and proportions are meaningful but absolute volumes are not.
- **The sampling rule assumes `unique_key` endings are unrelated to request characteristics.** This was not tested separately.
- **The dataset changes over time.** Results depend on the extraction date; running the notebook later gives a different 12-month window and slightly different records.
- **Recent requests may not be closed yet.** Closure information is as of the extraction date, so the latest months show lower recorded closure.
- **Field availability depends on the live API.** The selected-field list in the extraction notebook is the authoritative list for this run.

## 7. How to repeat the extraction

1. Open `Project.ipynb` in Google Colab and run the cell headed "New 3rd code for extraction - monthly trend" (the earlier cells are the superseded attempts).
2. The cell writes `nyc311_raw.csv` and `extraction_log.txt`.
3. Open `Project_Data_cleaning.ipynb` in Colab and run it from the top to produce `nyc311_clean.csv`, then load it into MySQL with `load_to_mysql.py` and check it with `validate_load.py`.
4. Note: the 12-month window is calculated from the day you run it, so running later gives a different window and slightly different records.
