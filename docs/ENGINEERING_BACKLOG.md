# Engineering Backlog — Pipeline Gap Analysis and Work Ledger


**Purpose**: Benchmarked against production-grade RAG services, this is a gap analysis of the entire pipeline (document parsing → ASR → chunking →
embedding → retrieval/query → performance/platform). Each item has an ID (BL-xx), current-state evidence
(traceable to code), the gap, the approach, **acceptance criteria**, and dependencies — traceable and checkable off.
The Status column is updated as work progresses; completed items move to the "Completed" section at the end. Baseline date: 2026-09-02.

## Execution Order (Overview)

| Wave | Items | Rationale |
|---|---|---|
| **In progress** (feat/asr-provider) | BL-06 ASR config, BL-07 AsrProvider interface, BL-21 import-cycle guard | Foundation for swapping ASR |
| **Wave 1 (P0)** | BL-01 RAG eval harness, BL-02 ASR eval set | **Prerequisite for all model/tuning decisions** — without it, swapping in FireRedASR, A/B embedding, or tuning ef_search cannot be validated |
| **Wave 2** | BL-08 FireRedASR, BL-05 metadata enrichment, BL-12 embedding A/B, BL-14 ef_search, BL-16 metrics, BL-18 queue persistence | P1, each independent and parallelizable |
| **Wave 3 (P2)** | Remainder | Optimizations and experiments once the harness and measurements are in place |

---

## H. Quality Evaluation (Cross-cutting — Highest Priority)

### BL-01 [P0 · framework ready] RAG retrieval eval harness (golden QA set + scoring script)
- **2026-09-02 framework delivered**: `evals/` structure + `scripts/run_rag_eval.py` (index → per-QA →
  recall@5/10 + MRR → baseline JSON) + 13 unit tests for the pure metric functions. **Pending assets**: `documents/`
  document set + `golden_qa.yaml` entries (see `evals/README.md`).
- **Current state**: Retrieval quality is unquantified. Tuning `merge_threshold`/`top_k`/`hybrid_alpha` or swapping
  embeddings relies on human intuition; the ROADMAP item "quality regression QA set" has been outstanding for a while.
- **Gap**: The industry-standard golden set + metric regression (recall@k / MRR / faithfulness sampling).
- **Approach**: An `evals/` directory: a representative document set (PDF/xlsx/scanned/audio) + 30-50 QA entries
  (question, expected file/chunk hit, reference answer) + a scoring script (index against the staging DB, run
  queries, produce a metrics JSON, and diff against the in-repo baseline).
- **Acceptance**: A single command produces scores; the baseline JSON is committed; any MR touching retrieval attaches a scoring diff.
- **Dependencies**: staging DB (available) + embedding service.

### BL-02 [P0 · framework ready] ASR eval set (golden transcripts)
- **2026-09-02 framework delivered**: `scripts/run_asr_eval.py` (any AsrProvider → CER /
  simplified-Chinese rate / hallucination count → baseline JSON, with `--provider` override and `--baseline` comparison).
  **Pending assets**: 3-5 audio clips + manually corrected Traditional-Chinese transcripts.
- **Current state**: No acceptance basis for swapping ASR models.
- **Approach**: 3-5 representative audio clips (meeting/presentation/with leading silence) + manually corrected Traditional-Chinese transcripts;
  metrics: CER, Traditional-Chinese output rate, hallucination-segment count (reusing the `audio_defense` pattern statistics).
- **Acceptance**: The script produces a CER table for any AsrProvider; the whisper-turbo baseline is committed.
- **Dependencies**: None. **Prerequisite for BL-08.**

## A. Document Parsing (docling)

### BL-05 [✅ 2026-09-02] Chunk metadata enrichment — section/page number into metadata
- **Delivered**: `docling_convert_once` returns chunk records `{text, headings, page_no}`
  (splits inherit the source block's meta, merges take the first block's, bare strings get None) → `leaf_splitter` injects leaf
  metadata → PGVector node → `mode=search` and REST query results carry `page`/
  `headings` (only when present; zero migration for existing indexes). Embedding uses the bare text, so the
  provenance fields do not pollute the vector.
- **Acceptance passed**: 13 unit tests (refine-record contract / leaf injection) + 2 integration tests
  (real docling md → headings, PDF → page_no, pinning the docling meta schema);
  backward compatible with old data (the response omits the key when the field is absent).
- **Note**: Only **newly indexed** data carries page numbers; existing folders get them only after re-indexing.

### BL-03 [P1] Parsing-quality sampling baseline (bundled with BL-01)
- OCR error rate is unmeasured (the tiny/small/medium tradeoff for `ocr_model_scale` has no data).
  Include 2-3 scanned documents with manually corrected text in the golden set, and have the scoring script also produce OCR CER.

