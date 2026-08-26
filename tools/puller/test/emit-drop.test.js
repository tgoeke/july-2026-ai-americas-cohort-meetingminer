'use strict';

// Puller-side half of the "both suites validate against the schema" rule
// (AD-1): every metadata.json this tool emits is checked against
// docs/source-drop.schema.json here, independently of the server's pytest
// suite. The schema is loaded ONLY in this test file — emit-drop.js never
// reads it, so the puller still runs standing alone outside this checkout.

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');

const emit = require('../emit-drop.js');

// ---------------------------------------------------------------------------
// Schema validator (skipped, with a named reason, in a standalone checkout)
// ---------------------------------------------------------------------------

const SCHEMA_RELPATH = path.join('docs', 'source-drop.schema.json');
// A directory carrying this as well is a MeetingMiner checkout, not some
// unrelated ancestor that merely happens to own a `docs/` folder.
const REPO_MARKER = path.join('infra', 'Makefile');

// Walk UP from `startDir` rather than counting `..` segments. A fixed depth
// disarms the whole contract check the moment this package moves: the miss
// surfaces as ENOENT, the standalone branch below turns ENOENT into a skip, and
// `npm test` still exits 0 with AD-1 unchecked. Exported for the cases below —
// the property that makes this depth-proof has to be pinned, not asserted.
//
// `blocked` records an ancestor we could not read. It matters because the
// search's failure and a genuine standalone checkout must not be reported as
// the same thing: `fs.existsSync` answers a plain `false` for EACCES, which
// would walk silently past the very directory holding the answer.
function findUpward(startDir, relPath) {
  let dir = path.resolve(startDir);
  let blocked = null;
  for (;;) {
    const candidate = path.join(dir, relPath);
    try {
      if (fs.statSync(candidate).isFile()) return { found: candidate, dir, blocked };
    } catch (e) {
      // ENOENT/ENOTDIR mean "not here" — the ordinary case that keeps the walk
      // going. Anything else is a directory we were refused, so remember it.
      if (e.code !== 'ENOENT' && e.code !== 'ENOTDIR') blocked = `${dir}: ${e.code}`;
    }
    const parent = path.dirname(dir);
    if (parent === dir) return { found: null, dir: null, blocked };
    dir = parent;
  }
}

const schemaSearch = findUpward(__dirname, SCHEMA_RELPATH);
const SCHEMA_PATH = schemaSearch.found;

// Running inside this repo, the schema is always present, so failing to find it
// means the search broke rather than that the contract is absent. That makes
// the check mandatory here without anyone having to remember a flag --
// `npm test` typed in tools/puller/ is guarded exactly like `make puller-test`.
const IN_REPO = findUpward(__dirname, REPO_MARKER).found !== null;
const SCHEMA_REQUIRED = IN_REPO || process.env.MM_REQUIRE_DROP_SCHEMA === '1';

// Two outcomes, deliberately NOT collapsed into one catch:
//
//   schema file ABSENT  -> a standalone puller checkout; skip with a named
//                          reason, because the contract is not here to check.
//   schema file PRESENT -> it MUST compile and validate. A corrupt schema, a
//                          missing ajv, or a failed compile has to fail loudly;
//                          turning any of those into a skip would quietly
//                          retire AD-1's only source-side contract check.
let schemaText = null;
let schemaSkip = null;
if (SCHEMA_PATH === null) {
  const why = schemaSearch.blocked
    ? `the search was refused at ${schemaSearch.blocked}`
    : `no ${SCHEMA_RELPATH} at or above ${__dirname}`;
  if (SCHEMA_REQUIRED)
    throw new Error(
      `the drop-schema cases are required here (${
        IN_REPO ? 'running inside the repo' : 'MM_REQUIRE_DROP_SCHEMA=1'
      }) but ${why}. Refusing to skip them.`
    );
  schemaSkip = `standalone checkout: ${why}`;
} else {
  // It was there a moment ago, so anything that stops us reading it now —
  // permissions, a truncated file, a race — is a real failure, never a skip.
  try {
    schemaText = fs.readFileSync(SCHEMA_PATH, 'utf8');
  } catch (e) {
    throw new Error(`the drop schema at ${SCHEMA_PATH} exists but could not be read: ${e.message}`);
  }
}

let validate = null;
if (schemaText !== null) {
  // Everything below throws on failure — at module load, so the whole suite
  // fails rather than reporting a green run with the contract unchecked.
  const schema = JSON.parse(schemaText);
  const Ajv2020 = require('ajv/dist/2020');
  const addFormats = require('ajv-formats');
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  validate = ajv.compile(schema);
}

function assertValid(metadata) {
  assert.ok(validate, 'the schema validator was not built; this test should have been skipped');
  const ok = validate(metadata);
  assert.ok(
    ok,
    'metadata.json violates docs/source-drop.schema.json: ' +
      JSON.stringify(validate.errors, null, 2)
  );
}

const SCHEMA_TEST = schemaSkip ? { skip: schemaSkip } : {};

// A required run that failed to resolve already threw at module load, so this
// cannot assert on `schemaSkip` -- it would be unreachable-fail. What it can
// still catch is the resolution landing somewhere unexpected, and it skips
// rather than passing vacuously when the requirement is not in force, so a
// hollow run stays legible in the output.
test('a required run validates against this repo\'s own schema', { skip: SCHEMA_REQUIRED ? false : 'schema not required here' }, () => {
  assert.ok(validate, 'a required run must have compiled the schema validator');
  if (IN_REPO)
    assert.equal(
      path.resolve(SCHEMA_PATH),
      path.resolve(schemaSearch.dir, SCHEMA_RELPATH),
      'the schema must come from the nearest ancestor that carries it'
    );
});

test('findUpward returns the NEAREST match, not the farthest', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'schema-search-'));
  const near = path.join(root, 'a', 'b');
  const start = path.join(near, 'c', 'test');
  fs.mkdirSync(path.join(root, 'docs'), { recursive: true });
  fs.mkdirSync(path.join(near, 'docs'), { recursive: true });
  fs.mkdirSync(start, { recursive: true });
  fs.writeFileSync(path.join(root, 'docs', 'source-drop.schema.json'), '{"far":true}');
  fs.writeFileSync(path.join(near, 'docs', 'source-drop.schema.json'), '{"near":true}');

  const hit = findUpward(start, SCHEMA_RELPATH);
  assert.equal(hit.found, path.join(near, SCHEMA_RELPATH));
  assert.equal(JSON.parse(fs.readFileSync(hit.found, 'utf8')).near, true);
});

test('findUpward terminates at the filesystem root and reports nothing found', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'schema-search-none-'));
  const start = path.join(root, 'x', 'y', 'z');
  fs.mkdirSync(start, { recursive: true });
  // Nothing named docs/source-drop.schema.json exists anywhere above a tmpdir.
  const hit = findUpward(start, SCHEMA_RELPATH);
  assert.equal(hit.found, null);
  assert.equal(hit.blocked, null);
});

test('findUpward resolves from any depth, which is what makes the move safe', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'schema-depth-'));
  fs.mkdirSync(path.join(root, 'docs'), { recursive: true });
  fs.writeFileSync(path.join(root, 'docs', 'source-drop.schema.json'), '{}');
  for (const depth of [1, 2, 5, 9]) {
    const start = path.join(root, ...Array.from({ length: depth }, (_, i) => `d${i}`));
    fs.mkdirSync(start, { recursive: true });
    assert.equal(
      findUpward(start, SCHEMA_RELPATH).found,
      path.join(root, SCHEMA_RELPATH),
      `depth ${depth} must resolve to the same schema`
    );
  }
});

test('the validator is absent only when the schema file itself is absent', () => {
  assert.equal(
    validate === null,
    schemaSkip !== null,
    'a present-but-unusable schema must fail the suite, never downgrade to a skip'
  );
});

test('the compiled validator enforces format: date-time, not just the pattern', SCHEMA_TEST, () => {
  const base = {
    schemaVersion: 1, sourceId: 's', corpus: 'real',
    startedAt: '2026-06-10T18:15:41Z', startedAtPrecision: 'second', provenance: {},
  };
  assert.equal(validate(base), true);
  // Matches the schema's pattern but is not a real instant: only ajv-formats
  // catches this, so its absence would silently weaken every assertion here.
  assert.equal(validate({ ...base, startedAt: '2026-13-10T10:10:10Z' }), false);
  assert.equal(validate({ ...base, startedAt: '2026-06-10T99:15:41Z' }), false);
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const STREAM_BASE =
  'https://contoso-my.sharepoint.com/personal/41883_contoso_com/_layouts/15/stream.aspx';

function streamUrl(recordingName, extraParams = '&referrer=StreamWebApp%2EWeb&referrerScenario=AddressBarCopied%2Eview%2Eabc') {
  const id = `/personal/41883_contoso_com/Documents/Recordings/${recordingName}`;
  return `${STREAM_BASE}?id=${encodeURIComponent(id)}${extraParams}`;
}

let roots = [];
function tmpRoot(label) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), `emit-drop-${label}-`));
  roots.push(dir);
  return dir;
}
test.after(() => {
  for (const r of roots) {
    try { fs.rmSync(r, { recursive: true, force: true }); } catch {}
  }
  roots = [];
});

// Build one occurrence directory exactly the way the puller lays it out:
// "<Title>/<M.D.YY>/" holding "<M.D.YY> <Title>.<ext>" files plus _source.json.
function makeOccurrence(root, {
  title = 'Fabrikam Data Hub Demo',
  date = '6.10.26',
  recordingName = 'Fabrikam Data Hub Demo-20260610_181541UTC-Meeting Recording.mp4',
  dateSource = 'migrate-layout.js (from pulls.jsonl)',
  exts = ['.txt'],
  extraFiles = [],
  url = null,
  dirName = '', // occurrence folder name; defaults to the date
  sidecar = undefined, // raw string overrides the JSON body (malformed-sidecar case)
  chart = undefined, // "<stem> org chart.json": an object, or a raw string
} = {}) {
  const dir = path.join(root, title, dirName || date || '_undated');
  fs.mkdirSync(dir, { recursive: true });
  // The puller's own rule: "<date> <title>.<ext>", or bare "<title>.<ext>" in
  // the undated layout.
  const stem = date ? `${date} ${title}` : title;
  for (const ext of exts) fs.writeFileSync(path.join(dir, stem + ext), `content of ${stem}${ext}\n`);
  if (chart !== undefined) {
    fs.writeFileSync(
      path.join(dir, stem + emit.ORG_CHART_SUFFIX),
      typeof chart === 'string' ? chart : JSON.stringify(chart, null, 2) + '\n'
    );
  }
  for (const name of extraFiles) fs.writeFileSync(path.join(dir, name), `extra ${name}\n`);
  if (sidecar !== undefined) {
    fs.writeFileSync(path.join(dir, '_source.json'), sidecar);
  } else {
    fs.writeFileSync(
      path.join(dir, '_source.json'),
      JSON.stringify(
        {
          url: url || streamUrl(recordingName),
          recordingName,
          title,
          date,
          dateSource,
          pulledAt: '2026-08-05T21:06:38.788Z',
        },
        null,
        2
      ) + '\n'
    );
  }
  return dir;
}

