-- One row per site and period of the day (dawn, day, dusk, night):
-- how loud, how bright and how variable the soundscape is, and how each
-- period compares with the rest of the day at the same site.
with recordings as (

    select * from {{ ref('stg_audio_features') }}

),

by_period as (

    select
        site_code,
        period,
        period_order,
        count(*)                       as n_recordings,
        avg(rms_dbfs)                  as avg_rms_dbfs,
        stddev_samp(rms_dbfs)          as stddev_rms_dbfs,
        avg(spectral_centroid_hz)      as avg_spectral_centroid_hz,
        stddev_samp(spectral_centroid_hz) as stddev_spectral_centroid_hz,
        avg(spectral_bandwidth_hz)     as avg_spectral_bandwidth_hz,
        avg(zero_crossing_rate)        as avg_zero_crossing_rate
    from recordings
    group by site_code, period, period_order

)

select
    site_code,
    period,
    period_order,
    n_recordings,
    avg_rms_dbfs,
    stddev_rms_dbfs,
    avg_spectral_centroid_hz,
    stddev_spectral_centroid_hz,
    avg_spectral_bandwidth_hz,
    avg_zero_crossing_rate,

    -- Window functions: compare each period with the other periods of its site.
    -- Site average weighted by recordings, so it equals the average over all of them
    avg_rms_dbfs
        - sum(avg_rms_dbfs * n_recordings) over site / sum(n_recordings) over site
                                                   as rms_dbfs_vs_site_avg,
    rank() over (partition by site_code order by avg_rms_dbfs desc)
                                                   as loudness_rank_in_site,
    -- Change from the previous period of the day (dawn has none: it comes first)
    avg_rms_dbfs - lag(avg_rms_dbfs) over site_by_order
                                                   as rms_dbfs_change_vs_previous,
    avg_spectral_centroid_hz - lag(avg_spectral_centroid_hz) over site_by_order
                                                   as centroid_hz_change_vs_previous
from by_period
window
    site as (partition by site_code),
    site_by_order as (partition by site_code order by period_order)
