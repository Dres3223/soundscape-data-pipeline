-- Raw layer: audio features loaded from features/*.parquet, one row per recording.
-- Columns mirror FEATURES_SCHEMA (docs/features_schema.md); dbt builds on top.
-- Requires raw.recordings (001), created by the ingestion.

CREATE TABLE IF NOT EXISTS raw.audio_features (
    -- Lineage: features can only exist for a registered recording
    sha256                 char(64)     PRIMARY KEY REFERENCES raw.recordings (sha256),
    file_name              text         NOT NULL,
    site_code              text         NOT NULL,
    recorded_at            timestamp    NOT NULL,
    duration_s             real         NOT NULL,
    mfcc_mean              real[]       NOT NULL,  -- n_mfcc values; mfcc_mean[1] is the first
    mfcc_std               real[]       NOT NULL,
    spectral_centroid_hz   real         NOT NULL,
    spectral_bandwidth_hz  real         NOT NULL,
    rms_mean               real         NOT NULL,
    zcr_mean               real         NOT NULL,
    sample_rate_hz         integer      NOT NULL,
    n_mfcc                 smallint     NOT NULL,
    extracted_at           timestamptz  NOT NULL,  -- when the features were computed
    loaded_at              timestamptz  NOT NULL DEFAULT now()  -- when this row was last written
);

-- Queries filter by site and by time range (period of day, month...)
CREATE INDEX IF NOT EXISTS audio_features_site_recorded_at_idx
    ON raw.audio_features (site_code, recorded_at);