function dropFiles(dropPath) {
  return fs.readdirSync(dropPath).sort();
}
function readMetadata(dropPath) {
  return JSON.parse(fs.readFileSync(path.join(dropPath, 'metadata.json'), 'utf8'));
}

// ---------------------------------------------------------------------------
// Pure mapping helpers
// ---------------------------------------------------------------------------

test('canonicalSourceId keeps only the identifying id parameter', () => {
  const a = emit.canonicalSourceId(streamUrl('Rec-20260610_181541UTC-Meeting Recording.mp4'));
  const b = emit.canonicalSourceId(
    streamUrl('Rec-20260610_181541UTC-Meeting Recording.mp4', '&referrer=Teams&isDarkMode=true')
  );
  assert.equal(a, b, 'copy-variant referrer params must not change the sourceId');
  assert.ok(!/referrer/.test(a));
  assert.ok(a.startsWith(STREAM_BASE + '?id='));
  assert.match(a, /Meeting%20Recording\.mp4$/);
});

test('canonicalSourceId rejects a url with no id parameter', () => {
  assert.throws(() => emit.canonicalSourceId('https://example.com/x'), emit.SkipError);
  assert.throws(() => emit.canonicalSourceId('not a url'), emit.SkipError);
});

test('a UTC-suffixed stamp gives that instant at second precision', () => {
  assert.deepEqual(
    emit.startedAtFrom({
      recordingName: 'Fabrikam Data Hub Demo-20260610_181541UTC-Meeting Recording.mp4',
      date: '6.10.26',
    }),
    { startedAt: '2026-06-10T18:15:41Z', startedAtPrecision: 'second' }
  );
});

test('an un-suffixed stamp falls back to the occurrence date at day precision', () => {
  // The un-suffixed stamp is in the ORGANIZER's timezone, which the puller
  // does not know; converting it would write a wrong instant under "second".
  assert.deepEqual(
    emit.startedAtFrom({
      recordingName: 'Contract Templates-20260702_080704-Meeting Recording.mp4',
      date: '7.2.26',
    }),
    { startedAt: '2026-07-02T00:00:00Z', startedAtPrecision: 'day' }
  );
});

test('no stamp at all still yields the occurrence date at day precision', () => {
  assert.deepEqual(
    emit.startedAtFrom({ recordingName: 'Some hand-uploaded recording.mp4', date: '4.28.26' }),
    { startedAt: '2026-04-28T00:00:00Z', startedAtPrecision: 'day' }
  );
});

test('startedAtFrom skips an occurrence with no usable date signal', () => {
  assert.throws(() => emit.startedAtFrom({ recordingName: 'x.mp4', date: 'nonsense' }), emit.SkipError);
});

test('dropName is deterministic and derived from sourceId', () => {
  const args = { startedAt: '2026-06-10T18:15:41Z', title: 'Fabrikam Data Hub Demo', sourceId: 'abc' };
  const name = emit.dropName(args);
  assert.equal(name, emit.dropName({ ...args }));
  assert.match(name, /^2026-06-10-fabrikam-data-hub-demo-[0-9a-f]{8}$/);
  assert.notEqual(name, emit.dropName({ ...args, sourceId: 'abd' }));
});

test('slugify collapses punctuation and never returns an empty slug', () => {
  assert.equal(emit.slugify('Vendor Portal- R2C Demo & Feedback'), 'vendor-portal-r2c-demo-feedback');
  assert.equal(emit.slugify('***'), 'untitled');
});

// ---------------------------------------------------------------------------
// Emit — layout
// ---------------------------------------------------------------------------

test('transcript-only occurrence emits metadata + transcript files, no recording', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt', '.vtt'] });
  const res = emit.emitDrop(dir, { dropsRoot: drops });
  assert.equal(res.status, 'created');
  assert.deepEqual(dropFiles(res.path), ['metadata.json', 'transcript.txt', 'transcript.vtt']);
});

test('an occurrence with a recording additionally carries recording.mp4', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt', '.vtt', '.mp4'] });
  const res = emit.emitDrop(dir, { dropsRoot: drops });
  assert.deepEqual(dropFiles(res.path), [
    'metadata.json', 'recording.mp4', 'transcript.txt', 'transcript.vtt',
  ]);
  assert.equal(
    fs.readFileSync(path.join(res.path, 'recording.mp4'), 'utf8'),
    fs.readFileSync(path.join(dir, '6.10.26 Fabrikam Data Hub Demo.mp4'), 'utf8')
  );
});

test('the generated extraction documents are carried; strays and .docx are not', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, {
    exts: ['.txt', '.vtt'],
    extraFiles: [
      '6.10.26 Fabrikam Data Hub Demo.docx',
      '6.10.26 Fabrikam Data Hub Demo.md',
      '6.10.26 Fabrikam Data Hub Demo action items.md',
      // Matched on the built filename, never on the ".md" extension, so the
      // org chart cannot be mistaken for a summary.
      '6.10.26 Fabrikam Data Hub Demo org chart.md',
      '11_59 AM - Fabrikam Data Hub Demo_transcript.txt',
      '11_59 AM - Fabrikam Data Hub Demo_transcript.vtt',
      '11_59 AM - Fabrikam Data Hub Demo.md',
    ],
  });
  const res = emit.emitDrop(dir, { dropsRoot: drops });
  assert.deepEqual(dropFiles(res.path), [
    'extraction-action-items.md',
    'extraction-summary.md',
    'metadata.json',
    'transcript.txt',
    'transcript.vtt',
  ]);
  // The stem-matched export won, not the stray one.
  assert.equal(
    fs.readFileSync(path.join(res.path, 'transcript.txt'), 'utf8'),
    'content of 6.10.26 Fabrikam Data Hub Demo.txt\n'
  );
  // And the stem-matched summary won, not the stray "<other stem>.md".
  assert.equal(
    fs.readFileSync(path.join(res.path, 'extraction-summary.md'), 'utf8'),
    'extra 6.10.26 Fabrikam Data Hub Demo.md\n'
  );
  assert.equal(
    fs.readFileSync(path.join(res.path, 'extraction-action-items.md'), 'utf8'),
    'extra 6.10.26 Fabrikam Data Hub Demo action items.md\n'
  );
});

test('an occurrence with no generated documents emits the drop it always emitted', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  const res = emit.emitDrop(dir, { dropsRoot: drops });
  assert.deepEqual(dropFiles(res.path), ['metadata.json', 'transcript.txt']);
  const md = readMetadata(res.path);
  assert.ok(!('extractions' in md), 'the key is omitted, never emitted as {}');
  assert.equal(md.schemaVersion, 1, 'and the drop stays version 1');
});

test('a drop carrying only one generated document declares only that one', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, {
    exts: ['.txt'],
    extraFiles: ['6.10.26 Fabrikam Data Hub Demo action items.md'],
  });
  const res = emit.emitDrop(dir, { dropsRoot: drops });
  assert.deepEqual(dropFiles(res.path), [
    'extraction-action-items.md', 'metadata.json', 'transcript.txt',
  ]);
  const md = readMetadata(res.path);
  assert.deepEqual(md.extractions, { actionItems: 'extraction-action-items.md' });
  assert.equal(md.schemaVersion, 3);
});

test('the extraction documents stay out of plan.files, so re-emit semantics are unchanged', () => {
  const src = tmpRoot('src');
  const dir = makeOccurrence(src, {
    exts: ['.txt'],
    extraFiles: [
      '6.10.26 Fabrikam Data Hub Demo.md',
      '6.10.26 Fabrikam Data Hub Demo action items.md',
    ],
  });
  const plan = emit.planDrop(dir);
  // dropIsCurrent() and evidencePresentIn() both read plan.files as the
  // *evidence* set. A summary in there would look like newly found evidence.
  assert.deepEqual(plan.files.map((f) => f.to), ['transcript.txt']);
  assert.deepEqual(plan.summaries.map((f) => f.to), [
    'extraction-summary.md', 'extraction-action-items.md',
  ]);
});

test('a summary does not make a drop current, and does not re-arm an occurrence', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  const first = emit.emitDrop(dir, { dropsRoot: drops });
  assert.equal(first.status, 'created');

  // The summariser ran after the drop was emitted. That is not evidence the
  // occurrence lacks, so intake would refuse a sibling for it — and the
  // puller does not write what the door will not take.
  for (const name of ['6.10.26 Fabrikam Data Hub Demo.md', '6.10.26 Fabrikam Data Hub Demo action items.md'])
    fs.writeFileSync(path.join(dir, name), 'generated later\n');

  const again = emit.emitDrop(dir, { dropsRoot: drops, reEmit: true });
  assert.equal(again.status, 'current');
  assert.deepEqual(dropFiles(first.path), ['metadata.json', 'transcript.txt']);
});

test('the occurrence directory is never mutated by an emit', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt', '.vtt', '.mp4'] });
  const before = dropFiles(dir);
  const sidecarBefore = fs.readFileSync(path.join(dir, '_source.json'), 'utf8');
  emit.emitDrop(dir, { dropsRoot: drops });
  assert.deepEqual(dropFiles(dir), before);
  assert.equal(fs.readFileSync(path.join(dir, '_source.json'), 'utf8'), sidecarBefore);
});

// ---------------------------------------------------------------------------
// Emit — metadata
// ---------------------------------------------------------------------------

// The metadata shape is a behavioral fact of this tool, so it is asserted
// unconditionally; only the "does it satisfy the shared schema" half is gated
// on the schema being present.
function emitOne(overrides = {}) {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'], ...(overrides.occurrence || {}) });
  const res = emit.emitDrop(dir, { dropsRoot: drops, ...(overrides.emit || {}) });
  return { src, drops, dir, res, metadata: readMetadata(res.path) };
}

test('metadata carries exactly the schema keys, with provenance embedded verbatim', () => {
  const { dir, metadata: md } = emitOne();
  assert.deepEqual(Object.keys(md).sort(), [
    'corpus', 'provenance', 'schemaVersion', 'sourceId', 'startedAt', 'startedAtPrecision',
  ]);
  assert.ok(
    !('extractions' in md),
    'an occurrence with no generated documents emits the drop it always emitted'
  );
  assert.equal(md.schemaVersion, 1);
  assert.equal(md.corpus, 'real');
  assert.equal(md.startedAt, '2026-06-10T18:15:41Z');
  assert.equal(md.startedAtPrecision, 'second');
  assert.ok(
    !('participants' in md),
    'an occurrence with no org chart emits the drop it always emitted'
  );
  assert.deepEqual(md.provenance, JSON.parse(fs.readFileSync(path.join(dir, '_source.json'), 'utf8')));
});

test('that same metadata validates against docs/source-drop.schema.json', SCHEMA_TEST, () => {
  assertValid(emitOne().metadata);
});

