"""Extract audio features from the recordings registered in raw.recordings.

Usage:
    uv run python -m soundscape.features

Each recording is read from S3 into memory and summarised as one row of
numbers: MFCC (mean and std per coefficient), spectral centroid and
bandwidth, RMS energy, zero-crossing rate, duration, and standard
ecoacoustic indices from scikit-maad (ACI, ADI, AEI, BI, NDSI, entropies,
background noise and signal-to-noise ratio). A damaged or empty file is
reported as failed instead of stopping the batch.

Results are written to S3 as Parquet (schema: docs/features_schema.md):
    features/site=<site>/month=<YYYY-MM>/features.parquet
    features_failed/failed.parquet
The run is incremental: only recordings without up-to-date features are
analyzed, and only the partitions they belong to are rewritten, keeping the
rows already there. Re-running with nothing new does no work.

Recordings are analyzed in parallel (FEATURES_WORKERS processes) and written
every CHUNK_SIZE recordings, so a run that stops halfway keeps what it did and
the next one carries on from there.
"""

import io
import logging
import multiprocessing
import sys
import warnings
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import repeat

import librosa
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import soundfile as sf
from maad import features as maad_features
from maad import sound as maad_sound
from psycopg.rows import dict_row
from pydantic import ValidationError

from soundscape.config import Settings
from soundscape.storage import pg_connect, s3_client

log = logging.getLogger("soundscape.features")

# Raise it whenever the calculation changes: every recording is then redone
FEATURES_VERSION = 3  # 2: ecoacoustic indices; 3: quality measures
CHUNK_SIZE = 250  # recordings analyzed between two writes to S3

# Ecoacoustic indices: scikit-maad defaults, with a fixed spectrogram and the
# high band capped at 16 kHz, half the sample rate (docs/features_schema.md)
SPECTROGRAM = {"mode": "amplitude", "nperseg": 1024, "noverlap": 512}
BANDS_HZ = {"flim_low": [0, 1000], "flim_mid": [1000, 10000], "flim_hi": [10000, 16000]}
# Quality measures (docs/features_schema.md): rain is loudest and steadiest in
# 600-1200 Hz (Bedoya et al. 2017); wind concentrates energy below ~200 Hz
RAIN_BAND_HZ = (600, 1200)
WIND_BELOW_HZ = 200
CLIPPING_LEVEL = 0.999  # share of full scale counted as clipped

# Our column name -> scikit-maad's
TEMPORAL_INDICES = {"ht": "Ht", "bgnt_db": "BGNt", "snrt_db": "SNRt"}
SPECTRAL_INDICES = {
    "aci": "ACI",
    "adi": "ADI",
    "aei": "AEI",
    "bi": "BI",
    "ndsi": "NDSI",
    "hf": "Hf",
}

# Fixed schema: n_mfcc changes the length of the lists, not the columns
FEATURES_SCHEMA = pa.schema(
    [
        ("sha256", pa.string()),
        ("file_name", pa.string()),
        ("site_code", pa.string()),
        # Parquet has no seconds unit: "s" would be read back as "ms"
        ("recorded_at", pa.timestamp("ms")),
        ("duration_s", pa.float32()),
        ("mfcc_mean", pa.list_(pa.float32())),
        ("mfcc_std", pa.list_(pa.float32())),
        ("spectral_centroid_hz", pa.float32()),
        ("spectral_bandwidth_hz", pa.float32()),
        ("rms_mean", pa.float32()),
        ("zcr_mean", pa.float32()),
        # Ecoacoustic indices; null when they cannot be computed (pure silence)
        ("aci", pa.float32()),
        ("adi", pa.float32()),
        ("aei", pa.float32()),
        ("bi", pa.float32()),
        ("ndsi", pa.float32()),
        ("ht", pa.float32()),
        ("hf", pa.float32()),
        ("bgnt_db", pa.float32()),
        ("snrt_db", pa.float32()),
        # Quality measures; flags and thresholds are applied in dbt
        ("clipping_fraction", pa.float32()),
        ("longest_zero_run_s", pa.float32()),
        ("low_freq_energy_ratio", pa.float32()),
        ("rain_band_psd_db", pa.float32()),
        ("rain_band_snr", pa.float32()),
        ("sample_rate_hz", pa.int32()),
        ("n_mfcc", pa.int16()),
        ("features_version", pa.int16()),
        ("extracted_at", pa.timestamp("us", tz="UTC")),
    ]
)

