#!/usr/bin/env node
'use strict';

// emit-drop — map one pulled occurrence directory into a MeetingMiner source
// drop, then hand the drop to the pipeline through POST /ingests.
//
// The puller is a black box to MeetingMiner and MeetingMiner is a black box to
// the puller: this file imports nothing from the server, reads no config.yaml
// and no .env, and never loads the drop JSON Schema at emit time (the schema is
// a test-time dependency only, so the puller still runs standing alone outside
// the MeetingMiner checkout). The only two contracts are the drop layout below
// and the HTTP call in postIngest().
//
// Drop layout (canonical filenames; every other archive file is ignored):
//   <dropsRoot>/<YYYY-MM-DD>-<title-slug>-<sha1(sourceId)[0:8]>/
//     metadata.json                required
//     recording.mp4                when the occurrence has a downloadable video
//     transcript.vtt               when the occurrence has the original VTT export
//     transcript.txt               the speaker-attributed export
//     extraction-summary.md        the generated architecture summary, when it exists
//     extraction-action-items.md   the generated action items, when it exists
//
// The two extraction documents are DERIVATIVE, not evidence: they never make a
// drop ingestible on their own, they stay out of plan.files (see EXTRACTION_MAP
// below), and MeetingMiner parses them instead of asking a model to re-derive
// what this tool already derived.
//
// Write-once: a drop is assembled under <dropsRoot>/.staging/... and finalized
// with a single rename. A finalized drop is never overwritten, re-copied into,
// or deleted — an existing target is reported and skipped.

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// ---------------------------------------------------------------------------
// Defaults & resolution order
// ---------------------------------------------------------------------------

// A dedicated folder outside both this repo and the puller's own archive: the
// archive is mutated in place by re-pulls, and drop contents are read-only
// after intake, so the two cannot share a directory.
const DEFAULT_DROPS_ROOT = '/Users/devopsterus/current/meetingminer-drops';
const DEFAULT_API_URL = 'http://127.0.0.1:8000';
const DEFAULT_CORPUS = 'real';
// An api that accepts the connection and then never answers must not park a
// pull forever: "the hand-off never fails a pull" is only true if it also
// always finishes. Overridable per call via opts.timeoutMs.
const DEFAULT_INTAKE_TIMEOUT_MS = 30000;

const SOURCE_SIDECAR = '_source.json';
const METADATA_FILENAME = 'metadata.json';
const STAGING_DIRNAME = '.staging';

// occurrence-file extension -> canonical drop filename.
const EVIDENCE_MAP = [
  ['.mp4', 'recording.mp4'],
  ['.vtt', 'transcript.vtt'],
  ['.txt', 'transcript.txt'],
];
const EVIDENCE_FILENAMES = EVIDENCE_MAP.map(([, canonical]) => canonical);

// occurrence-file SUFFIX -> canonical drop filename and metadata key, for the
// two documents grab-teams-transcript.js generates beside the transcript.
// Suffix-keyed rather than extension-keyed like EVIDENCE_MAP: both are ".md",
// so an extension key cannot tell them apart. The full name is built from the
// stem, so "<stem> org chart.json" -- which also sits in the directory -- can
// never match either.
//
// These are collected into plan.summaries and kept OUT of plan.files, because
// dropIsCurrent() and evidencePresentIn() both treat plan.files as the
// *evidence* set: folding summaries in would silently change re-emit semantics
// and make a summary look like a reason to re-arm an occurrence.
const EXTRACTION_MAP = [
  ['.md', 'extraction-summary.md', 'archSummary'],
  [' action items.md', 'extraction-action-items.md', 'actionItems'],
];

// The per-occurrence participant graph the puller writes beside the transcript,
// named "<stem> org chart.json". It is auxiliary evidence: the transcript is
// what makes an occurrence, so an absent or broken chart costs the drop its
// `participants` key and nothing else.
const ORG_CHART_SUFFIX = ' org chart.json';
// The chart's field for a person's name; the drop schema requires displayName.
const CHART_NAME_KEY = 'name';

// Re-emit sequencing. Sequence 1 IS the existing unsuffixed drop name — the 28
// finalized drops must not be renamed — so the discriminator starts at 002.
// Three digits, zero padded, so lexical order within a prefix is emit order.
const FIRST_SEQUENCE = 1;
const MAX_SEQUENCE = 999;
const SEQUENCE_DIGITS = 3;

function resolveDropsRoot(explicit) {
  return path.resolve(explicit || process.env.MM_DROPS_ROOT || DEFAULT_DROPS_ROOT);
}
function resolveApiUrl(explicit) {
  return String(explicit || process.env.MM_API_URL || DEFAULT_API_URL).replace(/\/+$/, '');
}
function resolveCorpus(explicit) {
  const c = explicit || process.env.MM_CORPUS || DEFAULT_CORPUS;
  if (c !== 'real' && c !== 'scripted')
    throw new Error(`corpus must be "real" or "scripted", got ${JSON.stringify(c)}`);
  return c;
}

// A mapping problem that is this occurrence's fault, not the tool's: the pass
// records it and moves on rather than aborting.
class SkipError extends Error {
  constructor(reason) {
    super(reason);
    this.name = 'SkipError';
  }
}