// Version 2 and `augments` are reachable only through --re-emit (below). An
// ordinary emit is still exactly the version 1 drop it always was, which is
// what keeps every pull and the --all backfill unchanged.
test('an ordinary emit is still a version 1 drop, and still valid', SCHEMA_TEST, () => {
  const md = emitOne().metadata;
  assert.equal(md.schemaVersion, 1, 'an ordinary emit does not emit version 2 drops');
  assert.ok(!('augments' in md), 'and never declares an augmentation');
  assertValid(md);
});

test('a hand-built version 2 augmenting drop validates against the same schema', SCHEMA_TEST, () => {
  const augmenting = {
    ...emitOne().metadata,
    schemaVersion: 2,
    augments: { sourceId: 'the-transcript-only-occurrence' },
  };
  assertValid(augmenting);

  // And the fail-closed direction: `augments` on a version 1 drop is invalid,
  // so a consumer pinned to version 1 can never silently ignore the field and
  // ingest the recovered recording as a second meeting.
  assert.equal(validate({ ...augmenting, schemaVersion: 1 }), false);
});

test('a drop carrying extraction documents validates at schemaVersion 3', SCHEMA_TEST, () => {
  const { metadata: md } = emitOne({
    occurrence: {
      extraFiles: [
        '6.10.26 Fabrikam Data Hub Demo.md',
        '6.10.26 Fabrikam Data Hub Demo action items.md',
      ],
    },
  });
  assert.equal(md.schemaVersion, 3);
  assert.deepEqual(md.extractions, {
    archSummary: 'extraction-summary.md',
    actionItems: 'extraction-action-items.md',
  });
  assertValid(md);

  // Fail-closed, the same way `augments` does: a consumer pinned to an older
  // version must refuse the drop rather than ignore the declaration and pay
  // for a model pass that re-derives documents the drop already carries.
  assert.equal(validate({ ...md, schemaVersion: 2 }), false);
  assert.equal(validate({ ...md, schemaVersion: 1 }), false);
});

test('an augmenting drop that also carries extraction documents validates', SCHEMA_TEST, () => {
  // This is why the schema's `augments` gate is a MINIMUM and not a const: at
  // `const: 2` this drop would be unsatisfiable — `augments` demanding exactly
  // 2 and `extractions` demanding at least 3.
  const { metadata: md } = emitOne({
    occurrence: {
      extraFiles: [
        '6.10.26 Fabrikam Data Hub Demo.md',
        '6.10.26 Fabrikam Data Hub Demo action items.md',
      ],
    },
  });
  assertValid({ ...md, augments: { sourceId: 'the-transcript-only-occurrence' } });
});

test('a re-emit never rewrites schemaVersion 3 down to 2', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, {
    exts: ['.txt'],
    extraFiles: [
      '6.10.26 Fabrikam Data Hub Demo.md',
      '6.10.26 Fabrikam Data Hub Demo action items.md',
    ],
    chart: { people: [{ name: 'Goeke, Timothy', mail: 'timothy.goeke@contoso.com' }] },
  });
  // First emit without the chart present is not reproducible here, so emit
  // once and then force a re-emit by removing the participants the newest
  // drop declares.
  const first = emit.emitDrop(dir, { dropsRoot: drops });
  assert.equal(first.status, 'created');
  const stripped = readMetadata(first.path);
  delete stripped.participants;
  fs.writeFileSync(
    path.join(first.path, 'metadata.json'),
    JSON.stringify(stripped, null, 2) + '\n'
  );

  const again = emit.emitDrop(dir, { dropsRoot: drops, reEmit: true });
  assert.equal(again.status, 'created');
  const md = readMetadata(again.path);
  assert.equal(md.schemaVersion, 3, 'never downgraded to 2 by the augments branch');
  assert.equal(md.augments.sourceId, md.sourceId);
  if (validate) assertValid(md);
});

test('both precision paths produce the documented startedAt', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const second = emit.emitDrop(makeOccurrence(src, { exts: ['.txt'] }), { dropsRoot: drops });
  const day = emit.emitDrop(
    makeOccurrence(src, {
      title: 'Contract Templates and DQA questions',
      date: '7.2.26',
      recordingName: 'Contract Templates and DQA questions-20260702_080704-Meeting Recording.mp4',
      exts: ['.txt', '.vtt', '.mp4'],
    }),
    { dropsRoot: drops }
  );
  const a = readMetadata(second.path);
  const b = readMetadata(day.path);
  assert.equal(a.startedAtPrecision, 'second');
  assert.equal(a.startedAt, '2026-06-10T18:15:41Z');
  assert.equal(b.startedAtPrecision, 'day');
  assert.equal(b.startedAt, '2026-07-02T00:00:00Z');
});

// Both forms must satisfy the schema, and the `if/then` block pinning day
// precision to T00:00:00 is the reason this is worth its own case.
test('both precision paths validate against docs/source-drop.schema.json', SCHEMA_TEST, () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const second = emit.emitDrop(makeOccurrence(src, { exts: ['.txt'] }), { dropsRoot: drops });
  const day = emit.emitDrop(
    makeOccurrence(src, {
      title: 'Day Precision Meeting', date: '7.2.26',
      recordingName: 'Day Precision Meeting-20260702_080704-Meeting Recording.mp4',
      exts: ['.txt'],
    }),
    { dropsRoot: drops }
  );
  assertValid(readMetadata(second.path));
  assertValid(readMetadata(day.path));
});

test('--corpus scripted is carried into metadata', () => {
  assert.equal(emitOne({ emit: { corpus: 'scripted' } }).metadata.corpus, 'scripted');
});

test('a scripted-corpus drop validates against the schema', SCHEMA_TEST, () => {
  assertValid(emitOne({ emit: { corpus: 'scripted' } }).metadata);
});

test('an unknown corpus is rejected before anything is written', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  assert.throws(() => emit.emitDrop(dir, { dropsRoot: drops, corpus: 'demo' }), /corpus must be/);
  assert.ok(!fs.existsSync(drops) || fs.readdirSync(drops).length === 0);
});

// ---------------------------------------------------------------------------
// Write-once
// ---------------------------------------------------------------------------

test('re-emitting a finalized drop reports exists and changes nothing', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt', '.vtt'] });

  const first = emit.emitDrop(dir, { dropsRoot: drops });
  assert.equal(first.status, 'created');
  const snapshot = dropFiles(first.path).map((f) => {
    const p = path.join(first.path, f);
    const st = fs.statSync(p);
    return [f, st.mtimeMs, fs.readFileSync(p, 'utf8')];
  });

  // Change the source after the fact: a finalized drop must not follow it.
  fs.writeFileSync(path.join(dir, '6.10.26 Fabrikam Data Hub Demo.txt'), 'REWRITTEN\n');

  const second = emit.emitDrop(dir, { dropsRoot: drops });
  assert.equal(second.status, 'exists');
  assert.equal(second.path, first.path);
  const after = dropFiles(first.path).map((f) => {
    const p = path.join(first.path, f);
    const st = fs.statSync(p);
    return [f, st.mtimeMs, fs.readFileSync(p, 'utf8')];
  });
  assert.deepEqual(after, snapshot);
  assert.equal(fs.existsSync(path.join(drops, '.staging')), false, 'no staging residue');
});

test('a finalize race onto an existing drop is reported as exists', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  const plan = emit.planDrop(dir);
  // Simulate the other emit having finalized between existsSync and rename by
  // creating the target through a path emitDrop does not check again.
  const target = path.join(drops, plan.name);
  fs.mkdirSync(target, { recursive: true });
  fs.writeFileSync(path.join(target, 'metadata.json'), '{"already":"there"}\n');
  const res = emit.emitDrop(dir, { dropsRoot: drops });
  assert.equal(res.status, 'exists');
  assert.equal(fs.readFileSync(path.join(target, 'metadata.json'), 'utf8'), '{"already":"there"}\n');
  assert.equal(fs.existsSync(path.join(drops, '.staging')), false);
});

test(
  'staging is removed and nothing is finalized when the copy fails',
  process.getuid && process.getuid() === 0
    ? { skip: 'running as root: file mode cannot make a source file unreadable' }
    : {},
  () => {
    const src = tmpRoot('src');
    const drops = tmpRoot('drops');
    const dir = makeOccurrence(src, { exts: ['.txt'] });
    const txt = path.join(dir, '6.10.26 Fabrikam Data Hub Demo.txt');
    const plan = emit.planDrop(dir);
    fs.chmodSync(txt, 0o000); // the copy will fail with EACCES
    try {
      assert.throws(() => emit.emitDrop(dir, { dropsRoot: drops }), /EACCES|permission/i);
    } finally {
      fs.chmodSync(txt, 0o644);
    }
    assert.equal(fs.existsSync(path.join(drops, '.staging')), false, 'staging removed on the error path');
    assert.equal(fs.existsSync(path.join(drops, plan.name)), false, 'no half-built drop finalized');
    assert.equal(fs.readdirSync(drops).length, 0);
  }
);

// ---------------------------------------------------------------------------
// Skips and failures
// ---------------------------------------------------------------------------

test('an occurrence with no evidence file is skipped with a named reason', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: [], extraFiles: ['6.10.26 Fabrikam Data Hub Demo.md'] });
  assert.throws(() => emit.emitDrop(dir, { dropsRoot: drops }), (e) => {
    assert.ok(e instanceof emit.SkipError);
    assert.match(e.message, /no canonical evidence file/);
    return true;
  });
  assert.ok(!fs.existsSync(drops) || fs.readdirSync(drops).length === 0);
});

test('a malformed _source.json is skipped with a named reason', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'], sidecar: '{ not json' });
  assert.throws(() => emit.emitDrop(dir, { dropsRoot: drops }), (e) => {
    assert.ok(e instanceof emit.SkipError);
    assert.match(e.message, /not valid JSON/);
    return true;
  });
});

test('a missing _source.json is skipped with a named reason', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = path.join(src, 'No Sidecar', '1.1.26');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, '1.1.26 No Sidecar.txt'), 'x\n');
  assert.throws(() => emit.emitDrop(dir, { dropsRoot: drops }), (e) => {
    assert.ok(e instanceof emit.SkipError);
    assert.match(e.message, /could not be read/);
    return true;
  });
});

// ---------------------------------------------------------------------------
// Dry run and archive scan
// ---------------------------------------------------------------------------

test('--dry-run plans the drop and writes nothing', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt', '.vtt'] });
  const res = emit.emitDrop(dir, { dropsRoot: drops, dryRun: true });
  assert.equal(res.status, 'planned');
  assert.equal(res.path, null);
  assert.deepEqual(res.plan.files.map((f) => f.to), ['transcript.vtt', 'transcript.txt']);
  assert.equal(fs.readdirSync(drops).length, 0, '--dry-run wrote into the drops folder');
});

