-- Raw layer: BirdNET results loaded from detections/*.parquet (soundscape.detections).
-- Requires raw.recordings (001), created by the ingestion.

-- One row per recording analyzed, with or without detections
CREATE TABLE IF NOT EXISTS raw.detection_recordings (
    sha256              char(64)     PRIMARY KEY REFERENCES raw.recordings (sha256),
    file_name           text         NOT NULL,
    site_code           text         NOT NULL,
    recorded_at         timestamp    NOT NULL,
    status              text         NOT NULL CHECK (status IN ('ok', 'failed')),
    error               text,
    n_detections        integer      NOT NULL,
    week                smallint     NOT NULL,  -- BirdNET week of the year, 1-48
    model_version       text         NOT NULL,
    min_confidence      real         NOT NULL,  -- lowest score stored
    detections_version  smallint     NOT NULL,
    detected_at         timestamptz  NOT NULL,
    loaded_at           timestamptz  NOT NULL DEFAULT now()
);

-- One row per recording, 3-second segment and species scored >= min_confidence
CREATE TABLE IF NOT EXISTS raw.bird_detections (
    sha256           char(64)     NOT NULL REFERENCES raw.detection_recordings (sha256)
                                  ON DELETE CASCADE,
    file_name        text         NOT NULL,
    site_code        text         NOT NULL,
    recorded_at      timestamp    NOT NULL,
    start_s          real         NOT NULL,
    end_s            real         NOT NULL,
    scientific_name  text         NOT NULL,
    common_name      text         NOT NULL,
    confidence       real         NOT NULL,
    geo_score        real,        -- geographic model score at the reserve that week
    detected_at      timestamptz  NOT NULL,
    PRIMARY KEY (sha256, start_s, scientific_name)
);

CREATE INDEX IF NOT EXISTS bird_detections_species_idx
    ON raw.bird_detections (scientific_name);
