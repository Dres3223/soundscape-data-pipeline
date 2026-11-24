import io

import numpy as np
import pytest
import soundfile as sf

from soundscape.features import analyze

SAMPLE_RATE = 32000


def tone(frequency_hz: float, seconds: float) -> np.ndarray:
    """A pure sine wave: its spectral centroid is known in advance."""
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (0.5 * np.sin(2 * np.pi * frequency_hz * t)).astype(np.float32)


def encode(audio: np.ndarray, file_format: str = "OGG") -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, audio, SAMPLE_RATE, format=file_format)
    return buffer.getvalue()


def test_tone_features():
    result = analyze(encode(tone(1000, 2)), SAMPLE_RATE, n_mfcc=20)

    assert result.status == "ok"
    assert result.error is None
    assert result.features["duration_s"] == pytest.approx(2.0)
    # A 1 kHz tone concentrates its energy at 1 kHz
    assert result.features["spectral_centroid_hz"] == pytest.approx(1000, rel=0.05)
    assert result.features["rms_mean"] > 0


def test_n_mfcc_sets_the_length_of_the_lists():
    result = analyze(encode(tone(1000, 1)), SAMPLE_RATE, n_mfcc=13)

    assert len(result.features["mfcc_mean"]) == 13
    assert len(result.features["mfcc_std"]) == 13


def test_other_sample_rate_is_resampled():
    # Ask for 16 kHz from a 32 kHz file: duration must not change
    result = analyze(encode(tone(1000, 2)), sample_rate=16000, n_mfcc=20)

    assert result.status == "ok"
    assert result.features["duration_s"] == pytest.approx(2.0)


@pytest.mark.parametrize(
    "data",
    [
        b"",  # empty file
        b"not an audio file" * 10,  # damaged file
        encode(np.zeros(0, dtype=np.float32), "WAV"),  # valid file, no samples
    ],
)
def test_bad_audio_fails_without_raising(data):
    result = analyze(data, SAMPLE_RATE, n_mfcc=20)

    assert result.status == "failed"
    assert result.error
    assert result.features == {}


INDICES = ["aci", "adi", "aei", "bi", "ndsi", "ht", "hf", "bgnt_db", "snrt_db"]


def noise(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(0)
    return (0.3 * rng.standard_normal(int(SAMPLE_RATE * seconds))).astype(np.float32)


def test_indices_tell_a_pure_tone_from_noise():
    tone_features = analyze(encode(tone(3000, 5), "WAV"), SAMPLE_RATE, 20).features
    noise_features = analyze(encode(noise(5), "WAV"), SAMPLE_RATE, 20).features

    # A tone concentrates its energy in one band; noise spreads it everywhere
    assert tone_features["hf"] < 0.5 < noise_features["hf"]
    assert tone_features["adi"] < noise_features["adi"]
    assert tone_features["aei"] > noise_features["aei"]


def test_indices_stay_in_their_ranges():
    values = analyze(encode(noise(5), "WAV"), SAMPLE_RATE, 20).features

    assert 0 <= values["aei"] <= 1
    assert -1 <= values["ndsi"] <= 1
    assert 0 <= values["ht"] <= 1
    assert 0 <= values["hf"] <= 1


def test_indices_are_null_for_pure_silence():
    silence = np.zeros(SAMPLE_RATE * 2, dtype=np.float32)
    result = analyze(encode(silence, "WAV"), SAMPLE_RATE, 20)

    assert result.status == "ok"
    assert all(result.features[name] is None for name in INDICES)


def test_quality_measures_spot_clipping_and_dropouts():
    clipped = np.clip(tone(1000, 2) * 4, -1, 1)
    with_gap = tone(1000, 2)
    with_gap[SAMPLE_RATE // 2 : SAMPLE_RATE] = 0  # half a second of silence

    clipped_features = analyze(encode(clipped, "WAV"), SAMPLE_RATE, 20).features
    gap_features = analyze(encode(with_gap, "WAV"), SAMPLE_RATE, 20).features

    assert clipped_features["clipping_fraction"] > 0.5
    assert gap_features["longest_zero_run_s"] == pytest.approx(0.5, abs=0.01)
    assert gap_features["clipping_fraction"] == 0


def test_quality_measures_spot_low_frequency_energy():
    rumble = analyze(encode(tone(60, 2), "WAV"), SAMPLE_RATE, 20).features
    whistle = analyze(encode(tone(3000, 2), "WAV"), SAMPLE_RATE, 20).features

    assert rumble["low_freq_energy_ratio"] > 0.9
    assert whistle["low_freq_energy_ratio"] < 0.01


def test_rain_band_is_steadier_for_noise_than_for_a_short_call():
    steady = analyze(encode(noise(5), "WAV"), SAMPLE_RATE, 20).features
    call = tone(900, 5)
    call[SAMPLE_RATE:] = 0  # one second of a 900 Hz call, then silence
    bursty = analyze(encode(call, "WAV"), SAMPLE_RATE, 20).features

    assert steady["rain_band_snr"] > bursty["rain_band_snr"]
