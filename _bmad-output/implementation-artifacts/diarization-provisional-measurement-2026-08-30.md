# Diarization provisional measurement — in-process pyannote on this Mac

**Date:** 2026-08-30
**Code under test:** `main` at `d1abe8a` (story 7.1 landed at `bb50c7b`) — the
pyannote adapter behind the `Diarizer` port, with the owner-ruled telemetry
disabling.
**Run host:** MacBook Pro `Mac16,5`, Apple M4 Max, 16 cores (12 performance /
4 efficiency), 128 GB unified memory, macOS 26.6.2 (25G83).
**Engine:** `pyannote/speaker-diarization-community-1`, pyannote.audio 4.0.7,
torch 2.13.0, torchcodec 0.16.0.
**Ran in:** worktree `meetingminer-wt/7-1-measure`, in-process. The shared
worker and api were never started (standing restart hold on the worker). No
store was written.

## Why this document is "provisional"

Story 7.1's acceptance criterion asks for a 60-minute recording. **No
60-minute recording exists.** The corpus holds exactly two recordings:

| drop | duration |
|---|---|
| `2026-08-20-q3-architecture-review-4c645e24` | 434.1 s (~7.2 min) |
| `2026-08-20-scripted-ui-demo-orders-module-8a90e644` | 247.0 s (~4.1 min) |

So this is not the Story 7.1 measurement. It is a **capacity measurement plus
an end-to-end smoke check**, and the two runs below carry very different
weight:

- The **synthetic ~60-minute run is the load-bearing number.** It is what
  answers the capacity question this document exists to answer.
- The **real 434 s run is a smoke check only.** It proves the adapter runs
  end to end on genuine meeting audio and produces plausibly-shaped output.
  **No turn-quality conclusion is drawn from it**, because a two-recording
  corpus cannot support one.

## The question this measurement answers

It is no longer "is pyannote fast enough to be the default". The LAN GPU host
already serves diarization and wins outright on speed while needing no
Hugging Face token (backlog B-36 covers wiring it):

> `POST http://10.77.0.120:8000/diarize`, NeMo `ClusteringDiarizer`
> (`vad_multilingual_marblenet` + `titanet_large`): 60 minutes of audio in
> **57.53 s** (RTF 0.0160, peak 8,817 MiB) with ASR resident; verified against
> a real 247 s meeting in 14 s → 82 turns, 2 speakers.
> (Figures cross-checked against `build-prompt-b36-remote-diarizer-2026-08-30.md`.)

The open question is therefore: **is in-process pyannote on this Mac a viable
_fallback_ when the GPU box is unavailable?** That matters because VM120 is
`onboot=0` and shares its RTX 4080 with VM116 — deliberately intermittent
infrastructure.

## Exact commands

```bash
# 1. Install the optional extra (in the measurement worktree)
uv sync --project server --extra diarize

# 2. Bind the engine for this run only (local edit, reverted afterwards)
#    config.yaml:  diarizer.engine: noop  ->  pyannote

# 3. Extract audio exactly as the pipeline does (16 kHz mono PCM WAV),
#    via the project's own meetingminer.pipeline.media.extract_audio
uv run --project server python -c "
from pathlib import Path
from meetingminer.pipeline import media
media.extract_audio(Path('.../2026-08-20-q3-architecture-review-4c645e24/recording.mp4'),
                    Path('\$TMPDIR/diar/real.wav'))"

# 4. Build the SYNTHETIC 60-minute file: 9 concatenated copies, trimmed to 3600 s
for i in $(seq 1 9); do echo "file '$TMPDIR/diar/real.wav'" >> list.txt; done
ffmpeg -nostdin -v error -y -f concat -safe 0 -i list.txt -t 3600 -c copy synth60.wav

# 5. Run the measurement in-process, through the real binding path
#    (load_config -> build_diarizer -> diarizer.diarize)
set -a && . ./.env && set +a
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib \
  uv run --project server python measure_diarization.py \
    real.wav synth60.wav tiny.wav report-full.json

# 6. Revert the config binding
#    config.yaml:  diarizer.engine: pyannote  ->  noop
```

## Device: it ran on CPU, not MPS

MPS placement is a recorded deferral for story 7.1. Reporting what really
happened rather than what was intended:

