"""AI GH Chart pipeline: one command from MP3 to a GH3-ready folder.

Usage (Python 3.11+ with librosa, soundfile, numpy, basic_pitch):
    python make_song.py "D:\\path\\song.mp3" --id mysong
    python make_song.py song.mp3 --id mysong --name "My Song" --skip-grid-fit

Stages, in order (difficulty reference: aighgorod1 revision 2):
  1. grid        librosa estimate -> linear-fit constant BPM (+ preview wav)
  2. transcribe  Basic Pitch directly on the source (no stem separation)
  3. filter      pitch outliers (squeal/hum) + fingerstyle clicks
  4. group       onset groups (30 ms window), chords max 2 frets
  5. map         global pitch-rank compression into 5 frets
  6. gameplay    sustains, HOPO candidates, Star Power phrases
  7. revise      drop the later attack of every pair closer than 80 ms,
                 then recompute sustains and HOPO (accepted difficulty rule)
  8. validate    strict technical checks (0 errors required to export)
  9. audio       song.wav: silence lead-in + tail, normalize
 10. export      notes.chart with practice sections + reports + CHECKLIST.md

The two listening checks (grid preview, filtered-notes preview) do NOT block
the run; CHECKLIST.md reminds the user to confirm them before playing.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from itertools import combinations
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

PIPELINE_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = PIPELINE_ROOT / "config.json"
NAME_FRETS = ["Green", "Red", "Yellow", "Blue", "Orange"]


# ---------------------------------------------------------------- utilities


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fail(message: str) -> None:
    raise SystemExit(f"PIPELINE STOPPED: {message}")


class Stage:
    def __init__(self) -> None:
        self.reports: dict[str, dict] = {}

    def run(self, name: str, function, *args, **kwargs):
        started = time.perf_counter()
        print(f"[{name}] ...", flush=True)
        result = function(*args, **kwargs)
        elapsed = time.perf_counter() - started
        print(f"[{name}] done in {elapsed:.1f} s", flush=True)
        return result


# ------------------------------------------------------------------- stages


def stage_grid(source: Path, work: Path, config: dict) -> dict:
    cfg = config["grid"]
    y, sr = librosa.load(str(source), sr=cfg["analysis_sample_rate"], mono=True)
    duration = len(y) / sr

    onset_env = librosa.onset.onset_strength(
        y=y, sr=sr, hop_length=cfg["hop_length"]
    )
    tempo, frames = librosa.beat.beat_track(
        onset_envelope=onset_env, sr=sr, hop_length=cfg["hop_length"], trim=True
    )
    bpm_raw = float(np.asarray(tempo).reshape(-1)[0])
    beats = librosa.frames_to_time(frames, sr=sr, hop_length=cfg["hop_length"])
    if len(beats) < 8:
        fail("fewer than 8 beats detected; cannot fit a constant grid")

    indices = np.arange(len(beats), dtype=float)
    a, b = np.polyfit(indices, beats, 1)
    bpm = 60.0 / float(a)
    first = float(b)
    fitted = first + indices * float(a)
    dev = (beats - fitted) * 1000.0

    grid = {
        "bpm": bpm,
        "raw_bpm": bpm_raw,
        "first_grid_point_seconds": first,
        "raw_beat_times_seconds": beats.tolist(),
        "duration_seconds": duration,
        "raw_deviation_ms": {
            "median": float(np.median(np.abs(dev))),
            "p95": float(np.percentile(np.abs(dev), 95)),
            "max": float(np.max(np.abs(dev))),
        },
        "status": "constant_grid_fit_not_listening_validated",
    }
    write_json(work / "grid_fit.json", grid)

    clicks = librosa.clicks(
        times=fitted,
        sr=sr,
        click_freq=cfg["click_freq"],
        click_duration=cfg["click_duration"],
        length=len(y),
    )
    mix = 0.65 * y + 0.35 * clicks
    peak = float(np.max(np.abs(mix)))
    if peak > 0.98:
        mix *= 0.98 / peak
    sf.write(str(work / "grid_preview.wav"), mix, sr, subtype="PCM_16")
    return grid


def stage_transcribe(source: Path, work: Path, config: dict) -> dict:
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict

    cfg = config["transcription"]
    _model_output, midi, note_events = predict(
        str(source),
        ICASSP_2022_MODEL_PATH,
        onset_threshold=cfg["onset_threshold"],
        frame_threshold=cfg["frame_threshold"],
        minimum_note_length=cfg["minimum_note_length_ms"],
    )
    notes = []
    for event in note_events:
        start, end, pitch, amplitude, *_ = event
        notes.append({
            "start_seconds": float(start),
            "end_seconds": float(end),
            "duration_seconds": float(end - start),
            "midi_pitch": int(pitch),
            "amplitude": float(amplitude),
        })
    notes.sort(key=lambda n: (n["start_seconds"], n["midi_pitch"]))
    midi.write(str(work / "transcription_initial.mid"))

    report = {
        "model": "basic-pitch / ICASSP_2022",
        "parameters": cfg,
        "note_count": len(notes),
        "notes": notes,
        "status": "initial_transcription_not_validated",
    }
    write_json(work / "notes_raw.json", report)
    return report


def stage_filter(transcription: dict, work: Path, config: dict) -> dict:
    cfg = config["pitch_filter"]
    lo = cfg["sub_bass_cut"]
    hi = cfg["fretboard_hi"]
    gate = cfg["above_fretboard_amplitude_gate"]

    kept, removed = [], []
    for index, note in enumerate(transcription["notes"]):
        pitch = note["midi_pitch"]
        amplitude = note["amplitude"]
        reason = None
        if pitch < lo:
            reason = "sub_bass_noise"
        elif pitch > hi and amplitude < gate:
            reason = "above_fretboard_squeal"
        if reason:
            removed.append({"source_index": index, **note, "reason": reason})
        else:
            kept.append({**note, "source_index": index})

    report = {
        "rules": {"sub_bass_cut": lo, "squeal_above": hi, "gate": gate},
        "input": len(transcription["notes"]),
        "removed": len(removed),
        "output": len(kept),
        "removed_notes": removed,
        "notes": kept,
        "status": "pitch_outliers_filtered_not_listening_validated",
    }
    write_json(work / "notes_filtered.json", report)
    return report


def stage_group(filtered: dict, work: Path, config: dict) -> dict:
    cfg = config["onsets"]
    notes = filtered["notes"]
    kept, clicks = [], []
    for note in notes:
        if (
            note["duration_seconds"] < cfg["click_min_duration_seconds"]
            or note["amplitude"] < cfg["click_min_amplitude"]
        ):
            clicks.append(note)
        else:
            kept.append(note)
    kept.sort(key=lambda n: (n["start_seconds"], n["midi_pitch"]))

    window = cfg["grouping_window_seconds"]
    groups = []
    for note in kept:
        if not groups or note["start_seconds"] - groups[-1]["start_seconds"] > window:
            groups.append({
                "start_seconds": note["start_seconds"],
                "notes": [],
            })
        groups[-1]["notes"].append(note)
    for group in groups:
        group["unique_pitches"] = sorted({n["midi_pitch"] for n in group["notes"]})
        group["onset_spread_ms"] = 1000 * (
            max(n["start_seconds"] for n in group["notes"])
            - group["start_seconds"]
        )

    report = {
        "grouping_window_seconds": window,
        "clicks_removed": len(clicks),
        "notes_kept": len(kept),
        "groups": groups,
        "status": "onset_groups_not_a_playable_chart",
    }
    write_json(work / "onset_groups.json", report)
    return report


def stage_map(groups: dict, work: Path, config: dict) -> dict:
    """Map pitches onto frets following the CONTOUR of the melody.

    The old global rank compression mapped every pitch to a fixed lane, which
    flattened the melodic shape (the same note always sat on the same fret).
    The contour method tracks the melody like the accepted Hard design does:
    a rolling window of recent centers defines the local range, each event
    lands near its relative height, and repeated same-lane attacks are pushed
    to a neighbouring lane so runs stay playable. Difficulty comes from the
    density of events and 2-note chords, not from losing the melody.
    """
    group_list = groups["groups"]
    if not group_list:
        fail("no onset groups to map")

    events = []
    history: list[float] = []
    window = config["expert"].get("contour_window_events", 8)
    lanes_count = 5

    def local_target(center: float) -> float:
        """Relative height of this event inside the recent melodic range."""
        span_low, span_high = min(history), max(history)
        span = (span_high - span_low) or 1.0
        return (lanes_count - 1) * (center - span_low) / span

    for index, group in enumerate(group_list):
        original = group["unique_pitches"]
        selected = original[:2] if len(original) <= 2 else [original[0], original[-1]]
        center = sum(selected) / len(selected)
        history.append(center)
        target = local_target(center)

        frets: list[int]
        if len(selected) == 2:
            # Two-note chord: two adjacent lanes around the melodic target.
            base = min(lanes_count - 2, max(0, round(target - 0.5)))
            frets = [base, base + 1]
        else:
            fret = min(lanes_count - 1, max(0, round(target)))
            previous = events[-1] if events else None
            if previous and previous["frets"] == [fret]:
                # Same lane as the previous attack: shift to the nearest free
                # lane so repeated notes stay readable (and hopo-friendly).
                options = [f for f in range(lanes_count) if f != fret]
                fret = min(options, key=lambda f: abs(f - target))
            frets = [fret]

        events.append({
            "source_group_index": index,
            "start_seconds": group["start_seconds"],
            "source_pitches": original,
            "selected_pitches": selected,
            "frets": frets,
        })
        if len(history) > window:
            history.pop(0)

    report = {
        "method": "melodic_contour_rolling_window",
        "contour_window_events": window,
        "lane_names": NAME_FRETS,
        "max_chord_size": config["expert"]["max_chord_size"],
        "events": events,
        "status": "draft_fret_mapping_not_playability_validated",
    }
    write_json(work / "mapping_draft.json", report)
    return report


def stage_gameplay(mapping: dict, groups: dict, grid: dict, work: Path, config: dict) -> dict:
    expert = config["expert"]
    period = 60 / grid["bpm"]
    events = [dict(event) for event in mapping["events"]]
    group_list = groups["groups"]

    for i, event in enumerate(events):
        start = event["start_seconds"]
        event["sustain_seconds"] = 0.0
        event["sustain_beats"] = 0.0
        event["hopo_candidate"] = False

        if len(event["frets"]) == 1:
            group = group_list[event["source_group_index"]]
            pitch = event["selected_pitches"][0]
            matching = [n for n in group["notes"] if n["midi_pitch"] == pitch]
            if not matching:
                fail("mapping references a missing source note")
            end = max(n["end_seconds"] for n in matching)
            if i + 1 < len(events):
                end = min(
                    end,
                    events[i + 1]["start_seconds"]
                    - period * expert["sustain_gap_before_next_beats"],
                )
            duration = max(0.0, end - start)
            if duration >= period * expert["sustain_minimum_beats"]:
                event["sustain_seconds"] = duration
                event["sustain_beats"] = duration / period

        if i > 0:
            previous = events[i - 1]
            gap = start - previous["start_seconds"]
            event["hopo_candidate"] = (
                len(previous["frets"]) == 1
                and len(event["frets"]) == 1
                and previous["frets"][0] != event["frets"][0]
                and 0 < gap <= period * expert["hopo_threshold_beats"]
            )

    grid_end_beats = (grid["duration_seconds"] - grid["first_grid_point_seconds"]) / period
    phrases, skipped = [], []
    for start_beat in range(
        expert["star_power_spacing_beats"],
        int(grid_end_beats),
        expert["star_power_spacing_beats"],
    ):
        end_beat = start_beat + expert["star_power_phrase_beats"]
        start = grid["first_grid_point_seconds"] + start_beat * period
        end = grid["first_grid_point_seconds"] + end_beat * period
        members = [
            event["source_group_index"]
            for event in events
            if start <= event["start_seconds"] < end
        ]
        if end_beat > grid_end_beats or len(members) < expert["star_power_minimum_events"]:
            skipped.append(start_beat)
            continue
        phrases.append({
            "start_seconds": start,
            "end_seconds": end,
            "source_group_indices": members,
        })
    phrases.sort(key=lambda phrase: phrase["start_seconds"])

    report = {
        "period_seconds": period,
        "sustains": sum(e["sustain_seconds"] > 0 for e in events),
        "hopo_candidates": sum(e["hopo_candidate"] for e in events),
        "star_power_phrases": phrases,
        "star_power_skipped_starts": skipped,
        "events": events,
        "status": "draft_with_gameplay_not_revised",
    }
    write_json(work / "draft_gameplay.json", report)
    return report


def stage_revise(gameplay: dict, work: Path, config: dict) -> dict:
    min_gap = config["expert"]["min_gap_seconds"]
    events = [dict(event) for event in gameplay["events"]]

    kept, removed = [], []
    for event in events:
        if kept and event["start_seconds"] - kept[-1]["start_seconds"] < min_gap:
            removed.append(event)
        else:
            kept.append(event)

    period = gameplay["period_seconds"]
    expert = config["expert"]
    sustains = 0
    hopo = 0
    for i, event in enumerate(kept):
        start = event["start_seconds"]
        event["sustain_seconds"] = 0.0
        event["sustain_beats"] = 0.0
        event["hopo_candidate"] = False

        if len(event["frets"]) == 1:
            group = gameplay["_group_list"][event["source_group_index"]]
            pitch = event["selected_pitches"][0]
            matching = [n for n in group["notes"] if n["midi_pitch"] == pitch]
            if not matching:
                fail("mapping references a missing source note")
            end = max(n["end_seconds"] for n in matching)
            if i + 1 < len(kept):
                end = min(
                    end,
                    kept[i + 1]["start_seconds"]
                    - period * expert["sustain_gap_before_next_beats"],
                )
            duration = max(0.0, end - start)
            if duration >= period * expert["sustain_minimum_beats"]:
                event["sustain_seconds"] = duration
                event["sustain_beats"] = duration / period
                sustains += 1

        if i > 0:
            previous = kept[i - 1]
            gap = start - previous["start_seconds"]
            event["hopo_candidate"] = (
                len(previous["frets"]) == 1
                and len(event["frets"]) == 1
                and previous["frets"][0] != event["frets"][0]
                and 0 < gap <= period * expert["hopo_threshold_beats"]
            )
            hopo += int(event["hopo_candidate"])

    phrases = []
    for phrase in gameplay["star_power_phrases"]:
        members = [
            index for index in phrase["source_group_indices"]
            if any(event["source_group_index"] == index for event in kept)
        ]
        if len(members) >= expert["star_power_minimum_events"]:
            phrases.append({**phrase, "source_group_indices": members})

    report = {
        "min_gap_seconds": min_gap,
        "removed_events": len(removed),
        "removed_detail": removed,
        "events": kept,
        "sustains": sustains,
        "hopo_candidates": hopo,
        "star_power_phrases": phrases,
        "status": "revision_applied_pending_validation",
    }
    write_json(work / "draft_revised.json", report)
    return report


def stage_hard(gameplay: dict, groups: dict, grid: dict, work: Path, config: dict) -> dict:
    """Hard difficulty: independent design, not Expert-minus-notes.

    Rhythm comes from fixed half-beat buckets (steady readable grid), pitch
    history is remapped onto FOUR lanes (no orange), and chords appear only
    where an attack lands on an already-sounding pitch with wide neighbours.
    """
    cfg = config["hard"]
    period = 60 / grid["bpm"]
    origin = grid["first_grid_point_seconds"]
    lanes = cfg["lanes"]
    bucket = period * cfg["bucket_beats"]
    group_list = groups["groups"]

    # --- rhythm: assign every expert event to a half-beat bucket ---
    buckets: dict[int, dict] = {}
    for event in gameplay["events"]:
        beat = (event["start_seconds"] - origin) / period
        index = max(0, round(beat / cfg["bucket_beats"]))
        slot = buckets.setdefault(index, {
            "index": index,
            "seconds": origin + index * bucket,
            "notes": [],
            "expert_events": [],
        })
        slot["expert_events"].append(event)
        slot["notes"].extend(
            group_list[event["source_group_index"]]["notes"]
        )

    # --- pitch: rolling rank remap into `lanes` lanes ---
    history = []
    events = []
    for index in sorted(buckets):
        slot = buckets[index]
        pitches = sorted({n["midi_pitch"] for n in slot["notes"]})
        if not pitches:
            continue
        center = sum(pitches) / len(pitches)
        history.append(center)
        window = history[-8:]
        low, high = min(window), max(window)
        span = (high - low) or 1.0
        target = (lanes - 1) * (center - low) / span
        chord = False

        # --- chord: attack over an already-sounding different pitch ---
        if len(pitches) > 1:
            earliest = min(slot["expert_events"], key=lambda e: e["start_seconds"])
            t = slot["seconds"]
            sounding = sorted({
                n["midi_pitch"]
                for e in slot["expert_events"] if e is not earliest
                for n in group_list[e["source_group_index"]]["notes"]
                if n["start_seconds"] < t - 0.030 and n["end_seconds"] >= t + 0.080
            })
            sounding = [p for p in sounding if p not in pitches] or sounding
            if sounding and len(sounding) >= 2:
                chord = True
                pitches = sorted({pitches[0], max(sounding)})

        previous_gap = (
            slot["seconds"] - events[-1]["start_seconds"]
            if events else None
        )
        next_known_gap = None  # refined after the loop below
        event = {
            "bucket_index": index,
            "start_seconds": slot["seconds"],
            "start_beat": index * cfg["bucket_beats"],
            "source_pitches": pitches,
            "is_chord": chord,
            "frets": [0],  # provisional; resolved after neighbour gaps known
            "sustain_seconds": 0.0,
            "sustain_beats": 0.0,
            "hopo_candidate": False,
            "_target": target,
            "_previous_gap": previous_gap,
        }
        event["_chord_allowed"] = (
            chord and previous_gap is not None
            and previous_gap >= cfg["chord_min_neighbor_gap_seconds"]
        )
        events.append(event)

    # resolve frets with distinct-lane choice + forced same-lane jump rule
    for i, event in enumerate(events):
        target = event.pop("_target")
        previous = events[i - 1] if i else None
        next_event = events[i + 1] if i + 1 < len(events) else None
        wide = (
            (event["_previous_gap"] is None or event["_previous_gap"] >= cfg["chord_min_neighbor_gap_seconds"])
            and (next_event is None or next_event["start_seconds"] - event["start_seconds"] >= cfg["chord_min_neighbor_gap_seconds"])
        )
        count = 2 if (event["_chord_allowed"] and wide) else 1
        event.pop("_chord_allowed", None)
        event.pop("_previous_gap", None)

        if count == 2:
            base = min(lanes - 1, max(0, round(target - 0.5)))
            frets = sorted({base, min(lanes - 1, base + 1)})
            if len(frets) < 2:
                frets = sorted({max(0, base - 1), base})
        else:
            fret = min(lanes - 1, max(0, round(target)))
            if previous and previous["frets"] == [fret]:
                # forced same-lane jump: shift to the nearest free lane
                options = [f for f in range(lanes) if f != fret]
                fret = min(options, key=lambda f: abs(f - target))
            frets = [fret]
        event["frets"] = frets

        # sustains: single notes only
        if count == 1:
            end = None
            for note in buckets[event["bucket_index"]]["notes"]:
                pitch = event["source_pitches"][0]
                if note["midi_pitch"] == pitch:
                    end = max(end or 0.0, note["end_seconds"])
            end = end if end is not None else event["start_seconds"] + period
            if next_event is not None:
                end = min(end, next_event["start_seconds"] - period * cfg["sustain_gap_before_next_beats"])
            duration = max(0.0, end - event["start_seconds"])
            if duration >= period * cfg["sustain_minimum_beats"]:
                event["sustain_seconds"] = duration
                event["sustain_beats"] = duration / period

    # HOPO candidates
    for i, event in enumerate(events):
        if i == 0:
            continue
        previous = events[i - 1]
        gap = event["start_seconds"] - previous["start_seconds"]
        event["hopo_candidate"] = (
            len(previous["frets"]) == 1
            and len(event["frets"]) == 1
            and previous["frets"][0] != event["frets"][0]
            and 0 < gap <= period * cfg["hopo_threshold_beats"]
        )

    # Star Power on the hard grid
    phrases = []
    grid_end_beats = (grid["duration_seconds"] - origin) / period
    for start_beat in range(
        cfg["star_power_spacing_beats"], int(grid_end_beats), cfg["star_power_spacing_beats"]
    ):
        end_beat = start_beat + cfg["star_power_phrase_beats"]
        start = origin + start_beat * period
        end = origin + end_beat * period
        members = [e for e in events if start <= e["start_seconds"] < end]
        if end_beat > grid_end_beats or len(members) < cfg["star_power_minimum_events"]:
            continue
        phrases.append({"start_seconds": start, "end_seconds": end})

    clean = [
        {k: v for k, v in event.items() if not k.startswith("_")}
        for event in events
    ]
    report = {
        "method": "half_beat_bucket_grid_four_lanes_independent_design",
        "bucket_beats": cfg["bucket_beats"],
        "lanes": lanes,
        "events": clean,
        "star_power_phrases": phrases,
        "status": "hard_draft_independent_design_not_game_tested",
    }
    write_json(work / "hard_draft.json", report)
    return report


def stage_validate(revised: dict, duration: float) -> dict:
    events = revised["events"]
    errors, fast = [], []
    min_gap = 0.080

    for i, event in enumerate(events):
        t = event["start_seconds"]
        sustain = event["sustain_seconds"]
        frets = event["frets"]
        if not math.isfinite(t) or not 0 <= t < duration:
            errors.append(f"Event {i}: invalid onset")
        if not math.isfinite(sustain) or sustain < 0:
            errors.append(f"Event {i}: invalid sustain")
        if (
            not 1 <= len(frets) <= 2
            or len(set(frets)) != len(frets)
            or any(type(f) is not int or not 0 <= f <= 4 for f in frets)
        ):
            errors.append(f"Event {i}: invalid frets")
        if i + 1 < len(events):
            gap = events[i + 1]["start_seconds"] - t
            if gap <= 0:
                errors.append(f"Event {i}: non-increasing onset order")
            if sustain > 0 and t + sustain > events[i + 1]["start_seconds"] + 1e-6:
                errors.append(f"Event {i}: sustain overlaps next attack")
            if 0 < gap < min_gap:
                fast.append({"index": i, "gap_ms": round(gap * 1000, 1)})

    for i, phrase in enumerate(revised["star_power_phrases"]):
        if not 0 <= phrase["start_seconds"] < phrase["end_seconds"] <= duration:
            errors.append(f"Star Power {i}: invalid bounds")
        count = sum(
            phrase["start_seconds"] <= e["start_seconds"] < phrase["end_seconds"]
            for e in events
        )
        if count < 3:
            errors.append(f"Star Power {i}: only {count} events")

    return {
        "errors": errors,
        "gaps_under_80ms": fast,
        "status": "pass" if not errors and not fast else "fail",
    }


def stage_audio(source: Path, out: Path, config: dict) -> dict:
    cfg = config["audio"]
    audio, sr = sf.read(str(source), dtype="float32", always_2d=True)
    if not np.isfinite(audio).all():
        fail("non-finite audio samples in source")
    lead = round(cfg["lead_in_seconds"] * sr)
    tail = round(cfg["tail_seconds"] * sr)
    song = np.concatenate([
        np.zeros((lead, audio.shape[1]), dtype=np.float32),
        audio,
        np.zeros((tail, audio.shape[1]), dtype=np.float32),
    ])
    peak = float(np.max(np.abs(song)))
    gain = min(1.0, cfg["peak_target"] / peak) if peak > 0 else 1.0
    sf.write(str(out / "song.wav"), song * gain, sr, subtype="PCM_16")
    # Where does the music actually stop? Trailing silence (encore tail,
    # encoder padding) must not carry playable notes.
    mono = audio.mean(axis=1)
    window = max(1, round(0.250 * sr))
    threshold = max(0.004, float(np.max(np.abs(mono))) * 0.01)
    music_end = len(audio) / sr
    quiet = np.abs(mono) < threshold
    run = 0
    for i in range(len(quiet) - 1, -1, -1):
        if quiet[i]:
            run += 1
        else:
            break
    if run >= window:
        music_end = (len(audio) - run) / sr
    return {
        "sample_rate": sr,
        "channels": audio.shape[1],
        "source_duration_seconds": len(audio) / sr,
        "music_end_seconds": music_end,
        "lead_in_seconds": cfg["lead_in_seconds"],
        "tail_seconds": cfg["tail_seconds"],
        "audio_duration_seconds": len(song) / sr,
        "gain": gain,
    }


def stage_export(draft: dict, grid: dict, audio: dict, out: Path, config: dict, song_id: str, name: str, artist: str, track: str = "ExpertSingle", lanes: int = 5) -> dict:
    chart_cfg = config["chart"]
    expert = config["expert"]
    resolution = chart_cfg["resolution"]
    bpm = grid["bpm"]
    shift = audio["lead_in_seconds"]
    ticks_per_second = resolution * bpm / 60

    def tick(seconds: float) -> int:
        return round(seconds * ticks_per_second)

    # Music can end before the audio does (encore tail, fade, silence): events
    # after the real end of the music would play over silence, so cut them.
    music_end = audio.get("music_end_seconds") or audio["source_duration_seconds"]
    playable = [
        event for event in draft["events"]
        if event["start_seconds"] <= music_end - 0.150
    ]
    if len(playable) < len(draft["events"]):
        print(
            f"    trimmed {len(draft['events']) - len(playable)} event(s) past the "
            "end of the music (tail silence)"
        )

    rows, seen, errors_ms = [], set(), []
    sustain_count = 0
    max_fret = lanes - 1
    for event in playable:
        seconds = shift + event["start_seconds"]
        position = tick(seconds)
        if position < 0 or position in seen:
            fail("negative or colliding event tick; export aborted")
        seen.add(position)
        errors_ms.append(abs(position / ticks_per_second - seconds) * 1000)
        sustain = event["sustain_seconds"]
        length = max(0, tick(seconds + sustain) - position) if sustain > 0 else 0
        sustain_count += int(length > 0)
        for fret in event["frets"]:
            if not 0 <= fret <= max_fret:
                fail(f"fret {fret} outside {lanes}-lane track; export aborted")
            rows.append((position, f"N {fret} {length}"))

    for phrase in draft["star_power_phrases"]:
        start = tick(shift + phrase["start_seconds"])
        end = tick(shift + phrase["end_seconds"])
        if end <= start:
            fail("invalid Star Power length; export aborted")
        rows.append((start, f"S 2 {end - start}"))

    audio_end = audio["audio_duration_seconds"]
    if any(position >= tick(audio_end) for position, _ in rows):
        fail("event outside audio; export aborted")

    period = 60 / bpm
    origin = grid["first_grid_point_seconds"]
    source_duration = audio["source_duration_seconds"]
    last_beat = max(
        (event["start_seconds"] - origin) / period for event in playable
    ) if playable else 0
    events_lines = [
        (0, 'E "section Lead-in"'),
        (tick(shift), 'E "section start"'),
    ]
    practice = 0
    for number, start_beat in enumerate(
        range(expert["practice_section_beats"], int(last_beat) + 1,
              expert["practice_section_beats"]),
        start=1,
    ):
        moment = origin + start_beat * period
        if moment >= source_duration - audio["tail_seconds"]:
            break
        events_lines.append((tick(shift + moment), f'E "section Part {number:02d}"'))
        practice += 1
    events_lines += [
        (tick(shift + source_duration - audio["tail_seconds"]), 'E "section Tail"'),
        (tick(audio_end - 0.05), 'E "end"'),
    ]

    lines = [
        "[Song]", "{",
        f'  Name = "{name}"',
        f'  Artist = "{artist}"',
        '  Charter = "AI GH Prototype"',
        "  Offset = 0",
        f"  Resolution = {resolution}",
        '  MusicStream = "song.wav"',
        "}",
        "[SyncTrack]", "{",
        f"  0 = {chart_cfg['time_signature']}",
        f"  0 = B {round(bpm * 1000)}",
        "}",
        "[Events]", "{",
    ]
    lines += [f"  {position} = {value}" for position, value in sorted(events_lines)]
    lines += ["}", f"[{track}]", "{"]
    lines += [f"  {position} = {value}" for position, value in sorted(rows)]
    lines += ["}"]
    (out / "notes.chart").write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = {
        "events_trimmed_at_music_end": len(draft["events"]) - len(playable),
        "song_id": song_id,
        "track": track,
        "lanes": lanes,
        "bpm": bpm,
        "resolution": resolution,
        "gameplay_events": len(draft["events"]),
        "note_rows": sum(value.startswith("N ") for _, value in rows),
        "sustain_events": sustain_count,
        "star_power_phrases": len(draft["star_power_phrases"]),
        "practice_sections": practice,
        "max_onset_rounding_error_ms": max(errors_ms, default=0),
        "forced_hopo_markers": False,
        "gaps_under_80ms": 0,
        "status": "chart_created_not_imported",
    }
    write_json(out / "chart_export_report.json", report)

    checklist = f"""# Checklist: {name} ({song_id})