test('findOccurrences keys on the _source.json sidecar, not on folder shape', () => {
  const src = tmpRoot('src');
  makeOccurrence(src, { exts: ['.txt'] });
  makeOccurrence(src, { title: 'Daily Standup', date: '8.4.26', exts: ['.txt'] });
  // A batch-mirror folder: looks like an occurrence, has no sidecar.
  const mirror = path.join(src, 'Recordings and Transcripts', '7.1.26');
  fs.mkdirSync(mirror, { recursive: true });
  fs.writeFileSync(path.join(mirror, 'something.mp4'), 'x\n');
  // Dotdirs and node_modules are never descended into.
  fs.mkdirSync(path.join(src, '.transcript-profile', 'x'), { recursive: true });
  fs.writeFileSync(path.join(src, '.transcript-profile', 'x', '_source.json'), '{}');
  fs.mkdirSync(path.join(src, 'node_modules', 'y'), { recursive: true });
  fs.writeFileSync(path.join(src, 'node_modules', 'y', '_source.json'), '{}');

  const found = emit.findOccurrences(src);
  assert.equal(found.length, 2);
  assert.ok(found.every((d) => fs.existsSync(path.join(d, '_source.json'))));
});

// ---------------------------------------------------------------------------
// Backfill shape: many occurrences at once, all schema-valid
// ---------------------------------------------------------------------------

test('a whole-archive pass emits one drop per occurrence and is idempotent', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const specs = [
    { title: 'Alpha Sync', date: '6.10.26', recordingName: 'Alpha Sync-20260610_181541UTC-Meeting Recording.mp4', exts: ['.txt', '.vtt', '.mp4'] },
    { title: 'Beta Review', date: '7.2.26', recordingName: 'Beta Review-20260702_080704-Meeting Recording.mp4', exts: ['.txt', '.vtt'] },
    { title: 'Gamma Standup', date: '8.4.26', recordingName: 'Gamma Standup no stamp.mp4', exts: ['.txt'] },
  ];
  for (const s of specs) makeOccurrence(src, s);

  const dirs = emit.findOccurrences(src);
  assert.equal(dirs.length, specs.length);

  const results = dirs.map((d) => emit.emitDrop(d, { dropsRoot: drops }));
  assert.deepEqual(results.map((r) => r.status), ['created', 'created', 'created']);

  const names = fs.readdirSync(drops).sort();
  assert.equal(names.length, specs.length);
  const precisions = { second: 0, day: 0 };
  let recordings = 0, vtts = 0, txts = 0;
  for (const n of names) {
    const md = readMetadata(path.join(drops, n));
    if (validate) assertValid(md);
    assert.equal(md.corpus, 'real');
    precisions[md.startedAtPrecision]++;
    const files = dropFiles(path.join(drops, n));
    if (files.includes('recording.mp4')) recordings++;
    if (files.includes('transcript.vtt')) vtts++;
    if (files.includes('transcript.txt')) txts++;
    assert.ok(!files.some((f) => f.endsWith('.docx') || f.endsWith('.md')));
  }
  assert.deepEqual(precisions, { second: 1, day: 2 });
  assert.equal(recordings, 1);
  assert.equal(vtts, 2);
  assert.equal(txts, 3);

  const again = dirs.map((d) => emit.emitDrop(d, { dropsRoot: drops }));
  assert.deepEqual(again.map((r) => r.status), ['exists', 'exists', 'exists']);
  assert.equal(fs.existsSync(path.join(drops, '.staging')), false);
});

// ---------------------------------------------------------------------------
// Intake
// ---------------------------------------------------------------------------

test('postIngest maps 201 / 200 / 409 onto named statuses', async () => {
  const http = require('node:http');
  const replies = [
    [201, { jobId: 'job-1' }],
    [200, { jobId: 'job-2' }],
    [409, { title: 'duplicate-source', jobId: 'job-3' }],
  ];
  const seen = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      seen.push({ url: req.url, body: JSON.parse(body) });
      const [code, payload] = replies.shift();
      res.writeHead(code, { 'content-type': 'application/json' });
      res.end(JSON.stringify(payload));
    });
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const apiUrl = `http://127.0.0.1:${server.address().port}`;
  try {
    assert.deepEqual(await emit.postIngest('/tmp/drop-a', { apiUrl }), {
      status: 'created', jobId: 'job-1', httpStatus: 201,
    });
    assert.deepEqual(await emit.postIngest('/tmp/drop-a', { apiUrl }), {
      status: 'requeued', jobId: 'job-2', httpStatus: 200,
    });
    assert.deepEqual(await emit.postIngest('/tmp/drop-a', { apiUrl }), {
      status: 'duplicate', jobId: 'job-3', httpStatus: 409,
    });
    assert.deepEqual(seen.map((s) => s.url), ['/ingests', '/ingests', '/ingests']);
    assert.deepEqual(seen[0].body, { dropPath: '/tmp/drop-a' });
  } finally {
    await new Promise((r) => server.close(r));
  }
});

test('postIngest names an unreachable api rather than throwing a bare fetch error', async () => {
  // Port 1 on loopback refuses connections immediately.
  await assert.rejects(
    emit.postIngest('/tmp/drop-a', { apiUrl: 'http://127.0.0.1:1' }),
    /POST http:\/\/127\.0\.0\.1:1\/ingests failed \(is the api running\?\)/
  );
});

test('postIngest raises a named error for a rejected drop', async () => {
  const http = require('node:http');
  const server = http.createServer((req, res) => {
    res.writeHead(422, { 'content-type': 'application/problem+json' });
    res.end(JSON.stringify({ title: 'invalid-drop', detail: 'metadata.json violates the schema' }));
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const apiUrl = `http://127.0.0.1:${server.address().port}`;
  try {
    await assert.rejects(
      emit.postIngest('/tmp/drop-a', { apiUrl }),
      /rejected the drop \(422\): metadata\.json violates the schema/
    );
  } finally {
    await new Promise((r) => server.close(r));
  }
});

test('postIngest does not mistake an augmentation refusal for a duplicate', async () => {
  const http = require('node:http');
  const server = http.createServer((req, res) => {
    res.writeHead(409, { 'content-type': 'application/problem+json' });
    res.end(JSON.stringify({ type: 'urn:meetingminer:problem:augment-adds-nothing', detail: 'no new evidence' }));
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  try {
    await assert.rejects(
      emit.postIngest('/tmp/drop-a', { apiUrl: `http://127.0.0.1:${server.address().port}` }),
      /rejected the drop \(409\): no new evidence/
    );
  } finally {
    await new Promise((r) => server.close(r));
  }
});

// ---------------------------------------------------------------------------
// Black-box seam
// ---------------------------------------------------------------------------

test('emit-drop.js loads no schema, no server code, and no server config', () => {
  const text = fs.readFileSync(path.resolve(__dirname, '..', 'emit-drop.js'), 'utf8');
  const code = text
    .split('\n')
    .filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l))
    .join('\n');
  assert.ok(!/require\(['"][^'"]*server/.test(code), 'must not require anything from server/');
  assert.ok(!/source-drop\.schema\.json/.test(code), 'the schema is a test-time dependency only');
  // Reading process.env for MM_DROPS_ROOT / MM_API_URL / MM_CORPUS is the
  // puller's own regime; what is forbidden is reading the server's config.yaml
  // or its .env file.
  assert.ok(!/config\.yaml/.test(code), 'must not read the server config.yaml');
  assert.ok(!/['"][^'"]*\.env['"]/.test(code), 'must not read a .env file');
  assert.ok(!/MM_CONFIG|MM_CONTENT_ROOT/.test(code), 'must not read the server config regime');
  assert.ok(!/graph\.microsoft\.com/i.test(code), 'no Microsoft Graph');
});

// ---------------------------------------------------------------------------
// Impossible dates and times must SKIP, never emit
// ---------------------------------------------------------------------------
//
// The stamp digits are matched positionally, so a corrupt recording name
// yields month 13 or hour 99 and a syntactically well-formed but impossible
// startedAt. The api rejects those with 422 — and by then the drop is
// finalized write-once, so the occurrence could never be ingested and nothing
// is allowed to delete the drop. Validation therefore has to happen before
// anything is written.

test('isRealCalendarDate rejects days that do not exist', () => {
  assert.equal(emit.isRealCalendarDate(2026, 2, 28), true);
  assert.equal(emit.isRealCalendarDate(2024, 2, 29), true); // leap year
  assert.equal(emit.isRealCalendarDate(2026, 2, 29), false);
  assert.equal(emit.isRealCalendarDate(2026, 2, 31), false);
  assert.equal(emit.isRealCalendarDate(2026, 4, 31), false);
  assert.equal(emit.isRealCalendarDate(2026, 13, 10), false);
  assert.equal(emit.isRealCalendarDate(2026, 0, 10), false);
});

test('parseStamp skips an impossible clock time', () => {
  for (const name of [
    'x-20260610_991541UTC-y.mp4', // hour 99
    'x-20260610_186541UTC-y.mp4', // minute 65
    'x-20260610_181599UTC-y.mp4', // second 99
  ]) {
    assert.throws(() => emit.parseStamp(name), (e) => {
      assert.ok(e instanceof emit.SkipError);
      assert.match(e.message, /impossible clock time/);
      return true;
    });
  }
});

test('parseStamp skips a date that does not exist', () => {
  for (const name of ['x-20261310_101010UTC-y.mp4', 'x-20260231_101010-y.mp4']) {
    assert.throws(() => emit.parseStamp(name), (e) => {
      assert.ok(e instanceof emit.SkipError);
      assert.match(e.message, /date that does not exist/);
      return true;
    });
  }
});

test('parseOccurrenceDate rejects a date that does not exist', () => {
  assert.equal(emit.parseOccurrenceDate('2.31.26'), null);
  assert.equal(emit.parseOccurrenceDate('13.1.26'), null);
  assert.equal(emit.parseOccurrenceDate('2.29.26'), null);
  assert.deepEqual(emit.parseOccurrenceDate('2.29.24'), { year: 2024, month: 2, day: 29 });
});

test('startedAtFrom skips rather than emitting an impossible instant', () => {
  // Every one of these used to produce a schema-invalid startedAt.
  assert.throws(
    () => emit.startedAtFrom({ recordingName: 'x-20261310_101010UTC-y.mp4', date: '' }),
    emit.SkipError
  );
  assert.throws(
    () => emit.startedAtFrom({ recordingName: 'x-20260610_991541UTC-y.mp4', date: '6.10.26' }),
    emit.SkipError
  );
  assert.throws(
    () => emit.startedAtFrom({ recordingName: 'no stamp here.mp4', date: '2.31.26' }),
    emit.SkipError
  );
});

test('the api would have rejected those instants, so nothing may be written', SCHEMA_TEST, () => {
  const base = {
    schemaVersion: 1, sourceId: 's', corpus: 'real',
    startedAtPrecision: 'second', provenance: {},
  };
  for (const startedAt of ['2026-13-10T10:10:10Z', '2026-06-10T99:15:41Z']) {
    assert.equal(validate({ ...base, startedAt }), false);
  }
  assert.equal(
    validate({ ...base, startedAtPrecision: 'day', startedAt: '2026-02-31T00:00:00Z' }),
    false
  );
});

test('an occurrence with a corrupt stamp is skipped and no drop is written', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, {
    recordingName: 'Fabrikam Data Hub Demo-20261310_101010UTC-Meeting Recording.mp4',
    exts: ['.txt'],
  });
  assert.throws(() => emit.emitDrop(dir, { dropsRoot: drops }), (e) => {
    assert.ok(e instanceof emit.SkipError);
    assert.match(e.message, /date that does not exist/);
    return true;
  });
  assert.equal(fs.readdirSync(drops).length, 0, 'a drop that can never be ingested was written');
});

// ---------------------------------------------------------------------------
// sourceId protocol
// ---------------------------------------------------------------------------

test('canonicalSourceId rejects a non-http(s) url', () => {
  // file:/data: URLs stringify their origin as "null", which would give several
  // occurrences the same sourceId.
  for (const u of ['file:///tmp/x?id=abc', 'data:text/plain,x', 'ftp://h/x?id=abc']) {
    assert.throws(() => emit.canonicalSourceId(u), (e) => {
      assert.ok(e instanceof emit.SkipError);
      assert.match(e.message, /not an http\(s\) URL/);
      return true;
    });
  }
  assert.ok(emit.canonicalSourceId('http://h/p?id=abc').startsWith('http://h/p?id='));
});

// ---------------------------------------------------------------------------
// A non-directory at the drop path
// ---------------------------------------------------------------------------

test('a plain file at the drop path is a named error, not "exists"', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  const plan = emit.planDrop(dir);
  fs.writeFileSync(path.join(drops, plan.name), 'not a drop\n');
  assert.throws(
    () => emit.emitDrop(dir, { dropsRoot: drops }),
    /drop target exists but is not a directory/
  );
});

// ---------------------------------------------------------------------------
// The puller's undated layout
// ---------------------------------------------------------------------------

test('an undated occurrence maps its bare "<title>.<ext>" files', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  // run() sets `base = stem` when there is no date, so the files carry no
  // "M.D.YY " prefix and _source.json's date is empty.
  const dir = makeOccurrence(src, {
    title: 'My Meeting',
    date: '',
    recordingName: 'My Meeting-20260610_181541UTC-Meeting Recording.mp4',
    exts: ['.txt', '.vtt'],
  });
  assert.ok(fs.existsSync(path.join(dir, 'My Meeting.txt')));
  const res = emit.emitDrop(dir, { dropsRoot: drops });
  assert.equal(res.status, 'created');
  assert.deepEqual(dropFiles(res.path), ['metadata.json', 'transcript.txt', 'transcript.vtt']);
  // The UTC stamp still supplies the instant even with no date field.
  assert.equal(readMetadata(res.path).startedAtPrecision, 'second');
});

test('an undated occurrence with no stamp falls back to the stamp-less skip', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, {
    title: 'My Meeting', date: '', recordingName: 'My Meeting.mp4', exts: ['.txt'],
  });
  assert.throws(() => emit.emitDrop(dir, { dropsRoot: drops }), (e) => {
    assert.ok(e instanceof emit.SkipError);
    assert.match(e.message, /no usable date/);
    return true;
  });
});

