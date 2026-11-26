-- One row per BirdNET detection (recording, 3-second segment, species), with
-- the period of the day and two flags set by the detection_thresholds seed.
-- BirdNET scores are not probabilities (docs/detections_schema.md); agreement
-- with published labels: docs/validation.md.
with detections as (

    select * from {{ source('raw', 'bird_detections') }}

),

periods as (

    select * from {{ ref('day_periods') }}

),

thresholds as (

    select * from {{ ref('detection_thresholds') }}

)

select
    detections.sha256                                   as recording_id,
    detections.site_code,
    detections.recorded_at                              as recorded_at_local,
    periods.period,
    periods.period_order,
    detections.start_s::double precision                as start_s,
    detections.end_s::double precision                  as end_s,
    detections.scientific_name,
    detections.common_name,
    detections.confidence::double precision             as confidence,
    detections.geo_score::double precision              as geo_score,
    {% for flag, measure in [
        ("is_confident", "confidence"),
        ("is_expected_here", "geo_score"),
    ] %}
    coalesce(detections.{{ measure }} >= (
        select threshold from thresholds where flag = '{{ flag }}'
    ), false)                                           as {{ flag }},
    {% endfor %}
    detections.detected_at
from detections
inner join periods
    on extract(hour from detections.recorded_at)::int = periods.hour_of_day
