# The LAN inference host — build specification

MeetingMiner runs its models locally by default. Transcription works on the
development Mac with no extra hardware, and diarization has a bundled `noop`
engine, so **nothing here is required to build or run the application** — see
the README's Quick start.

This document specifies the optional GPU host the project binds for speech
work, so a reader can understand the deployment shape without building one.
It is a specification, not an install guide, and the operational runbook (SSH
keys, host addresses, snapshot names) is kept outside this repository.

## Why it exists

Two ports in the architecture (AD-8) can be served remotely, and one of them
had no working engine at all:

- **`Stt`** — transcription. Works locally via `mlx-whisper` on Apple Silicon.
  A remote engine is a speed optimisation, nothing more.
- **`Diarizer`** — who spoke when. The bundled `noop` engine returns nothing,
  and the alternative in-process engine needs a licence-gated model. **A remote
  NeMo engine needs no such licence**, which made it the shortest route to real
  speaker attribution.

This matters for the demo corpus: public meeting recordings on YouTube carry
auto-generated captions, and auto-captions have **no speaker labels**. Without
diarization those meetings ingest as unattributed text.

## The machine

A GPU passed through to a Linux guest on a hypervisor:

| | |
|---|---|
| Guest OS | Ubuntu 24.04 LTS — its default Python 3.12 is what the ASR wheels want; newer distros have no wheels yet |
| GPU | NVIDIA RTX 4080 (16 GB), passed through as one PCI device with its HDMI-audio function |
| Guest resources | 12 vCPU, 32 GiB RAM, ~128 GB disk |
| Driver / toolkit | NVIDIA driver 595.84, CUDA 12.9 |
| Runtime | PyTorch 2.13 on CUDA, `nemo_toolkit[asr]` |
| ASR model | `nvidia/parakeet-tdt-0.6b-v3` (multilingual) |
| Diarization | NeMo `ClusteringDiarizer` — `vad_multilingual_marblenet` + `titanet_large` |
| Service | FastAPI/Uvicorn, one worker, under systemd so it survives reboot |

## The HTTP contract

MeetingMiner talks to remote inference as a **client of a model server**. It
never opens a shell on the host or runs a CLI there.

```
GET  /health
  -> {"ok": true, "ready": true, "model": "...", "device": "...",
      "reason": null, "diarization": {"model": "...", "ready": true, ...}}

POST /transcribe   multipart: file=<audio>
  -> {"segments": [{"start": 0.0, "end": 4.2, "text": "..."}],
      "language": "...", "model": "...", "processed_ranges": [...]}

POST /diarize      multipart: file=<audio>
  -> {"turns": [{"start": 0.46, "end": 4.57, "speaker": "SPEAKER_00"}],
      "model": "..."}
```

Five properties of that contract change the application's output if violated,
because the caller maps the responses onto frozen internal types without
re-checking them:

1. **Every segment and turn carries real `start`/`end` times, never a fabricated
   one.** The pipeline assigns each transcript segment the diarization tag with
   the longest overlap, so a systematically wrong or invented span silently
   mis-attributes speech instead of failing.
2. **`speaker` is a recording-local `SPEAKER_NN` tag and identifies nobody.** It
   is never stable across requests. Only a provided transcript's own labels, or
   an operator's explicit assignment, resolve a tag to a person (AD-13).
3. **Silence is a valid request.** An empty `turns` list returns HTTP 200 — the
   same semantics the bundled `noop` engine has. An empty result produced by a
   *failure* is a defect; an empty result from a healthy host is an answer.
4. **Overlapping speech is resolved by dropping the shorter measured span**,
   never by inventing a split timestamp.
5. **Errors return a body with a reason** rather than hanging. A two-hour job
   must not be killed by a blip, and the caller treats a named failure as data.

The two endpoints share one inference lock so they queue rather than contend
for the GPU. MeetingMiner's worker is single-threaded and runs transcription to
completion before diarization on the same file, so it never asks for both at
once anyway.

## Measured performance

With the ASR model resident:

| Workload | Audio | Elapsed | Peak GPU |
|---|---|---|---|
| Transcription | 10 min | ~2.4 s | — |
| Transcription (stress series) | 10 min ×15 | — | 11,208 MiB |
| Diarization | 10 min | 15.4 s | 3,461 MiB |
| Diarization | 60 min | 57.5 s | 8,817 MiB |

For comparison, the same 60 minutes of diarization takes **35 min 51 s**
in-process on an M4 Max — CPU-only, since the framework did not place work on
Metal — roughly **37× slower**. That gap is why the remote engine is the
default speech path when the host is scheduled, and the local engine a
deliberate, explicitly-configured fallback rather than an automatic one.

## Operational constraints the design accounts for

The host is **operator-scheduled infrastructure, not a best-effort
dependency**. It does not start with its hypervisor, and it shares its GPU with
another guest that must not run at the same time. So MeetingMiner treats it as
legitimately absent much of the time:

- When the GPU is unavailable the service stays reachable, reports
  `ready: false` with a reason, and returns HTTP 503 carrying that same reason.
- The adapter raises a **named error** carrying the endpoint, the model and the
  host's own reason, and **never falls back to another engine**. A meeting
  silently ingested without speaker turns, when diarization was asked for, is
  precisely the kind of silent failure this project refuses.
- The per-request timeout is finite and validated as such, so a wedged host
  cannot hang a pipeline stage indefinitely.

## How the application binds it

Where inference runs is a configuration change, never a code change (AD-9,
AD-10). In `config.yaml`:

```yaml
diarizer:
  engine: remote-http     # noop | pyannote | remote-http
  base_url: http://<host>:8000
  timeout_seconds: 900
```

`noop` is the committed default, so a fresh clone runs with no GPU host and no
speaker attribution. Binding `remote-http` is the only step needed to use one.
