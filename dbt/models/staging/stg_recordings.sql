-- One row per recording: catalog fields, with clear names and types.
select
    sha256                         as recording_id,
    file_name,
    site_code,
    -- Assumes file names use Colombian local time (UTC-5, no daylight saving)
    recorded_at                    as recorded_at_local,
    recorded_at::date              as recorded_date,
    extract(hour from recorded_at)::int as recorded_hour,
    duration_s::double precision   as duration_s,
    sample_rate_hz,
    channels,
    size_bytes,
    s3_key,
    source,
    ingested_at
from {{ source('raw', 'recordings') }}
