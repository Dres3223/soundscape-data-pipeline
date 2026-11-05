-- One row per recording: audio features with clear names and types,
-- plus the ecological period of the day the recording belongs to.
with features as (

    select * from {{ source('raw', 'audio_features') }}

),

periods as (

    select * from {{ ref('day_periods') }}

)

select
    features.sha256                                  as recording_id,
    features.site_code,
    features.recorded_at                             as recorded_at_local,
    features.recorded_at::date                       as recorded_date,
    extract(hour from features.recorded_at)::int     as recorded_hour,
    periods.period,
    periods.period_order,
    features.duration_s::double precision            as duration_s,
    features.spectral_centroid_hz::double precision  as spectral_centroid_hz,
    features.spectral_bandwidth_hz::double precision as spectral_bandwidth_hz,
    features.rms_mean::double precision              as rms,
    -- Loudness in decibels relative to full scale: easier to compare than raw RMS
    20 * log(greatest(features.rms_mean, 1e-10)::numeric)::double precision as rms_dbfs,
    features.zcr_mean::double precision              as zero_crossing_rate,
    features.mfcc_mean,
    features.mfcc_std,
    features.n_mfcc,
    features.sample_rate_hz,
    features.extracted_at
from features
inner join periods
    on extract(hour from features.recorded_at)::int = periods.hour_of_day