FAILED_SCHEMA = pa.schema(
    [
        ("sha256", pa.string()),
        ("file_name", pa.string()),
        ("s3_key", pa.string()),
        ("error", pa.string()),
        ("extracted_at", pa.timestamp("us", tz="UTC")),
    ]
)

FAILED_KEY = "features_failed/failed.parquet"


@dataclass
class FeatureResult:
    """Outcome for one recording: its features, or why they could not be computed."""

    status: str  # "ok" or "failed"
    features: dict = field(default_factory=dict)
    error: str | None = None


def acoustic_indices(audio: np.ndarray, sample_rate: int) -> dict:
    """Ecoacoustic indices with scikit-maad; all null for pure digital silence.

    Silence makes several indices undefined (NaN) and others meaningless, so
    nothing is reported rather than misleading numbers.
    """
    names = [*TEMPORAL_INDICES, *SPECTRAL_INDICES]
    if not np.any(audio):
        return dict.fromkeys(names)

    with warnings.catch_warnings():
        # scikit-maad warns on log(0) in near-silent frames; NaNs are handled below
        warnings.simplefilter("ignore")
        temporal = maad_features.all_temporal_alpha_indices(audio, sample_rate)
        sxx, tn, fn, _ = maad_sound.spectrogram(audio, sample_rate, **SPECTROGRAM)
        spectral, _ = maad_features.all_spectral_alpha_indices(
            sxx**2, tn, fn, **BANDS_HZ
        )

    values = {
        ours: temporal[theirs].iloc[0] for ours, theirs in TEMPORAL_INDICES.items()
    }
    values |= {
        ours: spectral[theirs].iloc[0] for ours, theirs in SPECTRAL_INDICES.items()
    }
    return {name: float(v) if np.isfinite(v) else None for name, v in values.items()}


def longest_run_of_zeros(audio: np.ndarray) -> int:
    """Length, in samples, of the longest stretch of exact digital zeros."""
    is_zero = np.concatenate(([0], (audio == 0).astype(np.int8), [0]))
    edges = np.flatnonzero(np.diff(is_zero))
    return int((edges[1::2] - edges[::2]).max()) if edges.size else 0


def quality_measures(audio: np.ndarray, sample_rate: int) -> dict:
    """Numbers that help spot clipping, dropouts, wind and rain.

    They are measures only: dbt turns them into flags with thresholds kept in a
    seed, so a threshold can change without recomputing the audio.
    """
    power = np.abs(librosa.stft(audio, n_fft=2048, hop_length=512)) ** 2
    freqs = librosa.fft_frequencies(sr=sample_rate, n_fft=2048)
    total = power.sum()

    in_band = (freqs >= RAIN_BAND_HZ[0]) & (freqs <= RAIN_BAND_HZ[1])
    band = power[in_band].mean(axis=0)  # mean power of the band, per frame
    band_mean = band.mean()
    return {
        "clipping_fraction": float(np.mean(np.abs(audio) >= CLIPPING_LEVEL)),
        "longest_zero_run_s": longest_run_of_zeros(audio) / sample_rate,
        "low_freq_energy_ratio": (
            float(power[freqs < WIND_BELOW_HZ].sum() / total) if total > 0 else None
        ),
        # Loud (high PSD) and steady (high mean/std over time) means rain-like
        "rain_band_psd_db": (
            float(10 * np.log10(band_mean)) if band_mean > 0 else None
        ),
        "rain_band_snr": (float(band_mean / band.std()) if band.std() > 0 else None),
    }


def extract_features(audio: np.ndarray, sample_rate: int, n_mfcc: int) -> dict:
    """Summarise a mono signal as a dict of features (one entry per column)."""
    mfcc = librosa.feature.mfcc(y=audio, sr=sample_rate, n_mfcc=n_mfcc)
    centroid = librosa.feature.spectral_centroid(y=audio, sr=sample_rate)
    bandwidth = librosa.feature.spectral_bandwidth(y=audio, sr=sample_rate)
    return {
        "duration_s": round(len(audio) / sample_rate, 3),
        # One value per coefficient, averaged over time
        "mfcc_mean": mfcc.mean(axis=1).tolist(),
        "mfcc_std": mfcc.std(axis=1).tolist(),
        "spectral_centroid_hz": float(centroid.mean()),
        "spectral_bandwidth_hz": float(bandwidth.mean()),
        "rms_mean": float(librosa.feature.rms(y=audio).mean()),
        "zcr_mean": float(librosa.feature.zero_crossing_rate(audio).mean()),
        **acoustic_indices(audio, sample_rate),
        **quality_measures(audio, sample_rate),
    }


