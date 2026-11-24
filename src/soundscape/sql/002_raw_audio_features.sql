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
    -- Ecoacoustic indices (scikit-maad); null when they cannot be computed
    aci                    real,
    adi                    real,
    aei                    real,
    bi                     real,
    ndsi                   real,
    ht                     real,
    hf                     real,
    bgnt_db                real,
    snrt_db                real,
    sample_rate_hz         integer      NOT NULL,
    n_mfcc                 smallint     NOT NULL,
    features_version       smallint     NOT NULL,  -- version of the calculation
    extracted_at           timestamptz  NOT NULL,  -- when the features were computed
    loaded_at              timestamptz  NOT NULL DEFAULT now()  -- when this row was last written
);

-- Queries filter by site and by time range (period of day, month...)
CREATE INDEX IF NOT EXISTS audio_features_site_recorded_at_idx
    ON raw.audio_features (site_code, recorded_at);

-- Tables created before this column existed; those rows are version 1
ALTER TABLE raw.audio_features
    ADD COLUMN IF NOT EXISTS features_version smallint NOT NULL DEFAULT 1;
ALTER TABLE raw.audio_features ALTER COLUMN features_version DROP DEFAULT;

-- Ecoacoustic indices, added in features version 2
ALTER TABLE raw.audio_features
    ADD COLUMN IF NOT EXISTS aci real,
    ADD COLUMN IF NOT EXISTS adi real,
    ADD COLUMN IF NOT EXISTS aei real,
    ADD COLUMN IF NOT EXISTS bi real,
    ADD COLUMN IF NOT EXISTS ndsi real,
    ADD COLUMN IF NOT EXISTS ht real,
    ADD COLUMN IF NOT EXISTS hf real,
    ADD COLUMN IF NOT EXISTS bgnt_db real,
    ADD COLUMN IF NOT EXISTS snrt_db real;