Package: {out}
The pipeline finished. Before/while testing in GH3:

1. [ ] Listen to grid_preview.wav (pipeline folder) - clicks must match the pulse.
       If they drift, re-run with --bpm and --grid-start overrides.
2. [ ] Listen to notes_preview.wav (pipeline folder) - melody recognizable,
       no squeal notes, no dull click-notes.
3. [ ] Import notes.chart + song.wav via GHTCP (song id: {song_id}).
4. [ ] Play Expert; use Practice -> Part NN sections for hard spots.
5. [ ] Report which Part numbers feel impossible; re-run with
       --min-gap 0.114 for a lighter chart if needed.

Facts: BPM {bpm:.3f} | events {report['gameplay_events']} | rows {report['note_rows']} |
sustains {sustain_count} | SP phrases {report['star_power_phrases']} |
practice sections {practice} | audio {audio_end:.1f} s
"""
    (out / "CHECKLIST.md").write_text(checklist, encoding="utf-8")
    return report


def export_hard_track(hard: dict, grid: dict, audio: dict, out: Path, config: dict, song_id: str, name: str, artist: str) -> dict:
    """Append [HardSingle] to notes.chart and merge the report."""
    chart_path = out / "notes.chart"
    text = chart_path.read_text(encoding="utf-8")
    temp = out / "_hard_draft_chart.chart"
    expert_report = json.loads((out / "chart_export_report.json").read_text(encoding="utf-8"))

    # Reuse stage_export into a scratch chart, then splice the block in.
    scratch = out / "_hard_scratch"
    scratch.mkdir(exist_ok=True)
    hard_report = stage_export(
        hard, grid, audio, scratch, config, song_id, name, artist,
        track="HardSingle", lanes=config["hard"]["lanes"],
    )
    hard_text = (scratch / "notes.chart").read_text(encoding="utf-8")
    block_start = hard_text.index("[HardSingle]")
    hard_block = hard_text[block_start:].rstrip("\n")
    if "[HardSingle]" in text:
        fail("chart already contains a HardSingle block; export aborted")
    chart_path.write_text(text.rstrip("\n") + "\n" + hard_block + "\n", encoding="utf-8")

    expert_report["hard_track"] = {
        "gameplay_events": hard_report["gameplay_events"],
        "note_rows": hard_report["note_rows"],
        "sustain_events": hard_report["sustain_events"],
        "star_power_phrases": hard_report["star_power_phrases"],
        "method": "half_beat_bucket_grid_four_lanes_independent_design",
    }
    (out / "chart_export_report.json").write_text(
        json.dumps(expert_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    scratch_path = out / "_hard_scratch"
    for leftover in scratch_path.iterdir():
        leftover.unlink()
    scratch_path.rmdir()
    temp.unlink(missing_ok=True)
    return hard_report


# --------------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(description="MP3 -> GH3 chart pipeline")
    parser.add_argument("source", help="path to the source audio (mp3/wav/flac/ogg)")
    parser.add_argument("song_id_positional", nargs="?", default=None,
                        help="song id as second word of the launcher line")
    parser.add_argument("--id", default=None, help="song id, e.g. mysong (latin letters/digits)")
    parser.add_argument("--last-id-file", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--name", default=None, help="chart display name (defaults to song id)")
    parser.add_argument("--artist", default=None, help="chart artist line (defaults to Unknown Artist)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="pipeline config path")
    parser.add_argument("--out-root", default=r"D:\ai-gh\pipeline\out", help="output root folder")
    parser.add_argument("--work-root", default=r"D:\ai-gh\pipeline\work", help="work folder root")
    parser.add_argument("--bpm", type=float, default=None, help="override constant BPM (skip grid fit)")
    parser.add_argument("--grid-start", type=float, default=None, help="override first grid point seconds")
    parser.add_argument("--min-gap", type=float, default=None, help="override the 80 ms revision rule")
    parser.add_argument("--no-hard", action="store_true", help="skip the Hard track")
    parser.add_argument("--skip-grid-fit", action="store_true", help="use raw librosa beats without constant fit")
    args = parser.parse_args()

    # Launcher convenience: 'script "path.mp3" mysong' == --id mysong.
    if args.id is None and args.song_id_positional:
        args.id = args.song_id_positional
    if args.id is None:
        fail("song id is required: pass --id or a second word")

    source = Path(args.source)
    if not source.exists():
        fail(f"source not found: {source}")
    # The .bat launcher passes --id via cmd; strip stray quotes and waste
    # characters that can arrive from interactive paste or drag-and-drop.
    song_id_arg = args.id.strip().strip('"').replace("=", "").strip()
    if not song_id_arg.isascii() or not song_id_arg.replace("-", "").isalnum():
        fail(f"--id must be latin letters/digits/dashes (GH3 song id); got: {args.id!r}")
    args.id = song_id_arg
    if args.last_id_file:
        Path(args.last_id_file).write_text(
            f"song_id={args.id}\n", encoding="ascii"
        )

    config = load_config(Path(args.config))
    if args.min_gap is not None:
        config["expert"]["min_gap_seconds"] = args.min_gap

    song_id = args.id
    out = Path(args.out_root) / song_id
    work = Path(args.work_root) / song_id
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    name = args.name or song_id
    artist = args.artist or "Unknown Artist"
    stage = Stage()

    grid = stage.run("grid", stage_grid, source, work, config)
    if args.bpm is not None:
        grid["bpm"] = args.bpm
        grid["status"] = "constant_grid_user_override"
    if args.grid_start is not None:
        grid["first_grid_point_seconds"] = args.grid_start
        grid["status"] = "constant_grid_user_override"
    if args.skip_grid_fit:
        grid["bpm"] = grid["raw_bpm"]
    print(f"    BPM {grid['bpm']:.3f} | first point {grid['first_grid_point_seconds']:.3f} s")

    transcription = stage.run("transcribe", stage_transcribe, source, work, config)
    print(f"    notes: {transcription['note_count']}")

    filtered = stage.run("filter", stage_filter, transcription, work, config)
    print(f"    after pitch filter: {filtered['output']} (removed {filtered['removed']})")

    groups = stage.run("group", stage_group, filtered, work, config)
    print(f"    groups: {len(groups['groups'])} (clicks removed: {groups['clicks_removed']})")

    mapping = stage.run("map", stage_map, groups, work, config)
    print(f"    events: {len(mapping['events'])}")

    gameplay = stage.run("gameplay", stage_gameplay, mapping, groups, grid, work, config)
    gameplay["_group_list"] = groups["groups"]

    revised = stage.run("revise", stage_revise, gameplay, work, config)
    print(f"    after {config['expert']['min_gap_seconds'] * 1000:.0f} ms rule: "
          f"{len(revised['events'])} events (removed {revised['removed_events']})")

    duration = grid["duration_seconds"]
    validation = stage.run("validate", stage_validate, revised, duration)
    write_json(work / "validation.json", validation)
    if validation["status"] != "pass":
        print(json.dumps(validation["errors"][:20], indent=2))
        fail("validation failed; nothing exported")
    print("    validation: 0 errors, 0 gaps under 80 ms")

    audio = stage.run("audio", stage_audio, source, out, config)
    print(f"    song.wav: {audio['audio_duration_seconds']:.1f} s (gain {audio['gain']:.3f})")

    report = stage.run("export", stage_export, revised, grid, audio, out, config, song_id, name, artist)
    if not args.no_hard:
        hard = stage.run("hard", stage_hard, gameplay, groups, grid, work, config)
        print(f"    hard track: {len(hard['events'])} events")
        hard_report = stage.run("export-hard", export_hard_track, hard, grid, audio, out, config, song_id, name, artist)
        report["hard_track"] = hard_report
    write_json(work / "pipeline_summary.json", {
        "song_id": song_id,
        "grid": {k: grid[k] for k in ("bpm", "first_grid_point_seconds", "status")},
        "counts": {
            "notes_raw": transcription["note_count"],
            "notes_filtered": filtered["output"],
            "clicks_removed": groups["clicks_removed"],
            "events_before_revision": len(gameplay["events"]),
            "events_final": len(revised["events"]),
        },
        "validation": validation["status"],
        "export": report,
    })

    # Notes listening preview from the FINAL revised events (post-filters).
    audio_data, sr = sf.read(str(source), dtype="float32", always_2d=True)
    reference = audio_data.mean(axis=1)
    synth = np.zeros(len(reference), dtype=np.float64)
    group_list = groups["groups"]
    for event in revised["events"]:
        group = group_list[event["source_group_index"]]
        for note in group["notes"]:
            start = max(0, round(note["start_seconds"] * sr))
            end = min(len(synth), round(note["end_seconds"] * sr))
            length = end - start
            if length <= 0:
                continue
            frequency = 440 * 2 ** ((note["midi_pitch"] - 69) / 12)
            t = np.arange(length) / sr
            tone = np.sin(2 * np.pi * frequency * t)
            envelope = np.ones(length)
            attack = min(round(0.005 * sr), length // 2)
            release = min(round(0.020 * sr), length // 2)
            if attack:
                envelope[:attack] = np.linspace(0, 1, attack)
            if release:
                envelope[-release:] = np.linspace(1, 0, release)
            synth[start:end] += tone * envelope * float(note["amplitude"])
    ref_rms = float(np.sqrt(np.mean(reference.astype(np.float64) ** 2)))
    syn_rms = float(np.sqrt(np.mean(synth ** 2)))
    if min(ref_rms, syn_rms) > 1e-8:
        reference = reference / ref_rms
        synth = synth / syn_rms
        peak = max(float(np.max(np.abs(reference))), float(np.max(np.abs(synth))))
        scale = min(0.1, 0.95 / peak)
        sf.write(str(work / "notes_preview.wav"), synth * scale, sr, subtype="PCM_16")

    print(f"\n=== DONE ===")
    print(f"Import folder : {out}")
    print(f"  notes.chart ({'Expert + Hard' if 'hard_track' in report else 'Expert only'}) | song.wav | reports | CHECKLIST.md")
    print(f"Work folder   : {work}")
    print(f"  grid_preview.wav | notes_preview.wav | reports")
    print(f"Next: listen to the two previews, then import via GHTCP as '{song_id}'.")


if __name__ == "__main__":
    main()