// ---------------------------------------------------------------------------
// Pure mapping helpers (exported for the test suite)
// ---------------------------------------------------------------------------

// sourceId — the Stream URL reduced to its identifying `id` parameter.
//
// AD-1 allows "recording drive-item ID or Stream URL". The drive-item id is
// only observable from live player traffic, so the backfill could not produce
// one; the Stream URL can. But the raw _source.json url also carries
// referrer / referrerScenario / isDarkMode params that vary with how the link
// was copied, so using it verbatim would let one occurrence produce two
// different sourceIds — and therefore two job rows. Keeping only `id` (the
// server-relative path of the recording file) yields a still-valid Stream URL
// that is stable across re-pulls and unique per occurrence.
function canonicalSourceId(url) {
  let parsed;
  try {
    parsed = new URL(String(url || ''));
  } catch {
    throw new SkipError(`_source.json url is not a URL: ${JSON.stringify(url)}`);
  }
  // Only http(s) has a meaningful origin. A file:/data:/anything else URL
  // stringifies its origin as "null", which would collide across occurrences
  // and hand MeetingMiner one sourceId for several meetings.
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:')
    throw new SkipError(`_source.json url is not an http(s) URL: ${parsed.href}`);
  const id = parsed.searchParams.get('id');
  if (!id) throw new SkipError(`_source.json url carries no "id" parameter: ${parsed.href}`);
  return `${parsed.origin}${parsed.pathname}?id=${encodeURIComponent(id)}`;
}

function pad(n, width) {
  return String(n).padStart(width, '0');
}

function isoSecondUtc(y, mo, d, h, mi, s) {
  return `${pad(y, 4)}-${pad(mo, 2)}-${pad(d, 2)}T${pad(h, 2)}:${pad(mi, 2)}:${pad(s, 2)}Z`;
}

// The "-YYYYMMDD_HHMMSS[UTC]-" stamp Teams writes into a recording filename.
// Group 7 (the literal "UTC") is the whole point here: grab-teams-transcript's
// stampDate() discards it, but it is the only signal that distinguishes an
// instant from a wall-clock time in the organizer's unknown timezone.
const STAMP_RE = /-(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(UTC)?/;

// Whether Y-M-D names a day that exists: Date.UTC silently rolls 2026-02-31
// forward to 2026-03-03, so the only check is a round trip back out.
function isRealCalendarDate(year, month, day) {
  if (month < 1 || month > 12 || day < 1 || day > 31) return false;
  const d = new Date(Date.UTC(year, month - 1, day));
  return d.getUTCFullYear() === year && d.getUTCMonth() === month - 1 && d.getUTCDate() === day;
}

// A malformed stamp must SKIP the occurrence, not fall through to day
// precision and not emit. The digits are matched positionally, so a corrupt
// name yields values like month 13 or hour 99 that produce a syntactically
// well-formed but impossible startedAt. The api's format checker rejects those
// with 422 — and by then the drop is finalized write-once and can never be
// ingested, because nothing is allowed to delete or rewrite it. So the
// validation has to happen before anything is written.
function parseStamp(recordingName) {
  const m = String(recordingName || '').match(STAMP_RE);
  if (!m) return null;
  const stamp = {
    year: +m[1], month: +m[2], day: +m[3],
    hour: +m[4], minute: +m[5], second: +m[6],
    utc: m[7] === 'UTC',
  };
  if (stamp.hour > 23 || stamp.minute > 59 || stamp.second > 59)
    throw new SkipError(
      `recording name carries an impossible clock time (${m[4]}:${m[5]}:${m[6]}): ${recordingName}`
    );
  if (!isRealCalendarDate(stamp.year, stamp.month, stamp.day))
    throw new SkipError(
      `recording name carries a date that does not exist (${m[1]}-${m[2]}-${m[3]}): ${recordingName}`
    );
  return stamp;
}

// The puller's own occurrence date, "M.D.YY". Returns null for anything that
// is not a real calendar day; startedAtFrom turns that into a named SkipError.
function parseOccurrenceDate(value) {
  const m = String(value || '').match(/^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2}|\d{4})$/);
  if (!m) return null;
  const year = m[3].length === 4 ? +m[3] : 2000 + +m[3];
  const month = +m[1];
  const day = +m[2];
  if (!isRealCalendarDate(year, month, day)) return null;
  return { year, month, day };
}

// startedAt / startedAtPrecision.
//
// Only a UTC-suffixed stamp names an instant. An un-suffixed stamp is in the
// ORGANIZER's timezone, which the puller does not know (see the puller's
// CLAUDE.md); converting it anyway would write a wrong UTC instant under
// startedAtPrecision "second", which the schema defines as "a real time of
// day". So anything that is not a UTC stamp falls back to the occurrence date
// at 00:00:00Z with "day" precision. Nothing is lost: the raw stamp survives
// verbatim inside provenance.recordingName for a later, better-informed pass.
// This also makes all three of the archive's dateSource variants fall out of
// one rule instead of three branches.
function startedAtFrom(source) {
  const stamp = parseStamp(source && source.recordingName);
  if (stamp && stamp.utc) {
    return {
      startedAt: isoSecondUtc(stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second),
      startedAtPrecision: 'second',
    };
  }
  const day = parseOccurrenceDate(source && source.date)
    // No usable `date` field: the un-suffixed stamp still names the right
    // calendar day in the organizer's timezone, which is exactly the
    // resolution "day" precision claims.
    || (stamp ? { year: stamp.year, month: stamp.month, day: stamp.day } : null);
  if (!day)
    throw new SkipError(
      `no usable date: _source.json date is ${JSON.stringify(source && source.date)} and the ` +
      'recording name carries no -YYYYMMDD_HHMMSS stamp'
    );
  return {
    startedAt: isoSecondUtc(day.year, day.month, day.day, 0, 0, 0),
    startedAtPrecision: 'day',
  };
}

