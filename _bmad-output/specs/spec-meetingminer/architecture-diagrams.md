# Architecture Diagrams

Companion to `SPEC.md`. High-level pipeline from the product brief.

## Processing pipeline

The puller finalizes each meeting as a write-once drop — recording and/or transcript plus a metadata sidecar with embedded provenance — and notifies MeetingMiner; files landing in the folder alone never ingest. Transcript-only drops (no downloadable recording — most of the real pulled corpus today) skip the Video Lane: their moments carry no screenshot, and a source deep link stands in for video replay. The skip is reversible — a recording recovered later arrives as a second drop against the same meeting and runs the Video Lane alone, attaching its output to the existing moments.

```
Drop Folder (write-once puller drops:
recording and/or transcript
+ metadata sidecar w/ provenance)
        │  puller notifies MM
        ▼
Source Adapters
        │
        ▼
Pipeline Orchestrator
        │
 ┌──────┼──────────┐
 ▼      ▼          ▼
Video   Audio   Metadata
Lane    Lane    Extraction
 └──────┼──────────┘
        ▼
Evidence Builder
        │
        ▼
Evidence Bundle
        │
 ┌──────┴──────────┐
 ▼                 ▼
Viewer      Domain Database (system of record:
            domain graph + artifacts,
            published and unpublished)
                   │  derived projections
         ┌─────────┴─────────┐
         ▼                   ▼
   Full-text Doc       GraphRAG index
   Index               (over domain graph)
         └─────────┬─────────┘
                   ▼
         Search + RAG + Chat
```

## Artifact re-indexing loop

Published artifacts flow back into the retrieval stores; unpublished ones never do.

```
Moments ──▶ Extraction ──▶ Artifacts in Domain DB (unpublished —
                                  │   never projected to stores)
                                  │  per-moment human approval
                                  ▼
                    Published (folder + local git)
                                  │
                                  ▼
              Projected into Retrieval Stores
              (ADRs, action items, arch docs become
               searchable, citable knowledge)
```