// ---------------------------------------------------------------------------
// Intake timeout
// ---------------------------------------------------------------------------

test('postIngest gives up on an api that accepts and never answers', async () => {
  const http = require('node:http');
  const sockets = [];
  const server = http.createServer((req, res) => { sockets.push(res); /* never respond */ });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const apiUrl = `http://127.0.0.1:${server.address().port}`;
  try {
    const started = Date.now();
    await assert.rejects(
      emit.postIngest('/tmp/drop-a', { apiUrl, timeoutMs: 150 }),
      /failed \(is the api running\?\): no response within 150ms/
    );
    assert.ok(Date.now() - started < 5000, 'the timeout did not fire');
  } finally {
    for (const res of sockets) { try { res.destroy(); } catch {} }
    server.closeAllConnections();
    await new Promise((r) => server.close(r));
  }
});

test('the default intake timeout is finite', () => {
  assert.ok(Number.isFinite(emit.DEFAULT_INTAKE_TIMEOUT_MS));
  assert.ok(emit.DEFAULT_INTAKE_TIMEOUT_MS > 0);
});

// ---------------------------------------------------------------------------
// Resolution order and env vars
// ---------------------------------------------------------------------------

function withEnv(vars, fn) {
  const saved = {};
  for (const k of Object.keys(vars)) {
    saved[k] = process.env[k];
    if (vars[k] === undefined) delete process.env[k];
    else process.env[k] = vars[k];
  }
  try {
    return fn();
  } finally {
    for (const k of Object.keys(saved)) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
}

test('MM_DROPS_ROOT is honored, and --drops beats it', () => {
  withEnv({ MM_DROPS_ROOT: '/tmp/from-env' }, () => {
    assert.equal(emit.resolveDropsRoot(''), '/tmp/from-env');
    assert.equal(emit.resolveDropsRoot('/tmp/from-flag'), '/tmp/from-flag');
  });
  withEnv({ MM_DROPS_ROOT: undefined }, () => {
    assert.equal(emit.resolveDropsRoot(''), emit.DEFAULT_DROPS_ROOT);
  });
});

test('MM_API_URL is honored, --api beats it, trailing slashes are stripped', () => {
  withEnv({ MM_API_URL: 'http://env-host:9000/' }, () => {
    assert.equal(emit.resolveApiUrl(''), 'http://env-host:9000');
    assert.equal(emit.resolveApiUrl('http://flag-host:1/'), 'http://flag-host:1');
    assert.equal(emit.resolveApiUrl('http://flag-host:1///'), 'http://flag-host:1');
  });
  withEnv({ MM_API_URL: undefined }, () => {
    assert.equal(emit.resolveApiUrl(''), emit.DEFAULT_API_URL);
  });
});

test('MM_CORPUS is honored, --corpus beats it, and both are validated', () => {
  withEnv({ MM_CORPUS: 'scripted' }, () => {
    assert.equal(emit.resolveCorpus(''), 'scripted');
    assert.equal(emit.resolveCorpus('real'), 'real');
  });
  withEnv({ MM_CORPUS: 'demo' }, () => {
    assert.throws(() => emit.resolveCorpus(''), /corpus must be/);
  });
  withEnv({ MM_CORPUS: undefined }, () => {
    assert.equal(emit.resolveCorpus(''), emit.DEFAULT_CORPUS);
  });
});

test('a drop emitted with MM_DROPS_ROOT set lands there', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  const res = withEnv({ MM_DROPS_ROOT: drops }, () => emit.emitDrop(dir, {}));
  // path.resolve, not realpath: /var is a symlink to /private/var on macOS
  // and emitDrop must not silently rewrite the folder the user named.
  assert.equal(path.dirname(res.path), path.resolve(drops));
  assert.ok(fs.existsSync(path.join(drops, path.basename(res.path))));
});

// ---------------------------------------------------------------------------
// emit-drop CLI: parseArgs and main
// ---------------------------------------------------------------------------

test('parseArgs maps argv onto options', () => {
  assert.deepEqual(emit.parseArgs(['--all', '--dry-run', '--no-post']), {
    dirs: [], all: true, dryRun: true, reEmit: false, noPost: true, help: false,
    dropsRoot: '', apiUrl: '', corpus: '',
  });
  assert.deepEqual(emit.parseArgs(['a', 'b', '--drops', '/d', '--api', 'http://h', '--corpus', 'scripted']), {
    dirs: ['a', 'b'], all: false, dryRun: false, reEmit: false, noPost: false, help: false,
    dropsRoot: '/d', apiUrl: 'http://h', corpus: 'scripted',
  });
  assert.equal(emit.parseArgs(['--all', '--re-emit']).reEmit, true);
  assert.equal(emit.parseArgs(['-h']).help, true);
  assert.equal(emit.parseArgs(['--help']).help, true);
});

test('parseArgs rejects a value flag swallowing the next option', () => {
  // Without this, `--drops --dry-run` writes drops into a folder named
  // "--dry-run" on a run the user asked to write nothing.
  assert.throws(() => emit.parseArgs(['--drops', '--dry-run']), /--drops needs a value, but got the option --dry-run/);
  assert.throws(() => emit.parseArgs(['--api']), /--api needs a value/);
  assert.throws(() => emit.parseArgs(['--drops', '/a', '--drops', '/b']), /--drops was given more than once/);
});

test('parseArgs rejects --all combined with listed directories', () => {
  assert.throws(() => emit.parseArgs(['--all', 'some/dir']), /--all covers the whole archive/);
});

test('parseArgs rejects unknown options, single dash included', () => {
  assert.throws(() => emit.parseArgs(['-x']), /unknown option -x/);
  assert.throws(() => emit.parseArgs(['--nope']), /unknown option --nope/);
  // ...but a plain path is still a positional.
  assert.deepEqual(emit.parseArgs(['some/dir']).dirs, ['some/dir']);
});

async function captureStderr(fn) {
  const lines = [];
  const original = console.error;
  console.error = (...a) => lines.push(a.map(String).join(' '));
  try {
    const result = await fn();
    return { result, out: lines.join('\n') };
  } finally {
    console.error = original;
  }
}

test('main --dry-run writes nothing and reports the plan', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt', '.vtt'] });
  const { result, out } = await captureStderr(() =>
    emit.main([dir, '--dry-run', '--drops', drops])
  );
  assert.equal(result, 0);
  assert.match(out, /^plan {5}2026-06-10-fabrikam-data-hub-demo-/m);
  assert.match(out, /planned 1, skipped 0, failed 0/);
  assert.match(out, /--dry-run: nothing was written/);
  assert.equal(fs.readdirSync(drops).length, 0);
});

test('main --no-post emits without touching the api', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  // An api url that would refuse instantly, to prove it is never called.
  const { result, out } = await captureStderr(() =>
    emit.main([dir, '--no-post', '--drops', drops, '--api', 'http://127.0.0.1:1'])
  );
  assert.equal(result, 0);
  assert.match(out, /created 1, exists 0, skipped 0, failed 0/);
  assert.ok(!/intake/.test(out), '--no-post still contacted the api');
  assert.equal(fs.readdirSync(drops).length, 1);
});

test('main POSTs each drop and reports the intake result', async () => {
  const http = require('node:http');
  const seen = [];
  let code = 201;
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      seen.push(JSON.parse(body).dropPath);
      res.writeHead(code, { 'content-type': 'application/json' });
      res.end(JSON.stringify(code === 409
        ? { type: 'urn:meetingminer:problem:duplicate-source', jobId: 'job-x' }
        : { jobId: 'job-x' }));
    });
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const apiUrl = `http://127.0.0.1:${server.address().port}`;
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  try {
    const first = await captureStderr(() => emit.main([dir, '--drops', drops, '--api', apiUrl]));
    assert.equal(first.result, 0);
    assert.match(first.out, /intake created \(201\) jobId job-x/);
    assert.match(first.out, /intake: 1 created, 0 re-queued, 0 already ingested, 0 failed/);

    code = 409;
    const second = await captureStderr(() => emit.main([dir, '--drops', drops, '--api', apiUrl]));
    assert.equal(second.result, 0, 'a duplicate is not an error');
    assert.match(second.out, /intake already ingested \(409\)/);
    assert.equal(seen.length, 2);
    assert.equal(seen[0], seen[1], 'both POSTs named the same finalized drop');
  } finally {
    await new Promise((r) => server.close(r));
  }
});

