# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""speaker -- voice-bridge extension: is the person talking the operator?

Reached at /inspect/api/voice/ext/speaker/<op> (ROUTES below). Runs in the
AGENTS venv and owns no model: the ECAPA weights live in their own CPU venv
behind `speaker_verify_worker.py`, which this module starts lazily and restarts
if it died. That keeps torch-CPU out of the kanban process and VRAM out of the
question.

What it is, honestly: a CONVENIENCE FILTER, not security. Cosine distance
between ECAPA embeddings tells the operator's voice from a stranger's; it
cannot tell the operator from a RECORDING of the operator. Anyone who can play
audio at the microphone passes. Treat `accepted` as "probably the right person
in the room", never as authentication.

Ops
    enrol   POST {name, audio_b64, mime} | {name, wav}  -> {ok, name, slug, seconds, n_windows}
            Needs >= MIN_ENROL_SECONDS of audio. Cut into 4 s windows, one
            embedding each, stored as the L2-normalised mean.
    verify  POST {audio_b64, mime} | {wav}  -> {ok, name, score, accepted, gate, threshold}
            score = best cosine against every enrolled speaker. With the gate
            off, `accepted` is True for everyone and the score is still
            reported, so the operator can tune the threshold from real numbers.
    list    GET  -> {ok, speakers: [{name, slug, n_windows, created, seconds}]}
    delete  POST {slug|name} -> {ok, deleted}
    config  GET  -> {ok, speaker_threshold, speaker_gate}
            POST {speaker_threshold?, speaker_gate?} -> same, after writing
