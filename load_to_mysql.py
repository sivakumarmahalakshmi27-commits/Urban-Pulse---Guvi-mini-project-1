
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/clean/nyc311_clean.csv"
SCHEMA_PATH = Path(__file__).parent / "sql" / "01_schema.sql"
DB_NAME = "urban_pulse_db"
BATCH_SIZE = 5000

user = os.getenv("MYSQL_USER", "root")
password = os.getenv("MYSQL_PASSWORD", "")
host = os.getenv("MYSQL_HOST", "localhost")
port = os.getenv("MYSQL_PORT", "3306")

DATE_COLS = ["created_date", "closed_date", "due_date", "resolution_action_updated_date"]
FLAG_COLS = ["zip_invalid_flag", "coord_missing_flag", "coord_out_of_nyc_flag", "is_closed",
             "closed_before_created_flag", "future_date_flag", "status_closed_mismatch_flag",
             "action_before_created_flag", "resolution_outlier_flag"]


def run_schema(server_engine):
    """Run 01_schema.sql statement by statement."""
    sql = SCHEMA_PATH.read_text()
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with server_engine.begin() as conn:
        for stmt in statements:
            lines = [ln for ln in stmt.splitlines() if not ln.strip().startswith("--")]
            stmt = "\n".join(lines).strip()
            if stmt:
                conn.execute(text(stmt))


def main():
    # 1. Read the cleaned CSV
    print(f"Reading {CSV_PATH} ...")
    df = pd.read_csv(CSV_PATH, dtype={"unique_key": str, "incident_zip": str}, low_memory=False)
    for c in DATE_COLS:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in FLAG_COLS:
        if c in df.columns:
            df[c] = df[c].map({True: 1, False: 0, "True": 1, "False": 0, 1: 1, 0: 0})
    df["created_date_only"] = pd.to_datetime(df["created_date_only"], errors="coerce").dt.date
    df = df.astype(object).where(df.notna(), None)   # NaN/NaT -> NULL
    source_rows = len(df)
    print("Rows in CSV:", source_rows)

    # 2. Create schema and staging table
    server_engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/")
    run_schema(server_engine)
    engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{DB_NAME}")

    # 3. Load in batches
    for start in range(0, source_rows, BATCH_SIZE):
        chunk = df.iloc[start:start + BATCH_SIZE]
        chunk.to_sql("service_requests_staging", engine, if_exists="append",
                     index=False, method="multi", chunksize=500)
        print(f"  loaded {min(start + BATCH_SIZE, source_rows)} / {source_rows}")

    # 4. Validate before publishing
    with engine.connect() as conn:
        staged = conn.execute(text("SELECT COUNT(*) FROM service_requests_staging")).scalar()
        distinct_keys = conn.execute(text("SELECT COUNT(DISTINCT unique_key) FROM service_requests_staging")).scalar()
    print(f"Validation: CSV={source_rows} | staging={staged} | distinct keys={distinct_keys}")
    if staged != source_rows or distinct_keys != source_rows:
        raise SystemExit("Validation FAILED - staging table not published. Check the load.")

    # 5. Publish (swap staging in as the live table)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS service_requests"))
        conn.execute(text("RENAME TABLE service_requests_staging TO service_requests"))
    print("Published: urban_pulse_db.service_requests")


if __name__ == "__main__":
    main()