test('main exits non-zero when the api is unreachable but keeps the drop', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  const { result, out } = await captureStderr(() =>
    emit.main([dir, '--drops', drops, '--api', 'http://127.0.0.1:1'])
  );
  assert.equal(result, 1);
  assert.match(out, /intake FAILED/);
  assert.match(out, /the drop is finalized; re-POST this exact sibling/);
  assert.equal(fs.readdirSync(drops).length, 1, 'the finalized drop was not kept');
});

test('main exits non-zero when every occurrence was skipped', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const bad = makeOccurrence(src, { exts: [], extraFiles: ['6.10.26 Fabrikam Data Hub Demo.md'] });
  const skipOnly = await captureStderr(() => emit.main([bad, '--no-post', '--drops', drops]));
  assert.equal(skipOnly.result, 1, 'a pass that emitted nothing at all reported success');
  assert.match(skipOnly.out, /created 0, exists 0, skipped 1, failed 0/);

  // A mixed run still succeeds: some occurrences legitimately have no evidence.
  const good = makeOccurrence(src, { title: 'Good Meeting', date: '8.4.26', exts: ['.txt'] });
  const mixed = await captureStderr(() => emit.main([bad, good, '--no-post', '--drops', drops]));
  assert.equal(mixed.result, 0);
  assert.match(mixed.out, /created 1, exists 0, skipped 1, failed 0/);
});

test('main reports a usage error for bad argv without writing anything', async () => {
  const drops = tmpRoot('drops');
  const { result, out } = await captureStderr(() => emit.main(['--drops', '--dry-run']));
  assert.equal(result, 1);
  assert.match(out, /--drops needs a value, but got the option --dry-run/);
  assert.match(out, /Usage: node emit-drop\.js/);
  assert.equal(fs.readdirSync(drops).length, 0);
});

test('main rejects a bad --corpus before touching the filesystem', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  const { result, out } = await captureStderr(() =>
    emit.main([dir, '--corpus', 'demo', '--no-post', '--drops', drops])
  );
  assert.equal(result, 1);
  assert.match(out, /corpus must be "real" or "scripted"/);
  assert.equal(fs.readdirSync(drops).length, 0);
});

test('findOccurrences names an unreadable subtree instead of dropping it silently', (t) => {
  if (process.getuid && process.getuid() === 0) {
    t.skip('running as root: file mode cannot make a directory unreadable');
    return;
  }
  const src = tmpRoot('src');
  makeOccurrence(src, { exts: ['.txt'] });
  const locked = path.join(src, 'Locked Series');
  fs.mkdirSync(locked, { recursive: true });
  fs.chmodSync(locked, 0o000);
  const lines = [];
  const original = console.error;
  console.error = (...a) => lines.push(a.map(String).join(' '));
  try {
    const found = emit.findOccurrences(src);
    assert.equal(found.length, 1);
  } finally {
    console.error = original;
    fs.chmodSync(locked, 0o755);
  }
  assert.match(lines.join('\n'), /warning: skipping unreadable directory .*Locked Series/);
});

// ---------------------------------------------------------------------------
// grab-teams-transcript.js flag parsing
// ---------------------------------------------------------------------------
//
// This is the highest-consequence code in the hand-off and nothing else covers
// it: if the "consumed" set were off by one, `--drops /tmp/d` would make
// /tmp/d the outFile, the `if (!outFile)` branch would never run, and the
// entire drop + intake step would vanish from every pull with every other test
// here still green.

const grab = require('../grab-teams-transcript.js');

test('requiring the puller does not run it', () => {
  assert.equal(typeof grab.parseGrabArgs, 'function');
});

test('value flags never fall through as the url or the output file', () => {
  const o = grab.parseGrabArgs([
    'https://host/stream.aspx?id=1',
    '--drops', '/tmp/d', '--api', 'http://api:8000', '--corpus', 'scripted', '--date', '7.14.26',
  ]);
  assert.equal(o.url, 'https://host/stream.aspx?id=1');
  assert.equal(o.outFile, undefined, 'a flag value was read as the output file');
  assert.equal(o.dropsRoot, '/tmp/d');
  assert.equal(o.apiUrl, 'http://api:8000');
  assert.equal(o.corpus, 'scripted');
  assert.equal(o.dateArg, '7.14.26');
});

test('a real output file is still a positional', () => {
  const o = grab.parseGrabArgs(['https://host/stream.aspx?id=1', 'out.txt', '--drops', '/tmp/d']);
  assert.equal(o.url, 'https://host/stream.aspx?id=1');
  assert.equal(o.outFile, 'out.txt');
  assert.equal(o.dropsRoot, '/tmp/d');
});

test('--no-emit turns the hand-off off and is on by default', () => {
  assert.equal(grab.parseGrabArgs(['u']).wantEmit, true);
  assert.equal(grab.parseGrabArgs(['u', '--no-emit']).wantEmit, false);
});

test('the existing flags keep their meaning', () => {
  const o = grab.parseGrabArgs(['u', '--no-video', '--no-summary', '--headful', '--force', '--dry-run']);
  assert.equal(o.wantVideo, false);
  assert.equal(o.wantSummary, false);
  assert.equal(o.headful, true);
  assert.equal(o.force, true);
  assert.equal(o.dryRun, true);
  assert.equal(grab.parseGrabArgs([]).wantVideo, true);
  assert.equal(grab.parseGrabArgs(['--login']).headful, true, '--login implies headful');
});

test('--replay forwards the hand-off flags to the pulls it spawns', () => {
  assert.deepEqual(
    grab.parseGrabArgs(['--replay', '--no-emit', '--no-video', '--drops', '/tmp/d', '--corpus', 'scripted'])
      .replayPassThrough,
    ['--no-emit', '--no-video', '--drops', '/tmp/d', '--corpus', 'scripted']
  );
  assert.deepEqual(grab.parseGrabArgs(['--replay']).replayPassThrough, []);
});

test('a repeated value flag is an error, not a silent first-wins', () => {
  // `--drops a --drops b` would otherwise use `a` and read `b` as the url.
  assert.throws(() => grab.parseGrabArgs(['u', '--drops', 'a', '--drops', 'b']), /--drops was given more than once/);
});

test('a value flag with no value, or followed by an option, is an error', () => {
  assert.throws(() => grab.parseGrabArgs(['u', '--drops']), /--drops needs a value/);
  assert.throws(() => grab.parseGrabArgs(['u', '--api', '--headful']), /--api needs a value/);
});

test('bad --date and bad --corpus are named errors', () => {
  assert.throws(() => grab.parseGrabArgs(['u', '--date', 'nope']), /is not a date/);
  assert.throws(() => grab.parseGrabArgs(['u', '--corpus', 'demo']), /use "real" or "scripted"/);
  assert.equal(grab.parseGrabArgs(['u', '--corpus', 'real']).corpus, 'real');
});

// ---------------------------------------------------------------------------
// The participant graph: "<stem> org chart.json" -> metadata.participants
// ---------------------------------------------------------------------------
//
// The chart is what makes a person one identity across meetings: the pipeline
// keys participants on `mail` when the graph supplies one and falls back to the
// normalized display name only where it does not. Omitting the key — which is
// what this tool used to do unconditionally — keys every person on how their
// name happened to be typed in that meeting's transcript.

function chartRow(overrides = {}) {
  return {
    name: 'Maplewood, Micah (CNTR)',
    mail: 'micah.maplewood@contoso.com',
    title: '',
    department: '01.102.000281.110',
    deptCode: '01.102.000281.110',
    lineOfBusiness: '',
    office: '',
    org: 'CONTOSO (contractor)',
    guest: false,
    unresolved: false,
    foundIn: ['recording permissions', 'transcript'],
    invite: 'can edit',
    response: '',
    spokeTurns: 24,
    spokeWords: 226,
    managerChain: [
      { name: 'Stonebridge, Finley', title: 'Associate Project Manager', mail: 'finley.stonebridge@contoso.com' },
      { name: 'Uppingham, Zephyr', title: 'Chief Executive Officer', mail: 'zephyr.uppingham@contoso.com' },
    ],
    ...overrides,
  };
}

// The real shape: top-level generatedAt / meeting / attendeeSources / orgSource
// / people / notes, as written by the puller beside every occurrence.
function chartOf(people) {
  return {
    generatedAt: '2026-08-18T16:01:11.733Z',
    meeting: { title: 'Fabrikam Data Hub Demo', dateISO: '2026-06-10T18:15:41.000Z' },
    attendeeSources: ['recording permissions (1)', 'transcript speakers (9)'],
    orgSource: 'sharepoint',
    people,
    notes: [],
  };
}

test('mapParticipants renames name to displayName and passes everything else verbatim', () => {
  const row = chartRow();
  const { participants, warnings } = emit.mapParticipants(chartOf([row]));
  assert.deepEqual(warnings, []);
  assert.equal(participants.length, 1);
  const p = participants[0];
  assert.equal(p.displayName, 'Maplewood, Micah (CNTR)');
  assert.ok(!('name' in p), 'the chart key must not survive beside displayName');
  for (const key of Object.keys(row)) {
    if (key === 'name') continue;
    assert.deepEqual(p[key], row[key], `${key} was not passed through verbatim`);
  }
  // managerChain in particular: that is what reaches meeting_participant.source
  // without a new column on either side.
  assert.equal(p.managerChain[1].mail, 'zephyr.uppingham@contoso.com');
});

test('mapParticipants returns null for a chart it cannot use, never []', () => {
  // [] is a different statement: `align` reads it as "the source looked and
  // found nobody" and does not fall back to transcript labels, so emitting it
  // for a broken chart would silently strip a meeting of its participants.
  for (const chart of [null, 'not an object', 42, [], {}, { people: 'nope' }, { people: {} }]) {
    const { participants, warnings } = emit.mapParticipants(chart);
    assert.equal(participants, null, `${JSON.stringify(chart)} should be unusable`);
    assert.ok(warnings.length, 'an unusable chart must say why');
  }
  const empty = emit.mapParticipants(chartOf([]));
  assert.equal(empty.participants, null);
  assert.match(empty.warnings.join('\n'), /no usable person rows/);
});