def analyze(data: bytes, sample_rate: int, n_mfcc: int) -> FeatureResult:
    """Decode an audio file held in memory and extract its features."""
    try:
        # Resamples only if the file's rate differs from sample_rate
        audio, _ = librosa.load(io.BytesIO(data), sr=sample_rate, mono=True)
    except sf.LibsndfileError as error:
        message = f"cannot decode audio: {error.error_string}"
        return FeatureResult("failed", error=message)

    if audio.size == 0:
        # A valid file with no samples decodes without error, so check it here
        return FeatureResult("failed", error="audio has no samples")
    return FeatureResult("ok", extract_features(audio, sample_rate, n_mfcc))


def partition_key(site_code: str, recorded_at: datetime) -> str:
    """Hive-style partition by site and month (~87 rows each on the full data)."""
    return f"features/site={site_code}/month={recorded_at:%Y-%m}/features.parquet"


def is_up_to_date(row: dict | None, sample_rate: int, n_mfcc: int) -> bool:
    """Whether stored features were computed with the current settings and code."""
    return (
        row is not None
        and row["sample_rate_hz"] == sample_rate
        and row["n_mfcc"] == n_mfcc
        and row["features_version"] == FEATURES_VERSION
    )


def read_existing_rows(s3, bucket: str) -> dict[str, dict]:
    """Stored features by recording; files with an older schema count as absent."""
    rows = {}
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix="features/"
    )
    for page in pages:
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            table = pq.read_table(io.BytesIO(body))
            if table.schema.equals(FEATURES_SCHEMA, check_metadata=False):
                rows.update({row["sha256"]: row for row in table.to_pylist()})
    return rows


def build_tables(
    results: list[tuple[dict, FeatureResult]],
    sample_rate: int,
    n_mfcc: int,
    extracted_at: datetime,
    kept_rows: Iterable[dict] = (),
) -> tuple[dict[str, pa.Table], pa.Table]:
    """Group results into one table per partition, plus a table of failures.

    Only partitions with a new result are returned; kept_rows fills those
    partitions with the rows that did not need recomputing.
    """
    partitions = defaultdict(list)
    failed = []
    for recording, result in results:
        if result.status == "ok":
            row = {
                "sha256": recording["sha256"],
                "file_name": recording["file_name"],
                "site_code": recording["site_code"],
                "recorded_at": recording["recorded_at"],
                **result.features,
                "sample_rate_hz": sample_rate,
                "n_mfcc": n_mfcc,
                "features_version": FEATURES_VERSION,
                "extracted_at": extracted_at,
            }
            key = partition_key(recording["site_code"], recording["recorded_at"])
            partitions[key].append(row)
        else:
            failed.append(
                {
                    "sha256": recording["sha256"],
                    "file_name": recording["file_name"],
                    "s3_key": recording["s3_key"],
                    "error": result.error,
                    "extracted_at": extracted_at,
                }
            )

    for row in kept_rows:
        key = partition_key(row["site_code"], row["recorded_at"])
        if key in partitions:
            partitions[key].append(row)

    tables = {
        key: pa.Table.from_pylist(
            sorted(rows, key=lambda row: (row["recorded_at"], row["file_name"])),
            schema=FEATURES_SCHEMA,
        )
        for key, rows in partitions.items()
    }
    return tables, pa.Table.from_pylist(failed, schema=FAILED_SCHEMA)


@contextmanager
def parent_main_hidden():
    """Keep spawned workers from running the parent's main script again.

    spawn starts each worker by re-running the parent's __main__. Inside an
    Airflow task that is the `airflow` command, which cannot start there (a
    task has no access to Airflow's database) and kills every worker. The
    workers only need this module, which they import by name, so while the
    pool runs __main__ shows neither its file nor its module name.
    """
    main = sys.modules["__main__"]
    missing = object()
    file = main.__dict__.pop("__file__", missing)
    spec = getattr(main, "__spec__", None)
    main.__spec__ = None
    try:
        yield
    finally:
        main.__spec__ = spec
        if file is not missing:
            main.__file__ = file


