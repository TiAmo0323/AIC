"""Generate ten held-out local samples with frozen quality/repair code."""
from pathlib import Path
import hashlib
import json
import sys
import time
import urllib.request
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT.parent / "HumanAction-runtime"
OUTPUT = ROOT / "reports/validation_20260930"
sys.path.insert(0, str(ROOT))
from motionlint.cli.main import _write_json


def request(url, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def code_hashes():
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "motionlint").rglob("*.py")) + list((ROOT / "motionlint/configs").glob("*.yaml"))}


def rhythm(path, bpm, pattern):
    rate, duration = 22050, 36
    samples = np.zeros(rate * duration)
    for index, when in enumerate(np.arange(0, duration, 60 / bpm / 2)):
        length = int(.16 * rate)
        t = np.arange(length) / rate
        if index % 2 == 0:
            pulse = np.sin(2 * np.pi * (65 * t + 35 * (1 - np.exp(-t * 30)) / 30)) * np.exp(-t * 25)
        else:
            pulse = .3 * np.random.default_rng(index + pattern).normal(size=length) * np.exp(-t * 55)
        if pattern == 2 and index % 4 == 3:
            pulse *= .35
        start = int(when * rate)
        stop = min(len(samples), start + length)
        samples[start:stop] += pulse[:stop - start]
    samples = (samples / max(1., np.abs(samples).max()) * 24000).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(samples.tobytes())


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    snapshot = OUTPUT / "generation.json"
    if snapshot.is_file():
        state = json.loads(snapshot.read_text(encoding="utf-8"))
        assert state["code_hashes"] == code_hashes(), "Frozen validation code changed"
    else:
        prompts = [
            ("handshake", "Two people face each other, shake their right hands, then release and stand still."),
            ("wave", "Two people stand apart and wave their right hands to greet each other."),
            ("walk", "Two people walk side by side at a normal pace."),
            ("dance", "Two people dance together with small steps and synchronized arm movements."),
            ("highfive", "Two people face each other and give each other a high five."),
            ("bow", "Two people face each other, bow politely, then straighten up."),
            ("point", "One person points to the left while the other person turns to look in that direction."),
            ("sidestep", "Two people stand side by side and take a small step to their right, then return."),
        ]
        state = {"code_hashes": code_hashes(), "purpose": "Held-out samples; no algorithm tuning on this batch",
                 "samples": [], "status": "prepared"}
        for index, (name, prompt) in enumerate(prompts):
            state["samples"].append({"name": "validation_" + name, "source": "intergen", "request": {
                "text": prompt, "seed": 26093000 + index, "num_samples": 1, "motion_frames": 180,
                "skin_id": "smpl", "planner_enabled": False, "experiment_group": "motionlint-heldout-20260930",
                "experiment_variant": "frozen-repair-v2"}})
        for index, bpm in enumerate((96, 132)):
            audio = OUTPUT / "audio" / f"original_rhythm_{bpm}bpm.wav"
            rhythm(audio, bpm, index + 1)
            state["samples"].append({"name": f"validation_rhythm_{bpm}", "source": "lodge",
                "audio_provenance": "Locally synthesized percussion test, not an existing music recording",
                "audio_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(), "request": {
                    "lodge_root": str(RUNTIME / "LODGE-main"), "audio_path": str(audio),
                    "song_id": f"v260930_{bpm}", "python_executable": str(RUNTIME / "envs/lodge/Scripts/python.exe"),
                    "mode": "smplx", "fps": 30, "skin_id": "smpl"}})
        _write_json(snapshot, state)
    for sample in state["samples"]:
        assert state["code_hashes"] == code_hashes(), "Frozen validation code changed"
        if sample.get("generation_status") == "failed" and sample["source"] == "lodge" and "_" in sample["request"]["song_id"]:
            sample.setdefault("failed_attempts", []).append({"task_id": sample.pop("task_id"),
                "request": sample["request"].copy(), "result": sample.pop("task_result")})
            # Upstream concat splits filenames at '_'; use an alphanumeric song ID.
            sample["request"]["song_id"] = sample["request"]["song_id"].replace("_", "")
            sample["generation_status"] = "retry_pending"
            _write_json(snapshot, state)
        port = 8001 if sample["source"] == "intergen" else 8002
        base = f"http://127.0.0.1:{port}/v1/{sample['source']}/tasks"
        if not sample.get("task_id"):
            endpoint = "generate" if sample["source"] == "intergen" else "infer-from-audio"
            result = request(base + "/" + endpoint, sample["request"])
            sample["task_id"] = result["task_id"]
            _write_json(snapshot, state)
        print(f"Generating {sample['name']} {sample['task_id']}", flush=True)
        deadline = time.monotonic() + 1800
        while True:
            result = request(base + "/" + sample["task_id"])
            sample["generation_status"] = result["status"]
            sample["generation_message"] = result.get("message", "")
            _write_json(snapshot, state)
            if result["status"] in {"succeeded", "failed"}:
                sample["task_result"] = result
                break
            if time.monotonic() > deadline:
                raise TimeoutError(f"Generation exceeded timeout: {sample['name']}")
            time.sleep(5)
        print(f"{sample['name']}: {result['status']}", flush=True)
        _write_json(snapshot, state)
    state["status"] = "generation_complete"
    _write_json(snapshot, state)


if __name__ == "__main__":
    main()