test('mapParticipants drops a nameless row and keeps the rest', () => {
  const { participants, warnings } = emit.mapParticipants(
    chartOf([
      chartRow(),
      chartRow({ name: '   ' }),
      { mail: 'nobody@contoso.com' },
      'not a row',
      chartRow({ name: 'Tremaine, Kendall', mail: 'kendall.tremaine@contoso.com' }),
    ])
  );
  assert.deepEqual(
    participants.map((p) => p.displayName),
    ['Maplewood, Micah (CNTR)', 'Tremaine, Kendall']
  );
  assert.equal(warnings.length, 3, 'each dropped row is named');
  assert.match(warnings.join('\n'), /people\[1\] has no usable "name"/);
  assert.match(warnings.join('\n'), /people\[2\] has no usable "name"/);
  assert.match(warnings.join('\n'), /people\[3\] is not an object/);
});

test('an occurrence with a chart emits participants in its metadata', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, {
    exts: ['.txt'],
    chart: chartOf([
      chartRow(),
      chartRow({ name: 'Tremaine, Kendall', mail: 'kendall.tremaine@contoso.com', title: 'Senior Procurement Program Manager' }),
      // An external attendee: unresolved with org "Unknown". The pipeline
      // stores it as external without consulting `guest`.
      chartRow({ name: 'Outside, Vendor', mail: '', org: 'Unknown', unresolved: true, managerChain: [] }),
    ]),
  });
  const { out } = await captureStderr(() => emit.emitDrop(dir, { dropsRoot: drops }));
  assert.equal(out, '', 'a usable chart warns about nothing');

  const md = readMetadata(path.join(drops, fs.readdirSync(drops)[0]));
  assert.equal(md.participants.length, 3);
  assert.deepEqual(
    md.participants.map((p) => p.displayName),
    ['Maplewood, Micah (CNTR)', 'Tremaine, Kendall', 'Outside, Vendor']
  );
  assert.equal(md.participants[1].mail, 'kendall.tremaine@contoso.com');
  assert.equal(md.participants[1].title, 'Senior Procurement Program Manager');
  assert.equal(md.participants[1].department, '01.102.000281.110');
  assert.equal(md.participants[0].managerChain.length, 2);
  assert.equal(md.participants[2].unresolved, true);
  // Still a version 1 drop: the participant graph is not an augmentation.
  assert.equal(md.schemaVersion, 1);
  assert.ok(!('augments' in md));
});

test('a drop carrying participants validates against docs/source-drop.schema.json', SCHEMA_TEST, () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, {
    exts: ['.txt'],
    chart: chartOf([chartRow(), chartRow({ name: 'Tremaine, Kendall' })]),
  });
  const res = emit.emitDrop(dir, { dropsRoot: drops });
  assertValid(readMetadata(res.path));
});

test('an unusable chart omits the key, warns, and never skips the occurrence', async () => {
  for (const chart of ['{ not json', JSON.stringify({ people: 'nope' }), JSON.stringify({ people: [] })]) {
    const src = tmpRoot('src');
    const drops = tmpRoot('drops');
    const dir = makeOccurrence(src, { exts: ['.txt'], chart });
    const { result, out } = await captureStderr(() => emit.emitDrop(dir, { dropsRoot: drops }));
    assert.equal(result.status, 'created', 'the transcript is the evidence; the chart is auxiliary');
    assert.ok(!('participants' in readMetadata(result.path)), 'a broken chart must not emit []');
    assert.match(out, /warning: /, 'an unusable chart must be named on stderr');
    assert.match(out, /org chart\.json/);
  }
});

test('a chart path that cannot be read degrades to a graph-less drop', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  fs.mkdirSync(path.join(dir, `6.10.26 Fabrikam Data Hub Demo${emit.ORG_CHART_SUFFIX}`));
  const { result, out } = await captureStderr(() => emit.emitDrop(dir, { dropsRoot: drops }));
  assert.equal(result.status, 'created');
  assert.ok(!('participants' in readMetadata(result.path)));
  assert.match(out, /participant graph could not be read/);
});

test('a nameless row is dropped with a warning and the rest of the drop stands', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, {
    exts: ['.txt'],
    chart: chartOf([chartRow({ name: '' }), chartRow({ name: 'Tremaine, Kendall' })]),
  });
  const { result, out } = await captureStderr(() => emit.emitDrop(dir, { dropsRoot: drops }));
  assert.equal(result.status, 'created');
  assert.deepEqual(
    readMetadata(result.path).participants.map((p) => p.displayName),
    ['Tremaine, Kendall']
  );
  assert.match(out, /people\[0\] has no usable "name"/);
});

test('a chart named for another occurrence is not this occurrence\'s graph', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  // Only the occurrence stem maps, exactly as for the transcripts.
  fs.writeFileSync(
    path.join(dir, '11_59 AM - Fabrikam Data Hub Demo org chart.json'),
    JSON.stringify(chartOf([chartRow()]))
  );
  const { result, out } = await captureStderr(() => emit.emitDrop(dir, { dropsRoot: drops }));
  assert.ok(!('participants' in readMetadata(result.path)));
  assert.equal(out, '', 'an occurrence with no chart of its own is silent');
});

test('--dry-run reports the participant count without writing', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, {
    exts: ['.txt'],
    chart: chartOf([chartRow(), chartRow({ name: 'Tremaine, Kendall' }), chartRow({ name: 'Third, Person' })]),
  });
  const { result, out } = await captureStderr(() => emit.main([dir, '--dry-run', '--drops', drops]));
  assert.equal(result, 0);
  assert.match(out, /people {4}3/);
  assert.equal(fs.readdirSync(drops).length, 0);
});

// ---------------------------------------------------------------------------
// --re-emit: a new sibling drop, never a rewrite of a finalized one
// ---------------------------------------------------------------------------

test('splitDropName treats the unsuffixed name as sequence 1', () => {
  assert.deepEqual(emit.splitDropName('2026-06-10-alpha-sync-abcd1234'), {
    prefix: '2026-06-10-alpha-sync-abcd1234', sequence: 1,
  });
  assert.deepEqual(emit.splitDropName('2026-06-10-alpha-sync-abcd1234-002'), {
    prefix: '2026-06-10-alpha-sync-abcd1234', sequence: 2,
  });
  assert.deepEqual(emit.splitDropName('2026-06-10-alpha-sync-abcd1234-014'), {
    prefix: '2026-06-10-alpha-sync-abcd1234', sequence: 14,
  });
  // "-001" is not a discriminator this tool writes: sequence 1 IS the base
  // name, so a directory literally called "...-001" is its own prefix.
  assert.equal(emit.splitDropName('2026-06-10-alpha-sync-abcd1234-001').sequence, 1);
});

test('nextDropName starts at the base name and then at -002', () => {
  const drops = tmpRoot('drops');
  const base = '2026-06-10-alpha-sync-abcd1234';
  assert.equal(emit.nextDropName(drops, base), base);
  fs.mkdirSync(path.join(drops, base));
  assert.equal(emit.nextDropName(drops, base), `${base}-002`);
  fs.mkdirSync(path.join(drops, `${base}-002`));
  assert.equal(emit.nextDropName(drops, base), `${base}-003`);
  // A different occurrence's drops never move this one's sequence.
  fs.mkdirSync(path.join(drops, '2026-06-10-other-meeting-99999999-002'));
  assert.equal(emit.nextDropName(drops, base), `${base}-003`);
});

test('a re-emit with no first drop emits the plain version 1 drop', () => {
  // You cannot augment an occurrence that was never ingested.
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'], chart: chartOf([chartRow()]) });
  const res = emit.emitDrop(dir, { dropsRoot: drops, reEmit: true });
  assert.equal(res.status, 'created');
  assert.equal(path.basename(res.path), res.plan.name);
  assert.ok(!/-\d{3}$/.test(path.basename(res.path)), 'the base name carries no sequence');
  const md = readMetadata(res.path);
  assert.equal(md.schemaVersion, 1);
  assert.ok(!('augments' in md));
  assert.equal(md.participants.length, 1);
});

test('--re-emit emits a new sibling drop and never touches the finalized one', SCHEMA_TEST, () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  // The corpus as it stands: a drop emitted before the chart existed.
  const dir = makeOccurrence(src, { exts: ['.txt', '.vtt'] });
  const first = emit.emitDrop(dir, { dropsRoot: drops });
  assert.equal(first.status, 'created');
  const base = path.basename(first.path);
  const before = fs.readdirSync(first.path).sort().map((f) => {
    const st = fs.statSync(path.join(first.path, f));
    return [f, st.mtimeMs, fs.readFileSync(path.join(first.path, f), 'utf8')];
  });

  // The chart is written later, and the occurrence is brought up to contract.
  fs.writeFileSync(
    path.join(dir, `6.10.26 Fabrikam Data Hub Demo${emit.ORG_CHART_SUFFIX}`),
    JSON.stringify(chartOf([chartRow(), chartRow({ name: 'Tremaine, Kendall' })]))
  );
  const second = emit.emitDrop(dir, { dropsRoot: drops, reEmit: true });

  assert.equal(second.status, 'created');
  assert.equal(path.basename(second.path), `${base}-002`);
  const md = readMetadata(second.path);
  assert.equal(md.schemaVersion, 2, 'an augmenting drop must declare version 2');
  assert.deepEqual(md.augments, { sourceId: md.sourceId });
  assert.equal(md.participants.length, 2);
  assertValid(md);
  // Every evidence file comes along: intake refuses an augmenting drop that
  // sheds a transcript the target's drop carries.
  assert.deepEqual(dropFiles(second.path), ['metadata.json', 'transcript.txt', 'transcript.vtt']);

  // AC: the finalized drop keeps its name, its bytes and its mtimes.
  assert.ok(fs.existsSync(path.join(drops, base)));
  const after = fs.readdirSync(first.path).sort().map((f) => {
    const st = fs.statSync(path.join(first.path, f));
    return [f, st.mtimeMs, fs.readFileSync(path.join(first.path, f), 'utf8')];
  });
  assert.deepEqual(after, before);

  // Emit order is recoverable from the drops folder alone: lexical sort within
  // the occurrence's prefix.
  assert.deepEqual(
    fs.readdirSync(drops).filter((n) => n.startsWith(base)).sort(),
    [base, `${base}-002`]
  );
});

test('a second re-emit with nothing new is `current` and writes nothing', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'], chart: chartOf([chartRow()]) });
  const first = emit.emitDrop(dir, { dropsRoot: drops });
  assert.equal(first.status, 'created');

  // Same participants, same evidence files: the newest drop already says it.
  const again = emit.emitDrop(dir, { dropsRoot: drops, reEmit: true });
  assert.equal(again.status, 'current');
  assert.equal(again.path, first.path);
  assert.deepEqual(fs.readdirSync(drops).sort(), [path.basename(first.path)]);
  assert.equal(fs.existsSync(path.join(drops, '.staging')), false);
});

test('a re-emit pass is idempotent after the sequence it wrote', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  const base = path.basename(emit.emitDrop(dir, { dropsRoot: drops }).path);
  fs.writeFileSync(
    path.join(dir, `6.10.26 Fabrikam Data Hub Demo${emit.ORG_CHART_SUFFIX}`),
    JSON.stringify(chartOf([chartRow()]))
  );
  assert.equal(emit.emitDrop(dir, { dropsRoot: drops, reEmit: true }).status, 'created');
  // The second pass compares against -002, not against the base drop.
  assert.equal(emit.emitDrop(dir, { dropsRoot: drops, reEmit: true }).status, 'current');
  assert.deepEqual(fs.readdirSync(drops).sort(), [base, `${base}-002`]);
});