"""
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(HERE, "data", "runtime", "voice_bridge")
SPEAKERS_DIR = os.path.join(RUNTIME, "speakers")
CONFIG_PATH = os.path.join(RUNTIME, "config.json")

WORKER_PY = os.path.join(HERE, "speaker_verify_worker.py")
WORKER_VENV_PY = str(paths.ZYG_MODELS_DIR / "speaker_verify" / ".venv" / "bin" / "python")
WORKER_IDLE_S = 600

# 20 s is the brief's floor and it is the right one: below ~15 s the mean
# embedding still carries the sentence more than the speaker.
MIN_ENROL_SECONDS = 20.0
WINDOW_S = 4.0
MIN_VERIFY_SECONDS = 0.5

DEFAULT_THRESHOLD = 0.55
DEFAULT_GATE = True

# Same table as voice_stt: the browser sends webm/opus, everything else is a
# file the operator pointed us at.
_MIME_SUFFIX = {
    "audio/webm": ".webm", "video/webm": ".webm",
    "audio/ogg": ".ogg", "application/ogg": ".ogg", "audio/opus": ".ogg",
    "audio/wav": ".wav", "audio/wave": ".wav", "audio/x-wav": ".wav",
    "audio/mp4": ".mp4", "video/mp4": ".mp4", "audio/m4a": ".mp4",
    "audio/x-m4a": ".mp4", "audio/mpeg": ".mp3", "audio/flac": ".flac",
}

_lock = threading.Lock()
_proc = None


class SpeakerError(RuntimeError):
    """Bad input, or the worker could not answer."""


# ---------------------------------------------------------------- worker seam

def _worker_alive():
    return _proc is not None and _proc.poll() is None


def _start_worker():
    """(Re)start the embedding worker in its own CPU venv. Caller holds _lock."""
    global _proc
    if _worker_alive():
        return _proc
    python = WORKER_VENV_PY if os.path.exists(WORKER_VENV_PY) else "python3"
    _proc = subprocess.Popen(
        [python, WORKER_PY, "--idle", str(WORKER_IDLE_S)],
        cwd=HERE, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, bufsize=1,
    )
    return _proc


def _ask(req, retry=True):
    """One request/response round trip, restarting a dead worker once."""
    global _proc
    with _lock:
        proc = _start_worker()
        try:
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
        except (BrokenPipeError, ValueError, OSError):
            line = ""
        if not line:
            # Worker died or timed out on idle. One clean retry, then give up.
            try:
                proc.kill()
            except Exception as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            _proc = None
            if not retry:
                raise SpeakerError("speaker worker did not answer")
    if not line:
        return _ask(req, retry=False)
    try:
        resp = json.loads(line)
    except ValueError as exc:
        raise SpeakerError("speaker worker sent junk: %r" % line[:120]) from exc
    if not resp.get("ok"):
        raise SpeakerError(str(resp.get("error") or "speaker worker refused"))
    return resp


def embed_wav(path):
    """192-float ECAPA embedding of a wav file. The seam the tests patch."""
    return _ask({"op": "embed", "wav": os.path.abspath(path)})["emb"]


# ------------------------------------------------------------------ audio in

def _suffix_for(mime):
    return _MIME_SUFFIX.get((mime or "").split(";")[0].strip().lower(), ".webm")


def _to_wav16k(src, dst):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SpeakerError("ffmpeg not found on PATH")
    proc = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         "-i", src, "-ac", "1", "-ar", "16000", "-f", "wav", dst],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not os.path.exists(dst) or not os.path.getsize(dst):
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        tail = " | ".join(err.splitlines()[-3:])[:300] or "no stderr"
        raise SpeakerError("ffmpeg could not decode the audio (rc=%d): %s"
                           % (proc.returncode, tail))


def _payload_to_wav(payload, tmpdir):
    """Accept audio_b64+mime OR a wav path; return a 16 kHz mono wav path."""
    dst = os.path.join(tmpdir, "in16k.wav")
    b64 = payload.get("audio_b64")
    if b64:
        raw = str(b64)
        if "," in raw[:80] and raw[:5] == "data:":      # data: URL from the panel
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw, validate=False)
        except Exception as exc:
            raise SpeakerError("audio_b64 is not base64: %s" % exc) from exc
        if not data:
            raise SpeakerError("audio_b64 decoded to nothing")
        src = os.path.join(tmpdir, "in" + _suffix_for(payload.get("mime")))
        with open(src, "wb") as fh:
            fh.write(data)
        _to_wav16k(src, dst)
        return dst
    path = payload.get("wav") or payload.get("path")
    if not path:
        raise SpeakerError("need audio_b64 (with mime) or wav")
    path = os.path.abspath(os.path.join(HERE, str(path)))
    if not os.path.exists(path):
        raise SpeakerError("wav not found: %s" % path)
    _to_wav16k(path, dst)
    return dst


def _wav_seconds(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate() or 16000)


def _write_window(src, dst, start_s, length_s):
    """Copy [start, start+length) of a 16 kHz mono wav into its own file."""
    with wave.open(src, "rb") as w:
        rate = w.getframerate() or 16000
        w.setpos(int(start_s * rate))
        frames = w.readframes(int(length_s * rate))
        params = w.getparams()
    with wave.open(dst, "wb") as out:
        out.setnchannels(params.nchannels)
        out.setsampwidth(params.sampwidth)
        out.setframerate(rate)
        out.writeframes(frames)


# --------------------------------------------------------------- vector maths

def _l2(vec):
    norm = sum(x * x for x in vec) ** 0.5
    if norm <= 0:
        raise SpeakerError("degenerate embedding (zero norm)")
    return [x / norm for x in vec]


def _mean_l2(vectors):
    width = len(vectors[0])
    return _l2([sum(v[i] for v in vectors) / len(vectors) for i in range(width)])


def _cosine(a, b):
    """Cosine of two vectors. Stored embeddings are already unit length."""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


# ------------------------------------------------------------------- storage

def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")
    if not s:
        raise SpeakerError("name must contain a letter or a digit")
    return s[:48]


def _load_speakers():
    out = []
    if not os.path.isdir(SPEAKERS_DIR):
        return out
    for fn in sorted(os.listdir(SPEAKERS_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(SPEAKERS_DIR, fn), "r", encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        if rec.get("emb"):
            rec.setdefault("slug", fn[:-5])
            out.append(rec)
    return out


def read_config():
    cfg = {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh) or {}
    except (OSError, ValueError):
        cfg = {}
    try:
        threshold = float(cfg.get("speaker_threshold", DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        threshold = DEFAULT_THRESHOLD
    gate = cfg.get("speaker_gate", DEFAULT_GATE)
    return {"speaker_threshold": threshold, "speaker_gate": bool(gate)}


def _write_config(updates):
    os.makedirs(RUNTIME, exist_ok=True)
    cfg = {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh) or {}
    except (OSError, ValueError):
        cfg = {}
    cfg.update(updates)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, sort_keys=True)
    os.replace(tmp, CONFIG_PATH)
    return read_config()


# --------------------------------------------------------------------- routes

def enrol(payload, method="POST"):
    name = str(payload.get("name") or "").strip()
    if not name:
        return {"error": "enrol needs a name", "code": 400}
    try:
        slug = _slug(name)
    except SpeakerError as exc:
        return {"error": str(exc), "code": 400}

    tmpdir = tempfile.mkdtemp(prefix="vb_spk_enrol_")
    try:
        wav = _payload_to_wav(payload, tmpdir)
        seconds = _wav_seconds(wav)
        if seconds < MIN_ENROL_SECONDS:
            return {"error": "enrol needs at least %.0f s of speech, got %.1f s"
                             % (MIN_ENROL_SECONDS, seconds),
                    "seconds": round(seconds, 2),
                    "min_seconds": MIN_ENROL_SECONDS, "code": 400}
        embeddings = []
        start = 0.0
        idx = 0
        while start + WINDOW_S <= seconds + 1e-6:
            piece = os.path.join(tmpdir, "w%03d.wav" % idx)
            _write_window(wav, piece, start, WINDOW_S)
            embeddings.append(_l2(embed_wav(piece)))
            start += WINDOW_S
            idx += 1
        if not embeddings:
            return {"error": "no usable %.0f s window in the audio" % WINDOW_S, "code": 400}
        record = {
            "name": name,
            "slug": slug,
            "emb": _mean_l2(embeddings),
            "n_windows": len(embeddings),
            "seconds": round(seconds, 2),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": "speechbrain/spkrec-ecapa-voxceleb",
        }
        os.makedirs(SPEAKERS_DIR, exist_ok=True)
        path = os.path.join(SPEAKERS_DIR, slug + ".json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(record, fh)
        os.replace(tmp, path)
        return {"ok": True, "name": name, "slug": slug,
                "n_windows": record["n_windows"], "seconds": record["seconds"]}
    except SpeakerError as exc:
        return {"error": str(exc), "code": 400}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def verify(payload, method="POST"):
    cfg = read_config()
    speakers = _load_speakers()
    if not speakers:
        return {"ok": True, "name": None, "score": 0.0,
                "accepted": not cfg["speaker_gate"],
                "gate": cfg["speaker_gate"], "threshold": cfg["speaker_threshold"],
                "reason": "nobody is enrolled"}
    tmpdir = tempfile.mkdtemp(prefix="vb_spk_verify_")
    try:
        t0 = time.time()
        wav = _payload_to_wav(payload, tmpdir)
        seconds = _wav_seconds(wav)
        if seconds < MIN_VERIFY_SECONDS:
            return {"error": "too short to identify (%.2f s)" % seconds,
                    "seconds": round(seconds, 2), "code": 400}
        probe = _l2(embed_wav(wav))
        scored = sorted(((_cosine(probe, s["emb"]), s) for s in speakers),
                        key=lambda p: p[0], reverse=True)
        score, best = scored[0]
        accepted = bool(score >= cfg["speaker_threshold"]) if cfg["speaker_gate"] else True
        return {"ok": True, "name": best["name"], "slug": best.get("slug"),
                "score": round(float(score), 4), "accepted": accepted,
                "gate": cfg["speaker_gate"], "threshold": cfg["speaker_threshold"],
                "seconds": round(seconds, 2), "ms": int((time.time() - t0) * 1000),
                "others": [{"name": s["name"], "score": round(float(sc), 4)}
                           for sc, s in scored[1:4]]}
    except SpeakerError as exc:
        return {"error": str(exc), "code": 400}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def list_(payload, method="GET"):
    rows = [{"name": s.get("name"), "slug": s.get("slug"),
             "n_windows": s.get("n_windows"), "created": s.get("created"),
             "seconds": s.get("seconds")}
            for s in _load_speakers()]
    return {"ok": True, "speakers": rows, "count": len(rows)}


def delete(payload, method="POST"):
    want = payload.get("slug") or payload.get("name")
    if not want:
        return {"error": "delete needs slug or name", "code": 400}
    try:
        slug = _slug(want)
    except SpeakerError as exc:
        return {"error": str(exc), "code": 400}
    path = os.path.join(SPEAKERS_DIR, slug + ".json")
    if not os.path.exists(path):
        return {"error": "no speaker %r" % slug, "code": 404}
    os.remove(path)
    return {"ok": True, "deleted": slug}


def config(payload, method="GET"):
    if str(method).upper() != "POST":
        cfg = read_config()
        cfg["ok"] = True
        return cfg
    updates = {}
    if "speaker_threshold" in payload:
        try:
            value = float(payload["speaker_threshold"])
        except (TypeError, ValueError):
            return {"error": "speaker_threshold must be a number", "code": 400}
        if not -1.0 <= value <= 1.0:
            return {"error": "speaker_threshold is a cosine: keep it in -1..1", "code": 400}
        updates["speaker_threshold"] = value
    if "speaker_gate" in payload:
        raw = payload["speaker_gate"]
        if isinstance(raw, str):
            raw = raw.strip().lower() not in ("0", "false", "no", "off", "")
        updates["speaker_gate"] = bool(raw)
    if not updates:
        return {"error": "nothing to set (speaker_threshold, speaker_gate)", "code": 400}
    cfg = _write_config(updates)
    cfg["ok"] = True
    return cfg


ROUTES = {"enrol": enrol, "verify": verify, "list": list_,
          "delete": delete, "config": config}
