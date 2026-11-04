# Urban Pulse NYC - Citizen Complaint Intelligence & Resolution Analytics

An end-to-end analytics project on NYC 311 service requests: extract data from the NYC Open Data API, clean and document it, store it in MySQL, answer 15 analyst questions in SQL and Python, and publish the results in an interactive Streamlit dashboard with five KPIs.

- **Data source:** NYC Open Data - 311 Service Requests from 2020 to Present (dataset `erm2-nwe9`)
- **Data used:** a systematic ~3% sample (request IDs ending in 07, 37 or 67), October 2025 to September 2026, **118,866 requests**, extracted on 30 October 2026
- **Because it is a ~3% sample, trends and proportions are meaningful; absolute volumes are not.**

## Pipeline

NYC Open Data API -> Python extraction (monthly requests) -> raw snapshot -> cleaning and derived fields -> descriptive statistics and outlier review -> MySQL staging, validation and publish -> SQL and Python analyst tasks -> Streamlit analyst pages -> five-KPI dashboard -> findings and limitations

## Folder structure

```
urban_pulse/
  README.md
  requirements.txt
  app.py                                                 Streamlit dashboard (single file)
  load_to_mysql.py                                       loads the cleaned CSV into MySQL (staging -> validate -> publish)
  validate_load.py                                       row-count and flag checks, writes logs/validation_log.csv
  Urban_Pulse_Tasks_01_06.ipynb                          analyst tasks 1-6 (volume and demand)
  Urban_Pulse_Tasks_07_11.ipynb                          analyst tasks 7-11 (status, resolution time, outliers)
  Urban_Pulse_Tasks_12_15.ipynb                          analyst tasks 12-15 (distribution, geography, closure, volume vs delay)
  cleaning_log.csv                                       cleaning steps and counts
  colab/
    Project_Data_Extraction.ipynb                        data extraction (Google Colab)
    Project_Data_cleaning.ipynb                          cleaning, derived fields and statistics (Google Colab)
  data/
    raw/nyc311_raw.csv                                   raw extract (118,866 rows x 23 columns)
    clean/nyc311_clean.csv                               cleaned dataset (118,866 rows x 39 columns)
  sql/
    01_schema.sql                                        database and table definition
  docs/
    data_dictionary.csv                                   39 fields: meaning, transformation, analytical use
    extraction_log.md                                     how the raw data was extracted
    Urban_pulse_Findings_and_Interpretation.docx          findings for the 15 tasks and limitations
    screenshots/                                          dashboard and validation evidence
  figures/                                                charts saved by the task notebooks
  logs/validation_log.csv                                 three-way row-count and flag validation (all PASS)
```

## Setup

1. Install Python (Anaconda is used in this project) and the packages in `requirements.txt`:
   ```
   pip install -r requirements.txt
   ```
2. Install and start MySQL. This project used XAMPP, whose MySQL service is MariaDB 10.11 (the SQL runs through the MySQL-compatible PyMySQL driver). Start the MySQL module in the XAMPP Control Panel.
3. Database settings are read from environment variables, so no password is stored in the code. If none are set, these defaults are used:

   | Variable | Default |
   |---|---|
   | `MYSQL_USER` | `root` |
   | `MYSQL_PASSWORD` | (empty) |
   | `MYSQL_HOST` | `localhost` |
   | `MYSQL_PORT` | `3306` |

## Run order

Open a terminal in the project folder (`urban_pulse`) for every step below.

1. **Extract and clean (Google Colab).** Run `colab/Project.ipynb` (final extraction cell: "New 3rd code for extraction - monthly trend"), then `colab/Project_Data_cleaning.ipynb`. They produce `nyc311_raw.csv` and `nyc311_clean.csv`. Place them in `data/raw/` and `data/clean/`. (The finished files are already included.)
2. **Load into MySQL.**
   ```
   python load_to_mysql.py data/clean/nyc311_clean.csv
   ```
   This creates `urban_pulse_db`, loads the data in batches into a staging table, checks the row and distinct-key counts, and only then publishes it as `service_requests`. It is safe to re-run.
3. **Validate the load.**
   ```
   python validate_load.py data/clean/nyc311_clean.csv 118866
   ```
   This compares raw, cleaned and MySQL counts and flag totals, and writes `logs/validation_log.csv`.
4. **Analyst tasks.** Open JupyterLab in the project folder and run the three `Urban_Pulse_Tasks_*.ipynb` notebooks. The same queries are saved in `sql/`.
5. **Dashboard.**
   ```
   streamlit run app.py
   ```
   It opens at `http://localhost:8501`. Stop it with Ctrl+C.

## The dashboard

- **Filters (sidebar):** created-date range, borough, complaint type. Leaving a multi-select empty means "all". Filters apply to every page.
- **Pages:** Overview and KPIs; Volume and mix (Tasks 1-4); Time patterns (5-6); Status and closure (7, 14); Resolution time (8-10, 12); Outliers (11); Geography (13); Volume vs delay (15).
- **Each analyst page shows:** the question, sample size, chart or table, observed pattern and a cautious interpretation.
- **Safety and robustness:** user-selected filters are passed to MySQL as query parameters (never pasted into the SQL text); readable messages appear for an empty result and for a database connection error.

### The five KPIs

| KPI | Definition |
|---|---|
| Total requests | Distinct request identifiers in the filtered data |
| Recorded closure | Share of filtered rows marked closed (a closed date is recorded) |
| Open requests | Filtered rows not marked closed |
| Median resolution | Median valid resolution duration, in hours |
| Over 72 hours | Share of valid durations above the project's illustrative 72-hour threshold |

## Key data-preparation decisions

- Quality problems are **flagged, not deleted**: 27 rows closed before created, 2,429 missing coordinates, 482 rows with a closed date but a status other than "Closed", 1,781 rows whose action date precedes creation. `resolution_hours` is left blank where the dates are impossible.
- **Valid resolution durations:** 114,660 of 118,866 rows.
- **Outliers** use the IQR rule (upper fence 191.99 hours) and are flagged for investigation, never removed: 17,869 rows (15.6% of valid durations).
- Median is reported alongside the mean because resolution times are very right-skewed (skewness 6.40).
- Group medians and rates are only compared where a group has at least 100 valid values.
- Full field descriptions are in `docs/data_dictionary.csv`; every cleaning step and count is in `cleaning_log.csv`.

## Limitations

- 311 records are reported requests, not the full prevalence of urban problems.
- The data is a ~3% sample of one 12-month window and reflects the extraction date; results would change with a different date or sample.
- Missing or inconsistent dates and coordinates limit some analyses (2,429 requests have no coordinates).
- Agency and category comparisons can reflect different case complexity and operational definitions, not performance.
- Recorded closure is based on a closed date. It does not show satisfaction, quality or verified resolution, and the most recent months have had less time to close.
- The 72-hour threshold is a project-defined cut-off, not an official service standard.
- Borough and ZIP counts are raw counts, not per-capita.

## Project information

Project created for the GUVI-HCL data science programme (project: Urban Pulse). See `docs/findings_summary.md` for the findings of all 15 analyst investigations.
