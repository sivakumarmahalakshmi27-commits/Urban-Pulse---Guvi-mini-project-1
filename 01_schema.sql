-- Urban Pulse NYC: schema for the cleaned NYC 311 table

CREATE DATABASE IF NOT EXISTS urban_pulse_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE urban_pulse_db;

DROP TABLE IF EXISTS service_requests_staging;

CREATE TABLE service_requests_staging (
  unique_key                      VARCHAR(20)  NOT NULL,
  created_date                    DATETIME     NOT NULL,
  closed_date                     DATETIME     NULL,
  agency                          VARCHAR(20)  NULL,
  agency_name                     VARCHAR(255) NULL,
  complaint_type                  VARCHAR(150) NULL,
  descriptor                      VARCHAR(255) NULL,
  location_type                   VARCHAR(255) NULL,
  incident_zip                    VARCHAR(10)  NULL,
  incident_address                VARCHAR(255) NULL,
  street_name                     VARCHAR(255) NULL,
  city                            VARCHAR(100) NULL,
  borough                         VARCHAR(30)  NULL,
  status                          VARCHAR(30)  NULL,
  resolution_description          TEXT         NULL,
  resolution_action_updated_date  DATETIME     NULL,
  community_board                 VARCHAR(60)  NULL,
  open_data_channel_type          VARCHAR(30)  NULL,
  park_borough                    VARCHAR(30)  NULL,
  latitude                        DOUBLE       NULL,
  longitude                       DOUBLE       NULL,
  facility_type                   VARCHAR(100) NULL,
  due_date                        DATETIME     NULL,
  zip_invalid_flag                TINYINT(1)   NULL,
  coord_missing_flag              TINYINT(1)   NULL,
  coord_out_of_nyc_flag           TINYINT(1)   NULL,
  is_closed                       TINYINT(1)   NOT NULL,
  closed_before_created_flag      TINYINT(1)   NULL,
  future_date_flag                TINYINT(1)   NULL,
  status_closed_mismatch_flag     TINYINT(1)   NULL,
  resolution_hours                DOUBLE       NULL,
  created_date_only               DATE         NULL,
  created_year                    SMALLINT     NULL,
  created_month                   TINYINT      NULL,
  created_ym                      CHAR(7)      NULL,
  created_weekday                 VARCHAR(12)  NULL,
  created_hour                    TINYINT      NULL,
  action_before_created_flag      TINYINT(1)   NULL,
  resolution_outlier_flag         TINYINT(1)   NULL,
  PRIMARY KEY (unique_key),
  KEY idx_created_date   (created_date),
  KEY idx_created_ym     (created_ym),
  KEY idx_borough        (borough),
  KEY idx_agency         (agency),
  KEY idx_complaint_type (complaint_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