function slugify(title) {
  const slug = String(title || '')
    .normalize('NFKD')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
    .replace(/-+$/g, '');
  return slug || 'untitled';
}

// Human-scannable and deterministic from sourceId, so write-once detection is
// a plain existsSync on a stable path rather than a scan of the drops folder.
function dropName({ startedAt, title, sourceId }) {
  const date = String(startedAt).slice(0, 10);
  const digest = crypto.createHash('sha1').update(String(sourceId), 'utf8').digest('hex').slice(0, 8);
  return `${date}-${slugify(title)}-${digest}`;
}

// A drop directory name split into the occurrence prefix produced by dropName()
// and its re-emit sequence. The unsuffixed name is sequence 1, so emit order for
// one occurrence is lexical order of its directory names. A base name always
// ends in the 8-hex digest, so a trailing "-NNN" can only be a sequence.
function splitDropName(name) {
  const m = /^(.+)-(\d{3})$/.exec(String(name));
  if (m) {
    const sequence = Number(m[2]);
    if (sequence > FIRST_SEQUENCE) return { prefix: m[1], sequence };
  }
  return { prefix: String(name), sequence: FIRST_SEQUENCE };
}

// ---------------------------------------------------------------------------
// The participant graph
// ---------------------------------------------------------------------------

// Pure: one org chart object -> { participants, warnings }.
//
// `participants` is null for a chart this tool cannot use at all, and the
// caller then omits the key entirely rather than emitting []. The distinction
// is load-bearing on the server: `align` reads an empty array as "the source
// looked and found nobody" and does NOT fall back to transcript labels, so
// emitting [] for a broken chart would silently strip a meeting of everyone.
//
// Every field but `name` passes through verbatim — including `managerChain`,
// which is what puts the reporting chain into the meeting's participant record
// without a new column on either side.
function mapParticipants(chart) {
  const warnings = [];
  if (!chart || typeof chart !== 'object' || Array.isArray(chart)) {
    warnings.push('the participant graph is not a JSON object');
    return { participants: null, warnings };
  }
  const people = chart.people;
  if (!Array.isArray(people)) {
    warnings.push(
      `the participant graph has no "people" array (got ${people === undefined ? 'nothing' : typeof people})`
    );
    return { participants: null, warnings };
  }
  const participants = [];
  for (let i = 0; i < people.length; i++) {
    const row = people[i];
    if (!row || typeof row !== 'object' || Array.isArray(row)) {
      warnings.push(`people[${i}] is not an object; that row is dropped`);
      continue;
    }
    const name = typeof row[CHART_NAME_KEY] === 'string' ? row[CHART_NAME_KEY].trim() : '';
    if (!name) {
      // One nameless row must not retire the occurrence, and it must not be
      // emitted either: the schema requires a non-empty displayName, so the
      // whole drop would be refused at intake over one bad row.
      warnings.push(`people[${i}] has no usable "${CHART_NAME_KEY}"; that row is dropped`);
      continue;
    }
    const mapped = { displayName: name };
    for (const [key, value] of Object.entries(row)) {
      // `displayName` is skipped as well as `name`: it is the one field this
      // mapping owns, and a row carrying its own must not be able to blank it.
      if (key === CHART_NAME_KEY || key === 'displayName') continue;
      mapped[key] = value;
    }
    participants.push(mapped);
  }
  if (!participants.length) {
    warnings.push('the participant graph carries no usable person rows');
    return { participants: null, warnings };
  }
  return { participants, warnings };
}

// The occurrence's chart as drop participants, or null. Never raises a
// SkipError: the transcript is the occurrence's evidence and the chart is
// auxiliary, so an unusable chart costs the `participants` key and says so on
// stderr rather than retiring a meeting.
function readParticipantGraph(dir, stem) {
  const chartPath = path.join(dir, stem + ORG_CHART_SUFFIX);
  let text;
  try {
    text = fs.readFileSync(chartPath, 'utf8');
  } catch (e) {
    // No chart at all is the ordinary shape of an older pull, and silent: the
    // drop is byte-identical to what this tool emitted before. Anything else
    // (unreadable, a directory in its place) is named.
    if (e.code !== 'ENOENT')
      console.error(`warning: participant graph could not be read, emitting no participants: ${chartPath}: ${e.message}`);
    return null;
  }
  let chart;
  try {
    chart = JSON.parse(text);
  } catch (e) {
    console.error(`warning: participant graph is not valid JSON, emitting no participants: ${chartPath}: ${e.message}`);
    return null;
  }
  const { participants, warnings } = mapParticipants(chart);
  for (const w of warnings) console.error(`warning: ${chartPath}: ${w}`);
  if (participants === null)
    console.error(`warning: emitting no participants for ${chartPath}`);
  return participants;
}