### BL-04 [P2] Image semantics (VLM caption experiment)
- Images currently carry only OCR text; the docling VLM pipeline (GraniteDocling) can produce image descriptions.
  GPU cost is high; defer to a small-scale experiment once the eval harness is ready.

## B. ASR (feat/asr-provider branch in progress)

### BL-06 [P0 · in progress] ASR config
- **Current state**: The audio pipeline is pure auto-discovery (`docling_loader:586` "no config switch");
  no switches for trimming or hallucination filtering.
- **Approach**: A `rag.asr` section: `enabled / provider / model_path / trim_leading_silence /
  filter_hallucinations / segment_seconds / to_traditional` (the last two reserved for FireRedASR).

### BL-07 [P0 · in progress] AsrProvider interface + docling default
- The `document_loader` audio path routes through the injected provider (same pattern as H6);
  `DoclingWhisperAsrProvider` wraps the current behavior = zero behavior change. `audio_defense`
  (trim/filter) stays outside the provider, model-agnostic.

### BL-08 [✅ 2026-09-03 accepted and promoted to production provider] FireRedASRProvider
- **Delivered**: `fireredasr_provider.py` — (1) 60s hard cap: ffmpeg silencedetect
  finds silence and greedily cuts ≤55s segments (cut point at the silence midpoint; hard cut when there is no silence —
  silero-vad drags torchaudio into a base-resolution and GPU-group switch conflict, so it was dropped); (2) ffmpeg
  16kHz mono resampling; (3) OpenCC s2twp simplified→traditional (Taiwan usage); (4) AED without punctuation →
  chunks=None takes the `leaf_splitter` plain-text path. The factory `provider: "fireredasr"`
  is wired in; a lazy singleton loads the model. The code is vendored from the official repo
  (`vendor/fireredasr_src/`, Apache-2.0; the PyPI `fireredasr` is a third-party fork).
- **Acceptance passed (2026-09-03, CV22 zh-TW test, 200 manually verified sentences)**:
  avg CER **6.11% vs whisper turbo 35.92%** (still ~29% after removing the simplified/traditional inflation, nearly a
  5x difference), 0% simplified-Chinese rate, 1.8x faster on CPU; baselines at `evals/baselines/asr_*_2026-09-03.json`.
  Config switched to `rag.asr.provider: "fireredasr"`.
- **Remaining**: (1) Deployment machines must ship the `assets/fireredasr/FireRedASR-AED-L/` weights (~4.7GB,
  not committed). The vendored code **is already compiled into the binary as a uv path dependency**
  (Nuitka), so deployment does not need to ship `vendor/` separately;
  (2) Real long meeting-audio acceptance pending three manually corrected clips under `custom/`;
  (3) Punctuation restoration to be evaluated separately later.

### BL-09 [✅ 2026-09-02] ASR cloud provider (OpenAI-compatible)
- Delivered alongside BL-07: `OpenAICompatibleAsrProvider` (multipart POST
  /audio/transcriptions, optional Bearer; compatible with OpenAI / Groq / vLLM whisper).

### BL-22 [P2] Video format support (mp4/avi/mov/mkv/webm)
- docling 2.124 officially supports video (via ASR + representative keyframes, requires ffmpeg).
- **2026-09-02 pipeline verified end-to-end**: the default DocumentConverter converts mp4 directly →
  SUCCESS (no separate pipeline needed; earlier estimates overstated the cost); the sample was pure tone with no speech, so
  **content-level verification awaits the BL-02 speech samples**, after which it can be admitted to the whitelist.
  The current ".webm → convert to WAV as audio" path is unchanged.

## C. Chunking

### BL-10 [P2] Chunk statistics report (length distribution / undersize rate / table-block share; extends the timing audit)
### BL-11 [P2] Semantic chunking experiment (embedding-based split; awaits the BL-01 harness)

## D. Embedding

### BL-12 [P1] e5-large vs bge-m3 A/B (a long-deferred decision)
- Current: `intfloat/multilingual-e5-large` + query/passage prefix; bge-m3 as the fallback.
  Run recall/MRR for both on the BL-01 harness and settle it with data. Full re-indexing of the ~28 existing folders follows the decision.

### BL-13 [P2] Chunk-level embedding cache
- The current file-level content-hash skip still re-embeds an entire file on a small in-file change. A chunk-hash → vector
  cache could save GPU time on re-indexing large files. Defer until scale demands it.

## E. Retrieval / Query

### BL-14 [P1] `hnsw.ef_search` tuning
- **Current state**: Index built with `m=16, ef_construction=64` (`db_bootstrap:159`, reasonable);
  but query-time `ef_search` uses pgvector's default of **40** — recall is limited when top_k is raised.
