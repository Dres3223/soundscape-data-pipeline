-- One row per site and period of the day (dawn, day, dusk, night):
-- how loud, how bright and how variable the soundscape is, and how each
-- period compares with the rest of the day at the same site.
-- Only recordings without quality flags are summarised; n_excluded counts
-- the others, which stay available in stg_audio_features.
with all_recordings as (

    select * from {{ ref('stg_audio_features') }}

),

recordings as (

    select * from all_recordings where is_usable

),

excluded as (

    select
        site_code,
        period,
        count(*) filter (where not is_usable) as n_excluded
    from all_recordings
    group by site_code, period

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
        avg(zero_crossing_rate)        as avg_zero_crossing_rate,
        -- Ecoacoustic indices (averages skip recordings where they are null)
        avg(aci)                       as avg_aci,
        avg(adi)                       as avg_adi,
        avg(aei)                       as avg_aei,
        avg(bi)                        as avg_bi,
        avg(ndsi)                      as avg_ndsi,
        avg(ht)                        as avg_ht,
        avg(hf)                        as avg_hf,
        avg(snrt_db)                   as avg_snrt_db
    from recordings
    group by site_code, period, period_order

)

select
    by_period.site_code,
    by_period.period,
    period_order,
    n_recordings,
    excluded.n_excluded,
    avg_rms_dbfs,
    stddev_rms_dbfs,
    avg_spectral_centroid_hz,
    stddev_spectral_centroid_hz,
    avg_spectral_bandwidth_hz,
    avg_zero_crossing_rate,
    avg_aci,
    avg_adi,
    avg_aei,
    avg_bi,
    avg_ndsi,
    avg_ht,
    avg_hf,
    avg_snrt_db,

    -- Window functions: compare each period with the other periods of its site.
    -- Site average weighted by recordings, so it equals the average over all of them
    avg_rms_dbfs
        - sum(avg_rms_dbfs * n_recordings) over site / sum(n_recordings) over site
                                                   as rms_dbfs_vs_site_avg,
    rank() over (partition by by_period.site_code order by avg_rms_dbfs desc)
                                                   as loudness_rank_in_site,
    -- Change from the previous period of the day (dawn has none: it comes first)
    avg_rms_dbfs - lag(avg_rms_dbfs) over site_by_order
                                                   as rms_dbfs_change_vs_previous,
    avg_spectral_centroid_hz - lag(avg_spectral_centroid_hz) over site_by_order
                                                   as centroid_hz_change_vs_previous
from by_period
inner join excluded
    on excluded.site_code = by_period.site_code
    and excluded.period = by_period.period
window
    site as (partition by by_period.site_code),
    site_by_order as (partition by by_period.site_code order by period_order)