| probe | value |
|---|---|
| `_inferences['_segmentation'].device` | **`cpu`** |
| `_inferences['_embedding'].device` | **`cpu`** |
| model parameter devices | **`{'cpu': 52}`** — every parameter on CPU |
| `torch.backends.mps.is_available()` | `True` |
| `torch.cuda.is_available()` | `False` |
| `torch.get_num_threads()` | 12 |

The adapter never calls `Pipeline.to(...)`, and the community-1 model config
carries no `device` key, so the pipeline stays on CPU. **MPS was available and
went unused.** Every number below is a 12-thread CPU number; an MPS run is
unmeasured and no figure here should be extrapolated to one.

Model load (weights already in the Hugging Face cache): **1.37 s**. This is the
once-per-process cost; the adapter defers it to the first `diarize()` call.

## Measurement 1 — SYNTHETIC ~60 minutes (the load-bearing number)

**Synthetic. The audio is the 434 s recording looped 9× and trimmed to
3600.000 s.** Looped audio does not represent natural turn-taking: the same
voices, the same phrases and the same acoustics recur every 7.2 minutes. It
exists to measure wall-clock and memory scaling and **nothing else**. Its turn
and speaker-tag counts are artifacts of the loop and say nothing about
accuracy. (The project's CUDA ASR handoff used this same technique with the
same caveat; this follows that precedent.)

| metric | value |
|---|---|
| audio duration | 3600.000 s |
| **wall-clock** | **2151.38 s (35 min 51 s)** |
| **real-time factor** | **0.5976** |
| throughput | 1.67× real time |
| **peak process RSS** | **4041.1 MB** |
| device | CPU (12 threads) |
| turns | 791 |
| distinct speaker tags | 6 |

Memory did not scale with duration: the 60-minute file peaked at 4041.1 MB
against 3638.4 MB for the 434 s file — a 8.3× longer input for 1.11× the peak
RSS. The pipeline streams segmentation in windows, so duration drives time,
not footprint.

## Measurement 2 — REAL 434 s corpus recording (smoke check only)

**Real meeting audio**, `2026-08-20-q3-architecture-review-4c645e24`.

| metric | value |
|---|---|
| audio duration | 433.984 s |
| wall-clock | 274.40 s |
| real-time factor | 0.6323 |
| throughput | 1.58× real time |
| peak process RSS | 3638.4 MB |
| device | CPU (12 threads) |
| turns | 90 |
| distinct speaker tags | 3 (`SPEAKER_00`, `SPEAKER_01`, `SPEAKER_02`) |
| total speech detected | 338.2 s of 434.0 s |
| known participant roster | 2 (`Goeke, Timothy`, `Tiffany Goeke`) |

The run was repeated and reproduced closely (274.40 s / RTF 0.6323 against
275.78 s / RTF 0.6355 on the first pass), so the wall-clock figure is stable.

**Tag count against roster — stated, not concluded.** pyannote emitted 3
speaker tags where the roster names 2 participants. That is recorded as an
observation and **no quality conclusion is drawn from it**: one recording, of
one meeting, with one speaker dominating (815 of 866 transcript words) is not
evidence about diarization accuracy in either direction. It is a flag for the
real measurement to resolve, not a finding. A tag is a placeholder by the
never-guess rule and resolves to no participant, so an extra tag is not a
correctness bug in the pipeline — it is a quality question that needs a
corpus.

## Telemetry stayed disabled — verified three ways

The owner ruled this egress closed. The adapter calls
`set_telemetry_metrics(False)` before `Pipeline.from_pretrained`. Verified:

1. **State check.** After the model load and again after both runs,
   `PYANNOTE_METRICS_ENABLED` was `"false"` and
   `pyannote.audio.telemetry.metrics.is_metrics_enabled()` returned `False`.
   pyannote's `track_model_init` / `track_pipeline_init` /
   `track_pipeline_apply` are all gated on that predicate, so no span was ever
   opened.
2. **Exporter tripwire.** `OTLPSpanExporter.export` was wrapped for the whole
   run to record any call. **Zero calls.**
3. **Socket-level tap.** `socket.getaddrinfo` and `socket.socket.connect` were
   wrapped for the whole process. The only host resolved was
   `huggingface.co`, and the only TCP connect was to its address on :443
   (the model fetch). **`otel.pyannote.ai` was never resolved and never
   connected to.**