- **Approach**: Once the BL-01 harness is ready, sweep ef_search 40/100/200 for the recall-latency curve, then set the value
  at the session/connection layer.
- **Dependencies**: BL-01.

### BL-15 [P2] Query-side enhancement experiment (rewrite / multi-query; the agentic scenario is partly covered by the caller LLM already, decide after measurement)

## F. Performance / Observability

### BL-16 [P1] Prometheus metrics
- **Current state**: Only structured logs + per-file timing audit (raw data exists, no export).
- **Approach**: A `/metrics` endpoint: indexing throughput (files/chunks per s), query latency P50/P95,
  job queue depth, cache hit rate, embedding batch latency. Fed directly from the timing audit.
- **Acceptance**: Prometheus can scrape it; the README lists the metrics.

### BL-17 [P2] Query load-test baseline (one-off k6/locust; concurrent-query P95 and GPU utilization)

## G. Platform / Scalability

### BL-18 [P1] Persist pending batches
- **Current state**: `_pending_file_batches` is purely in memory — a restart drops queued uploads (restart cleanup
  flips them to failed, forcing users to re-upload). Job status has DB write-through; the queue does not.
- **Approach**: Persist queued batches to IndexJobs (the status=queued row already exists) + rebuild the queue from the DB on restart.
- **Acceptance**: Integration test: kill/restart the manager while queued → the queue recovers and the job continues under the same id.

### BL-19 [P2] Externalize job state (PG advisory lock + SKIP LOCKED) → multi-instance indexing
- The current folder lock / TTLCache are both single-process in-memory — the indexing service can only run single-instance.
  Defer until the horizontal-scaling need is clear; the advisory-lock pattern from the migrate layer can be reused. **Depends on BL-18.**

### BL-20 [P2] Evaluate service-izing parse/embed (docling-serve; GPU isolation is already solved by cuda:N + INFER_LOCK, revisit at scale)

### BL-21 [P0 · in progress] Automated import-cycle guard
- Currently only a grep assertion (domain does not depend backward); build an AST-level zero-cycle import-graph unit test so that
  "A calls B, B calls A back" is permanently blocked in CI.

---

## Pipeline Review Backlog (2026-09-07 full-chain review; C1/C2/H1-H4/M3/M4 fixed)

### BL-23 [P1] Upload succeeds but auto-index fails to start → the file has no record at all (M1)
- `trigger_auto_index` swallows the exception and returns only a warning message; the File row exists but FileIndex does not.
  The frontend shows not_indexed, indistinguishable from "queued", with no retry. It should write a failed record or retry.

### BL-24 [P2] Delete order: physical file deleted first, DB row second (M2)
- An error in between leaves a "row without a file"; `FileIndex.file_id` FK has no ondelete cascade.

### BL-25 [P2] delete_document_index skips cache invalidation on exception (M5)
- Chunks are already deleted but FileIndexNotFound flips to False → the query cache is not cleared, returning deleted content within the TTL.

### BL-26 [P2] Folder rename: storage rename and file_path update are not atomic (M6)
### BL-27 [P2] After a reindex cancel 30s timeout, a lingering thread may rebuild a just-DROPped table (H5-B)
- The `hierarchical_indexer` file header already documents this risk; needs a hard job kill or a folder-generation check before writing.

### BL-28 [P3] No unique constraint on same-name files in the same folder (L1); a failed DB create after save_file leaves an orphan file (L2);
inconsistent single-file upload metadata=None message (L3); mixed semantics in delete_folder_index results (L4).

## Completed (Traceable Archive)

- 2026-08~09: 35 architecture-review items (H1-H6 / M1-M15 / Low), M6/M14 refactors,
  migrate triple-guard, 95%/50% dual coverage thresholds, integration-test scaffolding (see the git log
  `chore/bump-v1.1.9-rocm` branch and the ROADMAP "Delivered" section).
- 2026-09-02: docling 2.119 → 2.124 (BL prerequisite).
- 2026-09-02 (feat/asr-provider): **BL-06** rag.asr config (minimal 5 fields);
  **BL-07** AsrProvider interface + docling-whisper default (zero behavior) + routing;
  **BL-09** cloud openai-compatible provider; **BL-21** automated import-cycle guard
  (two-level AST zero-cycle pinned in CI); format v3 aligned with the official site (6 audio + odt/ods/odp/epub/
  tex/eml/xlsm); dead-code scan (vulture: 7 reports, all false positives / framework contracts, zero real dead code).
- 2026-09-02 (feat/asr-provider): **BL-05** chunk citation provenance (headings/page_no
  into node metadata, returned by search/query as page number and section chain; new-index data only).