def put_parquet(s3, bucket: str, key: str, table: pa.Table) -> None:
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    s3.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())


def run(settings: Settings) -> list[tuple[dict, FeatureResult]]:
    """Analyze the recordings without up-to-date features; write them to S3."""
    s3 = s3_client(settings)

    # raw.recordings is the catalog: only ingested files are processed (lineage)
    with pg_connect(settings, row_factory=dict_row) as conn:
        recordings = conn.execute(
            """
            SELECT sha256, file_name, site_code, recorded_at, s3_key
            FROM raw.recordings
            ORDER BY recorded_at, file_name
            """
        ).fetchall()

    sample_rate = settings.features_sample_rate
    n_mfcc = settings.features_n_mfcc
    existing = read_existing_rows(s3, settings.s3_bucket)
    pending, kept_rows = [], []
    for recording in recordings:
        row = existing.get(recording["sha256"])
        if is_up_to_date(row, sample_rate, n_mfcc):
            kept_rows.append(row)
        else:
            pending.append(recording)
    log.info("Up to date: %d; to analyze: %d", len(kept_rows), len(pending))

    # By partition, so each chunk rewrites few files
    pending.sort(key=lambda r: (r["site_code"], r["recorded_at"], r["file_name"]))
    kept = {row["sha256"]: row for row in kept_rows}
    workers = min(settings.features_workers, max(1, len(pending)))
    # spawn: the same on macOS and Linux; parent_main_hidden makes it work
    # inside an Airflow task
    pool = (
        ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn"))
        if workers > 1
        else nullcontext()
    )
    results, failures = [], []
    with parent_main_hidden(), pool:
        mapper = pool.map if workers > 1 else map
        for start in range(0, len(pending), CHUNK_SIZE):
            chunk = pending[start : start + CHUNK_SIZE]
            bodies = [
                s3.get_object(Bucket=settings.s3_bucket, Key=r["s3_key"])["Body"].read()
                for r in chunk
            ]
            chunk_results = list(
                zip(
                    chunk,
                    mapper(analyze, bodies, repeat(sample_rate), repeat(n_mfcc)),
                    strict=True,
                )
            )
            for recording, result in chunk_results:
                if result.status != "ok":
                    log.warning("Failed %s: %s", recording["file_name"], result.error)
            tables, failed = build_tables(
                chunk_results,
                sample_rate,
                n_mfcc,
                extracted_at=datetime.now(UTC),
                kept_rows=kept.values(),
            )
            for key, table in tables.items():
                put_parquet(s3, settings.s3_bucket, key, table)
                kept.update({row["sha256"]: row for row in table.to_pylist()})
            failures += failed.to_pylist()
            put_parquet(
                s3,
                settings.s3_bucket,
                FAILED_KEY,
                pa.Table.from_pylist(failures, schema=FAILED_SCHEMA),
            )
            results += chunk_results
            log.info(
                "Analyzed %d of %d recordings (%d partitions written)",
                start + len(chunk),
                len(pending),
                len(tables),
            )
    if not pending:
        # Always written, even empty, so the latest run's failures are what it shows
        put_parquet(
            s3,
            settings.s3_bucket,
            FAILED_KEY,
            pa.Table.from_pylist([], schema=FAILED_SCHEMA),
        )
    return results


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # boto3 is chatty at INFO level
    logging.getLogger("botocore").setLevel(logging.WARNING)

    try:
        settings = Settings()
    except ValidationError as error:
        # Report which settings are wrong without echoing their values (secrets)
        for problem in error.errors(include_input=False, include_url=False):
            field_name = ".".join(str(part) for part in problem["loc"])
            log.error("Invalid configuration for %s: %s", field_name, problem["msg"])
        raise SystemExit(1) from None

    results = run(settings)
    ok = sum(result.status == "ok" for _, result in results)
    log.info("Summary: ok=%d failed=%d", ok, len(results) - ok)


if __name__ == "__main__":
    main()