// ---------------------------------------------------------------------------
// Planning
// ---------------------------------------------------------------------------

function readSource(occurrenceDir) {
  const sidecar = path.join(occurrenceDir, SOURCE_SIDECAR);
  let text;
  try {
    text = fs.readFileSync(sidecar, 'utf8');
  } catch (e) {
    throw new SkipError(`${SOURCE_SIDECAR} could not be read: ${e.message}`);
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    throw new SkipError(`${SOURCE_SIDECAR} is not valid JSON: ${e.message}`);
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
    throw new SkipError(`${SOURCE_SIDECAR} is not a JSON object`);
  return parsed;
}

// Everything the emit needs, computed without touching the drops folder.
// Exported so --dry-run and the tests can inspect the mapping on its own.
function planDrop(occurrenceDir, opts = {}) {
  const dir = path.resolve(occurrenceDir);
  const source = opts.source || readSource(dir);
  const corpus = resolveCorpus(opts.corpus);
  const sourceId = canonicalSourceId(source.url);
  const { startedAt, startedAtPrecision } = startedAtFrom(source);

  // The occurrence's files are named "<date> <title>.<ext>" — except in the
  // puller's undated layout, where run() sets `base = stem` and the files are
  // just "<title>.<ext>". Mirror that exactly: prefixing an empty date would
  // build " <title>" with a leading space, which matches nothing on disk and
  // would skip every undated occurrence. Only stem-matched files map either
  // way: a stray "11_59 AM - ..._transcript.txt" sitting beside the real
  // export belongs to no occurrence and must not become the drop's transcript.
  const dateText = String(source.date == null ? '' : source.date).trim();
  const titleText = String(source.title == null ? '' : source.title).trim();
  const stem = dateText ? `${dateText} ${titleText}` : titleText;
  const files = [];
  for (const [ext, canonical] of EVIDENCE_MAP) {
    const from = path.join(dir, stem + ext);
    let stat = null;
    try {
      stat = fs.statSync(from);
    } catch {
      continue;
    }
    if (stat.isFile()) files.push({ from, to: canonical });
  }
  if (!files.length)
    throw new SkipError(
      `no canonical evidence file for stem ${JSON.stringify(stem)} ` +
      '(need one of .mp4 / .vtt / .txt)'
    );

  const metadata = {
    schemaVersion: 1,
    sourceId,
    corpus,
    startedAt,
    startedAtPrecision,
    // provenance is the occurrence's _source.json embedded verbatim.
    provenance: source,
  };

  // The participant graph the puller already wrote beside this occurrence,
  // mapped into the schema's `participants`. Keyed on mail by the pipeline, so
  // a person is one identity across meetings instead of one per spelling of
  // their name. The key is omitted — never emitted as [] — when there is no
  // usable chart; readParticipantGraph explains why.
  const participants = readParticipantGraph(dir, stem);
  if (participants) metadata.participants = participants;

  // A standalone/backfill invocation discovers matching documents from disk,
  // preserving the longstanding emit-drop behavior.  The active pull path
  // instead supplies an explicit (possibly empty) selection of documents
  // written for *this* transcript run.  That boundary stops a same-stem file
  // left by an earlier run from being adopted as fresh extraction evidence.
  //
  // Documents are still stat()ed before copying, but an explicit selection is
  // authoritative: a file that exists yet was not selected is never carried.
  const explicitDocuments = Object.prototype.hasOwnProperty.call(opts, 'extractionDocuments')
    ? new Set(opts.extractionDocuments || [])
    : null;

  // The generated extraction documents, when authorized for this emit.
  // Declared in metadata.extractions so a consumer knows which ones arrived
  // without stat()ing the drop, at schemaVersion 3 so a consumer pinned to an
  // older version fails closed rather than ignoring the declaration. The key
  // is omitted entirely -- never emitted as {} -- when neither document
  // exists, mirroring readParticipantGraph's rule.
  const summaries = [];
  const extractions = {};
  for (const [suffix, canonical, key] of EXTRACTION_MAP) {
    if (explicitDocuments !== null && !explicitDocuments.has(canonical)) continue;
    const from = path.join(dir, stem + suffix);
    let stat = null;
    try {
      stat = fs.statSync(from);
    } catch {
      continue;
    }
    if (!stat.isFile()) continue;
    summaries.push({ from, to: canonical });
    extractions[key] = canonical;
  }
  if (summaries.length) {
    metadata.schemaVersion = 3;
    metadata.extractions = extractions;
  }

  return {
    occurrenceDir: dir,
    stem,
    sourceId,
    startedAt,
    startedAtPrecision,
    corpus,
    files,
    summaries,
    metadata,
    name: dropName({ startedAt, title: source.title, sourceId }),
  };
}

// ---------------------------------------------------------------------------
// Emit
// ---------------------------------------------------------------------------

let stagingCounter = 0;

// Every finalized drop for one occurrence prefix, oldest emit first.
function existingDrops(dropsRoot, base) {
  let entries;
  try {
    entries = fs.readdirSync(dropsRoot, { withFileTypes: true });
  } catch (e) {
    if (e.code === 'ENOENT') return [];
    throw e;
  }
  return entries
    .filter((e) => e.isDirectory())
    .map((e) => ({ name: e.name, ...splitDropName(e.name) }))
    .filter((e) => e.prefix === base)
    .sort((a, b) => a.sequence - b.sequence);
}

// The name the next drop for this occurrence takes: the unsuffixed base when
// nothing is there yet, otherwise "<base>-NNN" one past the highest sequence.
function nextDropName(dropsRoot, base) {
  const existing = existingDrops(dropsRoot, base);
  if (!existing.length) return base;
  const next = existing[existing.length - 1].sequence + 1;
  if (next > MAX_SEQUENCE)
    throw new Error(
      `drop sequence exhausted for ${base}: ${MAX_SEQUENCE} drops already exist for this ` +
      'occurrence and a finalized drop is never overwritten'
    );
  return `${base}-${pad(next, SEQUENCE_DIGITS)}`;
}

function evidencePresentIn(dropPath) {
  const present = [];
  for (const canonical of EVIDENCE_FILENAMES) {
    let stat = null;
    try {
      stat = fs.statSync(path.join(dropPath, canonical));
    } catch {
      continue;
    }
    if (stat.isFile()) present.push(canonical);
  }
  return present.sort();
}

function readDropMetadata(dropPath) {
  try {
    const parsed = JSON.parse(fs.readFileSync(path.join(dropPath, METADATA_FILENAME), 'utf8'));
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function hasParticipantGraph(metadata) {
  return Array.isArray(metadata && metadata.participants) && metadata.participants.length > 0;
}

// Whether a new drop would bring the newest finalized one nothing it does not
// already have. This deliberately MIRRORS intake's augmentation rule rather
// than asking the broader "is anything different": intake accepts an
// augmenting drop only when it adds a participant graph the occurrence's drop
// lacks or a recording the meeting lacks, and refuses everything else. A
// puller that emitted on any difference — a chart whose rows were re-resolved,
// say — would finalize a drop write-once, POST it, be refused, and count the
// refusal as "already ingested"; the next pass would then see that drop as the
// newest and stop. The occurrence would silently never migrate. So the puller
// does not write what the door will not take.
//
// An unreadable drop answers false: "cannot tell" must not read as "already
// current", or a corrupt drop would retire its occurrence forever.
function dropIsCurrent(dropPath, plan) {
  const metadata = readDropMetadata(dropPath);
  if (metadata === null) return false;
  // Empty does not count as a graph on either side — `align` reads [] as "the
  // source found nobody", so it adds no participants and duplicates none.
  const have = hasParticipantGraph(metadata);
  const want = hasParticipantGraph(plan.metadata);
  const present = new Set(evidencePresentIn(dropPath));
  const proposed = new Set(plan.files.map((f) => f.to));
  const missing = [...present].filter((name) => !proposed.has(name));
  if (missing.length)
    throw new Error(
      `cannot re-emit ${path.basename(dropPath)}: this occurrence no longer carries ` +
      `target evidence (${missing.join(', ')}); an augmenting drop may not shed it`
    );
  // The door deliberately has only two evidence classes today. A newly found
  // VTT/TXT is useful source material but cannot by itself re-arm an occurrence:
  // intake would refuse the write-once sibling, so it is not a reason to emit.
  const addsRecording = proposed.has('recording.mp4') && !present.has('recording.mp4');
  return !(want && !have) && !addsRecording;
}

// Every occurrence prefix in the drops root whose NEWEST drop carries no
// `participants` key — i.e. what a `--re-emit` migration has not reached yet.
//
// `--re-emit` is opt-in per occurrence, so the same person is mail-keyed in a
// re-emitted meeting and name-keyed in one left alone, and nothing links the
// two participant rows. That is a migration to finish, not a state to sit in,
// so the pass has to be able to say how much of it is left. Read from the
// drops folder alone, the same property the sequence discriminator preserves.
function unmigratedPrefixes(dropsRoot) {
  let entries;
  try {
    entries = fs.readdirSync(dropsRoot, { withFileTypes: true });
  } catch {
    return { total: 0, stale: [] };
  }
  const newest = new Map();
  for (const e of entries) {
    if (!e.isDirectory() || e.name.startsWith('.')) continue;
    const { prefix, sequence } = splitDropName(e.name);
    const current = newest.get(prefix);
    if (!current || sequence > current.sequence) newest.set(prefix, { name: e.name, sequence });
  }
  const stale = [];
  for (const [prefix, { name }] of newest) {
    const metadata = readDropMetadata(path.join(dropsRoot, name));
    // An unreadable drop counts as unmigrated for the same reason
    // dropIsCurrent refuses it: "cannot tell" must not report as "done".
    if (metadata === null || !hasParticipantGraph(metadata)) stale.push(prefix);
  }
  return { total: newest.size, stale: stale.sort() };
}

// Assemble in staging, finalize with one rename. Returns
//   { status: 'created' | 'exists' | 'current' | 'planned', path, plan }
// and throws SkipError when the occurrence cannot be mapped at all.
//
// With opts.reEmit, an occurrence that already has a drop is not reported
// `exists`: if the newest drop says something different from what this pass
// would say, a NEW sibling drop is emitted at the next sequence, declaring
// `augments` so intake re-arms the occurrence's existing job instead of
// answering 409. The finalized drop is never renamed, rewritten, or deleted.
function emitDrop(occurrenceDir, opts = {}) {
  const plan = planDrop(occurrenceDir, opts);
  if (opts.dryRun && !opts.reEmit) return { status: 'planned', path: null, plan };

  const dropsRoot = resolveDropsRoot(opts.dropsRoot);

  if (opts.reEmit) {
    const existing = existingDrops(dropsRoot, plan.name);
    if (existing.length) {
      const newest = path.join(dropsRoot, existing[existing.length - 1].name);
      if (dropIsCurrent(newest, plan)) return { status: 'current', path: newest, plan };
      // A re-emit exists only because the occurrence was already emitted, and
      // therefore probably already ingested; without the declaration intake
      // would answer 409 on the live job. Naming its own sourceId is legal —
      // the schema allows the two ids to differ but does not require it — and
      // routes to the re-arm path that preserves the meeting id.
      plan.name = nextDropName(dropsRoot, plan.name);
      plan.metadata = {
        ...plan.metadata,
        // At least 2 for `augments`, but never *down* from 3: a drop that also
        // carries extraction documents has already declared version 3, and
        // rewriting that to 2 would emit a drop the schema refuses.
        schemaVersion: Math.max(plan.metadata.schemaVersion, 2),
        augments: { sourceId: plan.sourceId },
      };
    }
    if (opts.dryRun) return { status: 'planned', path: null, plan };
  }

  const target = path.join(dropsRoot, plan.name);
  let targetStat = null;
  try {
    targetStat = fs.statSync(target);
  } catch {}
  if (targetStat) {
    // "exists" means "a finalized drop is already there". A plain file at that
    // path is not one, and reporting it as `exists` would quietly retire the
    // occurrence: never emitted, never POSTed, and never mentioned again.
    if (!targetStat.isDirectory())
      throw new Error(`drop target exists but is not a directory: ${target}`);
    return { status: 'exists', path: target, plan };
  }

  const stagingRoot = path.join(dropsRoot, STAGING_DIRNAME);
  const staging = path.join(stagingRoot, `${plan.name}.${process.pid}.${stagingCounter++}`);
  let finalized = false;
  try {
    fs.mkdirSync(staging, { recursive: true });
    fs.writeFileSync(
      path.join(staging, METADATA_FILENAME),
      JSON.stringify(plan.metadata, null, 2) + '\n'
    );
    for (const f of [...plan.files, ...plan.summaries]) {
      // FICLONE is an APFS clone when the filesystem supports it and a real
      // byte copy otherwise, so the recordings cost no extra disk while the
      // drop stays independent of the archive that re-pulls mutate.
      fs.copyFileSync(f.from, path.join(staging, f.to), fs.constants.COPYFILE_FICLONE);
    }
    try {
      fs.renameSync(staging, target);
      finalized = true;
    } catch (e) {
      // Another emit finalized this same drop between the existsSync above and
      // this rename. A finalized drop is never overwritten, so that is the
      // "exists" outcome, not an error.
      if (e.code === 'EEXIST' || e.code === 'ENOTEMPTY') return { status: 'exists', path: target, plan };
      throw e;
    }
  } finally {
    if (!finalized) {
      try { fs.rmSync(staging, { recursive: true, force: true }); } catch {}
    }
    // Leaves nothing behind once the last concurrent emit is done; fails
    // harmlessly while another one is still staging.
    try { fs.rmdirSync(stagingRoot); } catch {}
  }
  return { status: 'created', path: target, plan };
}

// ---------------------------------------------------------------------------
// Intake
// ---------------------------------------------------------------------------

// POST /ingests — the one intake door (AD-14). Returns
//   { status: 'created' | 'requeued' | 'duplicate', jobId, httpStatus }
// and throws on anything else, including an unreachable api.
async function postIngest(dropPath, opts = {}) {
  const api = resolveApiUrl(opts.apiUrl);
  const url = `${api}/ingests`;
  const timeoutMs = opts.timeoutMs || DEFAULT_INTAKE_TIMEOUT_MS;
  let res;
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ dropPath: path.resolve(dropPath) }),
      // Covers the response body too, so a stalled read cannot hang either.
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (e) {
    const why = e && (e.name === 'TimeoutError' || e.name === 'AbortError')
      ? `no response within ${timeoutMs}ms`
      : (e && e.message) || String(e);
    throw new Error(`POST ${url} failed (is the api running?): ${why}`);
  }
  let body = null;
  try {
    body = await res.json();
  } catch {}
  if (res.status === 201) return { status: 'created', jobId: body && body.jobId, httpStatus: 201 };
  if (res.status === 200) return { status: 'requeued', jobId: body && body.jobId, httpStatus: 200 };
  if (res.status === 409 && (
    (body && body.title === 'duplicate-source') ||
    (body && typeof body.type === 'string' && body.type.endsWith(':duplicate-source'))
  )) return { status: 'duplicate', jobId: body && body.jobId, httpStatus: 409 };
  const detail = (body && (body.detail || body.title)) || `HTTP ${res.status}`;
  throw new Error(`POST ${url} rejected the drop (${res.status}): ${detail}`);
}

// ---------------------------------------------------------------------------
// Archive scan (--all)
// ---------------------------------------------------------------------------

// Every occurrence directory under `root`, keyed on the _source.json sidecar —
// not on an "M.D.YY" folder name. The batch-mirror folders under
// "Recordings and Transcripts/" look like occurrences but carry no sidecar and
// are not occurrences; the sidecar is what makes one.
function findOccurrences(root) {
  const found = [];
  const scan = (d) => {
    let entries = [];
    try {
      entries = fs.readdirSync(d, { withFileTypes: true });
    } catch (e) {
      // Silence here would drop a whole subtree out of a backfill that then
      // reports success, so the pass has to say which directory it could not
      // read.
      console.error(`warning: skipping unreadable directory ${d}: ${e.message}`);
      return;
    }
    for (const e of entries) {
      if (e.name === SOURCE_SIDECAR && e.isFile()) found.push(d);
      else if (e.isDirectory() && !e.name.startsWith('.') && e.name !== 'node_modules')
        scan(path.join(d, e.name));
    }
  };
  scan(path.resolve(root));
  return found.sort();
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

const USAGE = `Usage: node emit-drop.js [<occurrence-dir> ...] [options]

Maps a pulled occurrence directory (<Title>/<M.D.YY>/ with a _source.json) into
a MeetingMiner source drop and POSTs it to the ingestion API.

  --all               every occurrence under the puller directory (backfill)
  --dry-run           print the planned drop for each occurrence; write nothing
  --re-emit           bring already-emitted occurrences up to the current
                      contract: when the newest drop for an occurrence says
                      something different (a participant graph it lacks, or a
                      different evidence set), emit a NEW sibling drop at
                      "<name>-002", "-003", ... declaring augments, so intake
                      re-arms the existing job. Finalized drops are never
                      touched; an occurrence already current is reported so
  --no-post           emit the drop(s) but do not POST to the api
  --drops <dir>       drops folder            [MM_DROPS_ROOT, ${DEFAULT_DROPS_ROOT}]
  --api <url>         api base url            [MM_API_URL, ${DEFAULT_API_URL}]
  --corpus <c>        "real" | "scripted"     [MM_CORPUS, ${DEFAULT_CORPUS}]
  -h, --help          this text
`;

const VALUE_FLAGS = new Set(['--drops', '--api', '--corpus']);

function parseArgs(argv) {
  const out = { dirs: [], all: false, dryRun: false, reEmit: false, noPost: false, help: false, dropsRoot: '', apiUrl: '', corpus: '' };
  const seen = new Set();
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (VALUE_FLAGS.has(a)) {
      if (seen.has(a)) throw new Error(`${a} was given more than once`);
      seen.add(a);
      const v = argv[++i];
      if (v === undefined) throw new Error(`${a} needs a value`);
      // Without this, `--drops --dry-run` sets the drops folder to "--dry-run"
      // AND loses the dry run, so a run the user asked to write nothing writes
      // 28 drops into a directory named after a flag.
      if (v.startsWith('-')) throw new Error(`${a} needs a value, but got the option ${v}`);
      if (a === '--drops') out.dropsRoot = v;
      else if (a === '--api') out.apiUrl = v;
      else out.corpus = v;
      continue;
    }
    if (a === '--all') out.all = true;
    else if (a === '--dry-run') out.dryRun = true;
    else if (a === '--re-emit') out.reEmit = true;
    else if (a === '--no-post') out.noPost = true;
    else if (a === '-h' || a === '--help') out.help = true;
    // Single-dash too: an unrecognized "-x" is a typo, not an occurrence
    // directory, and treating it as one produces a confusing skip instead of a
    // usage error.
    else if (a.startsWith('-')) throw new Error(`unknown option ${a}`);
    else out.dirs.push(a);
  }
  // --all is "the whole archive"; listing directories alongside it means the
  // user expected those to be the run, so silently ignoring them is wrong.
  if (out.all && out.dirs.length)
    throw new Error(
      `--all covers the whole archive; it cannot be combined with the listed ` +
      `directory (${out.dirs[0]})`
    );
  return out;
}

async function main(argv) {
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (e) {
    console.error(e.message);
    console.error(USAGE);
    return 1;
  }
  if (opts.help) {
    console.error(USAGE);
    return 0;
  }

  const dirs = opts.all ? findOccurrences(__dirname) : opts.dirs;
  if (!dirs.length) {
    console.error(opts.all ? `No occurrences (no ${SOURCE_SIDECAR} sidecars) under ${__dirname}.` : USAGE);
    return 1;
  }
  // Fail before touching the filesystem if --corpus is nonsense.
  try {
    resolveCorpus(opts.corpus);
  } catch (e) {
    console.error(e.message);
    return 1;
  }

  const dropsRoot = resolveDropsRoot(opts.dropsRoot);
  const counts = { created: 0, exists: 0, current: 0, planned: 0, skipped: 0, failed: 0 };
  const post = { created: 0, requeued: 0, duplicate: 0, failed: 0 };

  for (const dir of dirs) {
    let res;
    try {
      res = emitDrop(dir, {
        dropsRoot,
        corpus: opts.corpus,
        dryRun: opts.dryRun,
        reEmit: opts.reEmit,
      });
    } catch (e) {
      if (e instanceof SkipError) {
        counts.skipped++;
        console.error(`skip     ${dir}\n           ${e.message}`);
      } else {
        counts.failed++;
        console.error(`FAILED   ${dir}\n           ${e.message}`);
      }
      continue;
    }

    if (res.status === 'planned') {
      counts.planned++;
      const p = res.plan;
      console.error(`plan     ${p.name}`);
      console.error(`           from      ${p.occurrenceDir}`);
      console.error(`           files     ${METADATA_FILENAME}, ${p.files.map((f) => f.to).join(', ')}`);
      console.error(`           docs      ${p.summaries.length ? p.summaries.map((f) => f.to).join(', ') : 'no extraction documents'}`);
      console.error(`           sourceId  ${p.sourceId}`);
      console.error(`           startedAt ${p.startedAt} (${p.startedAtPrecision}), corpus ${p.corpus}`);
      console.error(`           people    ${p.metadata.participants ? p.metadata.participants.length : 'no participant graph'}` +
        (p.metadata.augments ? `, augments ${p.metadata.augments.sourceId}` : '') +
        ` (schemaVersion ${p.metadata.schemaVersion})`);
      continue;
    }

    counts[res.status]++;
    console.error(`${res.status.padEnd(8)} ${res.path}`);

    // Nothing was written, so there is nothing new to hand the api: the drop
    // at that path was already POSTed by the pass that created it.
    if (res.status === 'current') continue;
    if (opts.noPost) continue;
    try {
      const r = await postIngest(res.path, { apiUrl: opts.apiUrl });
      post[r.status]++;
      const label = r.status === 'duplicate' ? 'already ingested' : r.status;
      console.error(`           intake ${label} (${r.httpStatus}) jobId ${r.jobId || '(none)'}`);
    } catch (e) {
      post.failed++;
      console.error(`           intake FAILED: ${e.message}`);
      console.error(`           the drop is finalized; re-POST this exact sibling, not the occurrence: ` +
        `POST ${resolveApiUrl(opts.apiUrl)}/ingests {"dropPath":${JSON.stringify(path.resolve(res.path))}}`);
    }
  }

  const emitted = opts.dryRun
    ? `planned ${counts.planned}`
    : `created ${counts.created}, exists ${counts.exists}` +
      (opts.reEmit ? `, current ${counts.current}` : '');
  console.error(`\n${emitted}, skipped ${counts.skipped}, failed ${counts.failed}` +
    (opts.dryRun ? '  (--dry-run: nothing was written)' : `  -> ${dropsRoot}`));
  if (opts.reEmit) {
    // Says how much of the migration is left. Without it a pass over a subset
    // of the archive looks identical to a finished one, while the corpus holds
    // the same person under a mail-keyed and a name-keyed identity at once.
    const { total, stale } = unmigratedPrefixes(dropsRoot);
    console.error(
      `participants: ${stale.length} of ${total} drop prefixes still carry no participants key` +
      (stale.length ? ` (oldest: ${stale[0]})` : '')
    );
  }
  if (!opts.dryRun && !opts.noPost)
    console.error(`intake: ${post.created} created, ${post.requeued} re-queued, ` +
      `${post.duplicate} already ingested, ${post.failed} failed`);

  if (counts.failed || post.failed) return 1;
  // A pass that emitted nothing at all and skipped something did not do the
  // job it was asked to do; exiting 0 would let a broken backfill look clean
  // in a script. A mixed run (some emitted, some skipped) stays 0.
  if (counts.skipped && !(counts.created + counts.exists + counts.current + counts.planned)) return 1;
  return 0;
}

module.exports = {
  SkipError,
  DEFAULT_DROPS_ROOT,
  DEFAULT_API_URL,
  DEFAULT_CORPUS,
  DEFAULT_INTAKE_TIMEOUT_MS,
  METADATA_FILENAME,
  USAGE,
  parseArgs,
  main,
  isRealCalendarDate,
  canonicalSourceId,
  parseStamp,
  parseOccurrenceDate,
  startedAtFrom,
  slugify,
  dropName,
  splitDropName,
  ORG_CHART_SUFFIX,
  EXTRACTION_MAP,
  mapParticipants,
  readParticipantGraph,
  existingDrops,
  nextDropName,
  dropIsCurrent,
  unmigratedPrefixes,
  MAX_SEQUENCE,
  planDrop,
  emitDrop,
  postIngest,
  findOccurrences,
  resolveDropsRoot,
  resolveApiUrl,
  resolveCorpus,
};

if (require.main === module) {
  main(process.argv.slice(2)).then(
    (code) => { process.exitCode = code; },
    (err) => {
      console.error('emit-drop failed:', (err && err.message) || err);
      process.exitCode = 1;
    }
  );
}