test('a re-resolved chart does not re-emit: the door would refuse that drop', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'], chart: chartOf([chartRow()]) });
  const first = emit.emitDrop(dir, { dropsRoot: drops });
  assert.equal(first.status, 'created');

  // The chart was re-resolved upstream and now says something different. That
  // is a difference, but it is not evidence the occurrence LACKS: intake's
  // augmentation door refuses a drop whose target already carries a graph. A
  // puller that emitted here would finalize a write-once drop the api then
  // refuses, and the next pass would compare against that never-ingested drop
  // and report the occurrence migrated. So this is `current`, not `created`.
  fs.writeFileSync(
    path.join(dir, `6.10.26 Fabrikam Data Hub Demo${emit.ORG_CHART_SUFFIX}`),
    JSON.stringify(chartOf([chartRow({ name: 'Maplewood, Micah', title: 'Principal' })]))
  );
  const again = emit.emitDrop(dir, { dropsRoot: drops, reEmit: true });
  assert.equal(again.status, 'current');
  assert.deepEqual(fs.readdirSync(drops).sort(), [path.basename(first.path)]);
});

test('an empty participants array is not a graph, on either side', () => {
  // `align` reads [] as "the source looked and found nobody", so it adds no
  // participants — mapParticipants never emits it, and a drop that somehow
  // carries one must not count as migrated.
  const { participants, warnings } = emit.mapParticipants(chartOf([]));
  assert.equal(participants, null, '[] must never be emitted');
  assert.ok(warnings.some((w) => /no usable person rows/.test(w)));

  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  const base = path.basename(emit.emitDrop(dir, { dropsRoot: drops }).path);
  // Hand-edit the finalized drop's metadata to carry [] — the shape a broken
  // source could produce — then give the occurrence a real chart.
  const metaPath = path.join(drops, base, 'metadata.json');
  const meta = JSON.parse(fs.readFileSync(metaPath, 'utf8'));
  fs.writeFileSync(metaPath, JSON.stringify({ ...meta, participants: [] }, null, 2));
  fs.writeFileSync(
    path.join(dir, `6.10.26 Fabrikam Data Hub Demo${emit.ORG_CHART_SUFFIX}`),
    JSON.stringify(chartOf([chartRow()]))
  );
  assert.equal(emit.emitDrop(dir, { dropsRoot: drops, reEmit: true }).status, 'created');
  assert.deepEqual(emit.unmigratedPrefixes(drops).stale, []);
});

test('a changed evidence set re-emits even when the participants match', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'], chart: chartOf([chartRow()]) });
  const base = path.basename(emit.emitDrop(dir, { dropsRoot: drops }).path);
  // A re-pull recovered the video.
  fs.writeFileSync(path.join(dir, '6.10.26 Fabrikam Data Hub Demo.mp4'), 'video bytes\n');
  const res = emit.emitDrop(dir, { dropsRoot: drops, reEmit: true });
  assert.equal(res.status, 'created');
  assert.equal(path.basename(res.path), `${base}-002`);
  assert.deepEqual(dropFiles(res.path), ['metadata.json', 'recording.mp4', 'transcript.txt']);
  assert.deepEqual(readMetadata(res.path).augments, { sourceId: res.plan.sourceId });
});

test('a VTT-only change is current because intake cannot augment transcript forms', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'], chart: chartOf([chartRow()]) });
  const first = emit.emitDrop(dir, { dropsRoot: drops });
  fs.writeFileSync(path.join(dir, '6.10.26 Fabrikam Data Hub Demo.vtt'), 'WEBVTT\n');
  const again = emit.emitDrop(dir, { dropsRoot: drops, reEmit: true });
  assert.equal(again.status, 'current');
  assert.deepEqual(fs.readdirSync(drops).sort(), [path.basename(first.path)]);
});

test('a graph re-emit refuses to shed a target transcript before writing', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt', '.vtt'] });
  const first = emit.emitDrop(dir, { dropsRoot: drops });
  fs.rmSync(path.join(dir, '6.10.26 Fabrikam Data Hub Demo.vtt'));
  fs.writeFileSync(path.join(dir, `6.10.26 Fabrikam Data Hub Demo${emit.ORG_CHART_SUFFIX}`), JSON.stringify(chartOf([chartRow()])));
  assert.throws(() => emit.emitDrop(dir, { dropsRoot: drops, reEmit: true }), /may not shed/);
  assert.deepEqual(fs.readdirSync(drops).sort(), [path.basename(first.path)]);
});

test('without --re-emit an existing drop is still reported `exists`', () => {
  // The default behaviour is unchanged: no flag, no second drop, ever.
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  const first = emit.emitDrop(dir, { dropsRoot: drops });
  fs.writeFileSync(
    path.join(dir, `6.10.26 Fabrikam Data Hub Demo${emit.ORG_CHART_SUFFIX}`),
    JSON.stringify(chartOf([chartRow()]))
  );
  const second = emit.emitDrop(dir, { dropsRoot: drops });
  assert.equal(second.status, 'exists');
  assert.equal(second.path, first.path);
  assert.deepEqual(fs.readdirSync(drops).sort(), [path.basename(first.path)]);
});

test('an exhausted sequence is a named error and writes nothing', () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  const base = emit.planDrop(dir).name;
  fs.mkdirSync(path.join(drops, base), { recursive: true });
  fs.writeFileSync(path.join(drops, base, 'metadata.json'), '{}\n');
  fs.mkdirSync(path.join(drops, `${base}-999`), { recursive: true });
  fs.writeFileSync(path.join(drops, `${base}-999`, 'metadata.json'), '{}\n');
  fs.writeFileSync(
    path.join(dir, `6.10.26 Fabrikam Data Hub Demo${emit.ORG_CHART_SUFFIX}`),
    JSON.stringify(chartOf([chartRow()]))
  );

  assert.throws(
    () => emit.emitDrop(dir, { dropsRoot: drops, reEmit: true }),
    /drop sequence exhausted for /
  );
  assert.deepEqual(fs.readdirSync(drops).sort(), [base, `${base}-999`]);
});

test('--re-emit --dry-run names the sequenced target and writes nothing', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'] });
  const base = path.basename(emit.emitDrop(dir, { dropsRoot: drops }).path);
  fs.writeFileSync(
    path.join(dir, `6.10.26 Fabrikam Data Hub Demo${emit.ORG_CHART_SUFFIX}`),
    JSON.stringify(chartOf([chartRow()]))
  );
  const { result, out } = await captureStderr(() =>
    emit.main([dir, '--re-emit', '--dry-run', '--drops', drops])
  );
  assert.equal(result, 0);
  assert.match(out, new RegExp(`plan {5}${base}-002`));
  assert.match(out, /augments .* \(schemaVersion 2\)/);
  assert.deepEqual(fs.readdirSync(drops).sort(), [base]);
});

// ---------------------------------------------------------------------------
// How much of the migration is left
// ---------------------------------------------------------------------------
//
// --re-emit is opt-in per occurrence, so a person is mail-keyed in a re-emitted
// meeting and name-keyed in one left alone, and nothing links the two
// participant rows. The pass therefore has to report what it has not reached,
// or a half-migrated corpus looks exactly like a finished one.

test('unmigratedPrefixes counts prefixes whose NEWEST drop carries no participants', () => {
  const drops = tmpRoot('drops');
  const write = (name, metadata) => {
    fs.mkdirSync(path.join(drops, name), { recursive: true });
    fs.writeFileSync(path.join(drops, name, 'metadata.json'), JSON.stringify(metadata));
  };
  write('2026-06-10-alpha-aaaaaaaa', { schemaVersion: 1 });
  write('2026-06-10-alpha-aaaaaaaa-002', { schemaVersion: 2, participants: [{ displayName: 'A' }] });
  write('2026-07-02-beta-bbbbbbbb', { schemaVersion: 1 });
  write('2026-08-04-gamma-cccccccc', { schemaVersion: 1, participants: [] });
  // Unreadable: "cannot tell" must not report as "already migrated".
  fs.mkdirSync(path.join(drops, '2026-08-05-delta-dddddddd'), { recursive: true });
  fs.mkdirSync(path.join(drops, '.staging'), { recursive: true });

  const { total, stale } = emit.unmigratedPrefixes(drops);
  assert.equal(total, 4, 'the staging dir is not an occurrence and -002 is not a fifth prefix');
  assert.deepEqual(stale, ['2026-07-02-beta-bbbbbbbb', '2026-08-04-gamma-cccccccc', '2026-08-05-delta-dddddddd']);
});

test('a --re-emit pass reports how many prefixes are still on the old contract', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const migrated = makeOccurrence(src, { exts: ['.txt'] });
  const left = makeOccurrence(src, { title: 'Left Alone', date: '8.4.26', exts: ['.txt'] });
  emit.emitDrop(migrated, { dropsRoot: drops });
  emit.emitDrop(left, { dropsRoot: drops });
  fs.writeFileSync(
    path.join(migrated, `6.10.26 Fabrikam Data Hub Demo${emit.ORG_CHART_SUFFIX}`),
    JSON.stringify(chartOf([chartRow()]))
  );

  const { result, out } = await captureStderr(() =>
    emit.main([migrated, '--re-emit', '--no-post', '--drops', drops])
  );
  assert.equal(result, 0);
  assert.match(out, /created 1, exists 0, current 0, skipped 0, failed 0/);
  assert.match(out, /participants: 1 of 2 drop prefixes still carry no participants key/);

  // And once the other one is brought over, the pass says the migration is done.
  fs.writeFileSync(
    path.join(left, `8.4.26 Left Alone${emit.ORG_CHART_SUFFIX}`),
    JSON.stringify(chartOf([chartRow()]))
  );
  const done = await captureStderr(() =>
    emit.main([migrated, left, '--re-emit', '--no-post', '--drops', drops])
  );
  assert.match(done.out, /created 1, exists 0, current 1, skipped 0, failed 0/);
  assert.match(done.out, /participants: 0 of 2 drop prefixes still carry no participants key/);
});

test('a `current` occurrence is not re-POSTed to the api', async () => {
  const src = tmpRoot('src');
  const drops = tmpRoot('drops');
  const dir = makeOccurrence(src, { exts: ['.txt'], chart: chartOf([chartRow()]) });
  emit.emitDrop(dir, { dropsRoot: drops });
  // An api url that refuses instantly, to prove it is never called.
  const { result, out } = await captureStderr(() =>
    emit.main([dir, '--re-emit', '--drops', drops, '--api', 'http://127.0.0.1:1'])
  );
  assert.equal(result, 0);
  assert.match(out, /created 0, exists 0, current 1/);
  assert.ok(!/intake FAILED/.test(out), 'a drop that was not written must not be POSTed');
});
