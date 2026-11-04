
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/clean/nyc311_clean.csv"
RAW_ROWS = int(sys.argv[2]) if len(sys.argv) > 2 else 118866   # from your extraction log
DB_NAME = "urban_pulse_db"

user = os.getenv("MYSQL_USER", "root")
password = os.getenv("MYSQL_PASSWORD", "")
host = os.getenv("MYSQL_HOST", "localhost")
port = os.getenv("MYSQL_PORT", "3306")

# ---- 1. Numbers computed from the cleaned CSV ----
df = pd.read_csv(CSV_PATH, dtype={"unique_key": str}, low_memory=False)


def flag_sum(col):
    """Count TRUE flags whether stored as True/False or 1/0."""
    if col not in df.columns:
        return None
    return int(df[col].map({True: 1, False: 0, "True": 1, "False": 0, 1: 1, 0: 0}).fillna(0).sum())


csv_vals = {
    "rows": len(df),
    "distinct_unique_key": df["unique_key"].nunique(),
    "closed_rows (is_closed=1)": int(df["is_closed"].sum()),
    "valid_resolution_hours": int(df["resolution_hours"].notna().sum()),
    "closed_before_created_flag": flag_sum("closed_before_created_flag"),
    "coord_missing_flag": flag_sum("coord_missing_flag"),
    "status_closed_mismatch_flag": flag_sum("status_closed_mismatch_flag"),
    "action_before_created_flag": flag_sum("action_before_created_flag"),
    "resolution_outlier_flag": flag_sum("resolution_outlier_flag"),
}

# ---- 2. Same numbers computed inside MySQL ----
engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{DB_NAME}")
sql = {
    "rows": "SELECT COUNT(*) FROM service_requests",
    "distinct_unique_key": "SELECT COUNT(DISTINCT unique_key) FROM service_requests",
    "closed_rows (is_closed=1)": "SELECT SUM(is_closed) FROM service_requests",
    "valid_resolution_hours": "SELECT COUNT(resolution_hours) FROM service_requests",
    "closed_before_created_flag": "SELECT SUM(closed_before_created_flag) FROM service_requests",
    "coord_missing_flag": "SELECT SUM(coord_missing_flag) FROM service_requests",
    "status_closed_mismatch_flag": "SELECT SUM(status_closed_mismatch_flag) FROM service_requests",
    "action_before_created_flag": "SELECT SUM(action_before_created_flag) FROM service_requests",
    "resolution_outlier_flag": "SELECT SUM(resolution_outlier_flag) FROM service_requests",
}
rows = []
with engine.connect() as conn:
    for name, q in sql.items():
        mysql_val = conn.execute(text(q)).scalar()
        mysql_val = None if mysql_val is None else int(mysql_val)
        csv_val = csv_vals[name]
        if csv_val is None:                      # column not in this CSV
            status = "SKIPPED (column not in CSV)"
        else:
            status = "PASS" if csv_val == mysql_val else "CHECK"
        rows.append({"check": name, "cleaned_csv": csv_val, "mysql": mysql_val, "status": status})
    dmin, dmax = conn.execute(text("SELECT MIN(created_date), MAX(created_date) FROM service_requests")).one()

# ---- 3. Three-way row count: raw -> cleaned -> MySQL ----
mysql_rows = rows[0]["mysql"]
all_equal = RAW_ROWS == csv_vals["rows"] == mysql_rows
three_way = {
    "check": "ROW COUNT raw vs cleaned vs MySQL",
    "raw_extract": RAW_ROWS, "cleaned_csv": csv_vals["rows"], "mysql": mysql_rows,
    "status": "PASS" if all_equal else "CHECK (expected if you are using a sample file)",
}
log = pd.DataFrame([three_way] + rows, columns=["check", "raw_extract", "cleaned_csv", "mysql", "status"])
log.loc[len(log)] = ["created_date range (min / max)", "", str(dmin), str(dmax), "INFO"]


def tidy(v):
    """Blank for missing, whole numbers without .0, everything else unchanged."""
    if v is None or (isinstance(v, float) and v != v):
        return ""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


for col in ["raw_extract", "cleaned_csv", "mysql"]:
    log[col] = log[col].astype(object).map(tidy)

print(log.to_string(index=False))
Path("logs").mkdir(exist_ok=True)
log.to_csv("logs/validation_log.csv", index=False)
print("\nSaved: logs/validation_log.csv  (screenshot this output as evidence)")
