-- One row per site, period of the day and species: in how many of the usable
-- recordings BirdNET detected the species. Only detections that pass both
-- flags of stg_bird_detections count, and only recordings without a quality
-- flag (stg_audio_features.is_usable). A naive detection rate: it does not
-- correct for missed or false detections. Precision 0.80-0.90 and recall 0.14
-- against published labels (docs/validation.md).
with analyzed as (

    select
        features.recording_id,
        features.site_code,
        features.period,
        features.period_order
    from {{ source('raw', 'detection_recordings') }} as analyzed_recordings
    inner join {{ ref('stg_audio_features') }} as features
        on features.recording_id = analyzed_recordings.sha256
    where analyzed_recordings.status = 'ok'
        and features.is_usable

),

totals as (

    select
        site_code,
        period,
        period_order,
        count(*) as n_recordings_analyzed
    from analyzed
    group by site_code, period, period_order

),

species_in_recording as (

    select
        recording_id,
        scientific_name,
        common_name,
        max(confidence) as max_confidence
    from {{ ref('stg_bird_detections') }}
    where is_confident and is_expected_here
    group by recording_id, scientific_name, common_name

)

select
    analyzed.site_code,
    analyzed.period,
    analyzed.period_order,
    species_in_recording.scientific_name,
    species_in_recording.common_name,
    count(*)                                         as n_recordings_detected,
    totals.n_recordings_analyzed,
    count(*)::double precision / totals.n_recordings_analyzed as detection_rate,
    max(species_in_recording.max_confidence)         as max_confidence
from species_in_recording
inner join analyzed
    on analyzed.recording_id = species_in_recording.recording_id
inner join totals
    on totals.site_code = analyzed.site_code
    and totals.period = analyzed.period
group by
    analyzed.site_code,
    analyzed.period,
    analyzed.period_order,
    species_in_recording.scientific_name,
    species_in_recording.common_name,
    totals.n_recordings_analyzed
