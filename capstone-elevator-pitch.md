# MeetingMiner — Elevator Pitch (Week 2 Live Session, ~2–3 min)

**Format:** talking points, not a script. Bold lines are the beats; speak the rest naturally.

---

## The hook (~25s)

**Every AI meeting tool today is a summarizer — it hands you prose you have to take on faith. I'm building the opposite: an evidence engine.**

MeetingMiner turns meetings into trustworthy engineering artifacts. I review 60–90 minute recorded functional demos of enterprise systems; everything I need is in the video — every screen shown, every decision made — but extracting it means scrubbing, screenshotting, and pasting fragments into an LLM. Days per demo, with silent misses.

## What I'm building (~40s)

**First slice: a local pipeline that turns a demo recording into a browsable, evidence-grounded record of the demo.**

- Input: paste the meeting recap URL — MeetingMiner pulls the recording and transcript automatically. (A local file works too; ingestion is a pluggable port.)
- Output: every distinct UI screen shown — captured, cropped to the app window, labeled slide vs. live UI — each married to a confirmed, speaker-attributed snippet of what was said about it.
- All in a viewer app where any screen can replay the original video moment on demand.
- And every processed meeting joins a searchable knowledge base: type a phrase, find every moment it was said across all your meetings, and jump straight to the video of it being said.

Capture is signal-driven, not clock-based: it fuses signals the recording already carries — keyframes, packet-size deltas, audio silence, transcript rhythm — so it only decodes frames where something actually changed. It transcribes locally and merges its own ASR against the provided transcript to confirm and improve it, never erasing the original.

## Why it fits the theme (~50s)

**The core guarantee — every screen captured, none missed — is exactly the kind of promise you can't get by trusting a model.** The stance in six words: AI proposes, provenance verifies, humans approve.

Three commitments, straight from the theme:

- **Deterministic core, probabilistic contributors.** Capture decisions, cropping, merge, and alignment are deterministic code. Models feed evidence *into* that core — they never own an outcome. Anything auto-applied is verifiable in one click via source-clip replay.
- **Model-swap safe by construction.** No call site names a vendor or engine. ASR and LLM access go through ports/adapters selected by config — in-process, LAN host, or allowlisted cloud — with typed results that fail visibly, not silently. Swap the engine, rerun the evals, ship.
- **Evals are the load-bearing wall — with ground truth by construction.** I'm standing up my own M365 tenant as a controlled meeting lab: real Teams demos performed to a script, so I know every screen shown, every word said, and every change requested *before the recording exists* — with hard cases planted on purpose. Primary metric: capture recall — 100% of scripted screens present. The harness sweeps every tunable and gates every change against measured recall, then validates on real held-out NDA recordings so I'm not overfitting to the lab.

## Where it stands & where it goes (~20s)

**Spec, architecture, and eval plan are already documented** — 10 capabilities, 19 binding architecture decisions. Weeks 3–4: ground-truth labeling, a signal-weight POC, and the end-to-end slice. The vision goes deeper — mining user stories, ADRs, and migration plans with per-claim provenance — and wider, to discovery calls, postmortems, and design sessions. But none of it works unless capture is provably complete. That's this capstone.

---

## If asked (backup answers)

- **"MeetingMiner" but only demos?** The name is the vision; the capstone is the slice where the eval target is crisp. On a screen-share demo, "did we capture every screen" is measurable against ground truth. Transcript-only meetings inherit the same evidence spine later, but they don't have a recall metric this sharp — and a sharp metric is the point of this program.
- **Why solo?** Scope is pre-planned and sliced; the spec's non-goals keep the 4-week window honest.
- **Riskiest part?** The 75% distinct-screen threshold — modals and partial-form changes may need a secondary lower-threshold trigger; first POC question, answered against ground truth, not intuition. (Graph auth is already de-risked: I have a working Graph pull script and I administer the tenant, so consent is configuration — and the local-file adapter is the fallback regardless.)
- **Will it mine requirements?** Stretch goal. The scripted meetings have planted change requests with known answers, so the mining eval set exists from day one — if the committed slice lands early, I'll run a first extraction pass and score recall against the script. But mining only counts if capture is provably complete; that's the commitment.
- **Chat with your meetings?** Second stretch goal, behind mining. The transcript knowledge base is RAG-ready, and the LLM port already exists — chat is retrieval plus synthesis where every answer cites timecodes and every citation replays its moment. The scripted corpus even gives me retrieval ground truth: planted phrases with known timestamps. Committed scope stops at deterministic search-to-replay; grounded chat is the designed next step.
- **Why local-first?** Recordings are under NDA. Fully local by default; an endpoint allowlist governs any egress — only derived data, only to sanctioned providers.
- **Performance?** Two-tier video path: demux-only signal scan proposes candidates (no full decode), decode only at candidates. That's how 90 minutes of 1080p stays tractable.