## Environment finding: the extra does not run out of the box here

Worth recording because it will bite the next person. The install itself
succeeds, but the first `diarize()` call fails on this Mac:

```
OSError: Could not load this library:
  .../torchcodec/libtorchcodec_core9.dylib
  Library not loaded: @rpath/libavutil.61.dylib
```

pyannote 4 decodes audio through torchcodec, which dlopens FFmpeg's shared
libraries. This host has Homebrew FFmpeg 9.0.1 (`libavutil.61`), which
torchcodec 0.16.0's `core9` build does want — but `@rpath` does not include
`/opt/homebrew/lib`, so all of `core9…core4` fail in turn and diarization dies
before any inference. Setting `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`
resolves it, and every number in this document was produced with that set.

Two consequences if pyannote is ever wired to the worker: the worker's
environment needs that variable, and `nohup` (or any SIP-protected launcher)
silently strips `DYLD_*` on exec, so it must be set in the process that
actually execs Python.

## The comparison

| | LAN GPU (NeMo, B-36) | This Mac (pyannote, CPU) |
|---|---|---|
| 60 min of audio | **57.53 s** | **2151.38 s (35 min 51 s)** |
| real-time factor | **0.0160** | **0.5976** |
| peak memory | 8,817 MiB (GPU-resident, ASR loaded) | 4,041 MB (host RSS) |
| device | RTX 4080 | CPU only; MPS available, unused |
| gated token needed | no | yes (Hugging Face, licence accepted) |
| availability | intermittent (VM120 `onboot=0`, 4080 shared with VM116) | always |

The Mac is **37× slower** than the LAN path (2151.38 / 57.53 = 37.4×; the RTF
ratio agrees at 37.4×). The memory figures are not the same resource — 8,817
MiB is GPU VRAM with ASR co-resident, 4,041 MB is host RSS — so they should
not be read as a like-for-like win for the Mac.

## Is it a viable fallback?

**Yes — a 60-minute meeting is tolerable on this Mac when the GPU host is
down, but only as an explicitly-chosen fallback, never a silent one.** It
completes in about 36 minutes at 1.67× real time inside 4 GB of RAM, which is
fine for unattended or overnight backlog draining and clearly unacceptable for
anything interactive; diarization should not simply fail by name and wait when
the alternative is a run that finishes within the hour.

The "never silent" half of that sentence is not a style preference. The owner
has already ruled against silent fallbacks in this project (the LLM fallback
ruling: failures must surface visibly). A diarizer that quietly degrades from
57 seconds to 36 minutes is exactly the kind of invisible 37× cost that ruling
exists to prevent. If this path is wired, the substitution must be named in
the job record the way the OCR engine substitution already is.

## What the real Story 7.1 measurement needs

This document does not close Story 7.1's acceptance criterion. To close it:

1. **A recording of genuine 60-minute length**, from the owned Teams sandbox
   corpus being rebuilt — not looped audio. Only that retires the synthetic
   caveat.
2. **A known participant roster of more than two**, with more than one
   substantive speaker, so the tag-count comparison carries information. The
   current corpus's speaker distribution (815 words against 51) cannot.
3. **Turn-quality measured against a reference**, not inferred from tag count
   — diarization error rate, or at minimum hand-checked turn boundaries at
   known speaker changes. The 3-tags-vs-2-roster observation above is the
   open question this would answer.
4. **A decision on MPS placement.** Every figure here is CPU. If MPS
   placement lands, the capacity numbers must be re-measured, not scaled —
   nothing here supports predicting an MPS RTF.
5. **The same run against the B-36 LAN path**, on the same audio, so the
   engine comparison is like-for-like rather than this document's comparison
   of two different measurements taken on two different inputs.

## Reproducing

The harness is `measure_diarization.py` (session scratchpad; not committed —
it is a measurement tool, not a project artifact). It goes through
`load_config()` → `build_diarizer()` → `diarizer.diarize()`, so it exercises
the shipped binding path rather than calling pyannote directly, and it carries
the telemetry state check, the exporter tripwire and the socket tap described
above. `config.yaml`'s `diarizer.engine` binding was reverted to `noop` after
the run; nothing was committed to any story branch.
