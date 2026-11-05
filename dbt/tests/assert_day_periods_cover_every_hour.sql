-- Singular test: returns rows (and so fails) unless the seed has exactly
-- the 24 hours. With a missing hour, the INNER JOIN in stg_audio_features
-- would silently drop every recording made at that hour.
select count(*) as hours
from {{ ref('day_periods') }}
having count(*) <> 24
