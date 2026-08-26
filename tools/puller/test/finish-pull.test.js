'use strict';

// The post-download tail's ORDER is a contract, and it is the kind of contract
// that reverts silently: every other suite stays green whether the summariser
// runs before the emit or after it. So `finishPull` is exercised here with
// stubs for its four collaborators, and what is asserted is the sequence.
//
// Why the sequence matters, in the order the steps run:
//   1. `_source.json` first — `--all` keys on that sidecar, so a crash during
//      the multi-minute summariser pass must not leave a transcript that
//      neither the backfill nor a manual emit can ever see again.
//   2. summaries next — the drop CARRIES them (story 4.1a), so emitting first
//      would mean no drop could ever carry them.
//   3. emit last, unconditional — "the hand-off never fails a pull".

const test = require('node:test');
const assert = require('node:assert/strict');

// Requiring the tool must not launch a browser; it guards on require.main.
const { finishPull, summarizeTranscript } = require('../grab-teams-transcript.js');

function harness(overrides = {}) {
  const order = [];
  const stubs = {
    writeSidecar: (dir, record) => { order.push(['sidecar', record.title]); },
    log: (record) => { order.push(['log', record.event]); },
    generate: async (txtPath) => { order.push(['generate', txtPath]); },
    emit: (dir) => {
      order.push(['emit', dir]);
      return { status: 'created', path: '/drops/2026-06-10-demo-abcd1234' };
    },
    post: async (dropPath) => {
      order.push(['post', dropPath]);
      return { status: 'created', jobId: 'job-1', httpStatus: 201 };
    },
  };
  const opts = {
    dir: '/archive/Demo/6.10.26',
    target: '/archive/Demo/6.10.26/6.10.26 Demo.txt',
    outFile: '',
    url: 'https://example.invalid/stream.aspx?id=%2Frec.mp4',
    recordingName: 'rec.mp4',
    title: 'Demo',
    date: '6.10.26',
    dateSource: 'test',
    wantSummary: true,
    wantEmit: true,
    dropsRoot: '/drops',
    apiUrl: 'http://127.0.0.1:8000',
    corpus: 'real',
    ...stubs,
    ...overrides,
  };
  return { order, opts };
}

test('the sidecar is written before the summariser, and the emit runs last', async () => {
  const { order, opts } = harness();
  await finishPull(opts);
  assert.deepEqual(order.map((step) => step[0]), [
    'sidecar', 'log', 'generate', 'emit', 'post',
  ]);
});

test('a crash during generation still leaves the occurrence discoverable', async () => {
  // The whole reason the sidecar goes first: --all keys on _source.json.
  const { order, opts } = harness({
    generate: async () => {
      order.push(['generate', 'boom']);
      throw new Error('the pull was interrupted mid-generation');
    },
  });
  await finishPull(opts);
  assert.deepEqual(order[0][0], 'sidecar', 'the sidecar exists before anything slow ran');
});

test('a failed summariser is non-fatal and the emit still runs', async () => {
  const { order, opts } = harness({
    generate: async () => { throw new Error('Ollama at http://x timed out: no output for 120000ms'); },
  });
  await finishPull(opts);
  assert.deepEqual(order.map((step) => step[0]), ['sidecar', 'log', 'emit', 'post']);
});

test('a failed emit never fails the pull', async () => {
  const { order, opts } = harness({
    emit: () => {
      order.push(['emit', 'boom']);
      throw new Error('drops root is not writable');
    },
  });
  await finishPull(opts);
  assert.deepEqual(order.map((step) => step[0]), ['sidecar', 'log', 'generate', 'emit']);
});

test('a failed intake never fails the pull, and the drop is already finalized', async () => {
  const { order, opts } = harness({
    post: async () => {
      order.push(['post', 'boom']);
      throw new Error('api unreachable');
    },
  });
  await finishPull(opts);
  assert.deepEqual(order.map((step) => step[0]), [
    'sidecar', 'log', 'generate', 'emit', 'post',
  ]);
});

test('--no-summary skips generation but still emits', async () => {
  const { order, opts } = harness({ wantSummary: false });
  await finishPull(opts);
  assert.deepEqual(order.map((step) => step[0]), ['sidecar', 'log', 'emit', 'post']);
});

test('--no-summary never carries same-stem documents left by an earlier pull', async () => {
  const fs = require('fs');
  const os = require('os');
  const path = require('path');
  const emitModule = require('../emit-drop.js');
  const src = fs.mkdtempSync(path.join(os.tmpdir(), 'finish-pull-stale-src-'));
  const drops = fs.mkdtempSync(path.join(os.tmpdir(), 'finish-pull-stale-drops-'));
  try {
    const dir = path.join(src, 'Demo', '6.10.26');
    fs.mkdirSync(dir, { recursive: true });
    const stem = '6.10.26 Demo';
    const target = path.join(dir, stem + '.txt');
    fs.writeFileSync(target, '[0:02] Goeke, Timothy: Changed transcript.\n');
    fs.writeFileSync(path.join(dir, stem + '.md'), 'stale summary\n');
    fs.writeFileSync(path.join(dir, stem + ' action items.md'), 'stale actions\n');
    fs.writeFileSync(path.join(dir, '_source.json'), JSON.stringify({
      url: 'https://example-my.sharepoint.com/personal/u/_layouts/15/stream.aspx?id=%2Frec%2Emp4',
      recordingName: 'rec.mp4', title: 'Demo', date: '6.10.26', dateSource: 'test',
    }));

    let emitted;
    await finishPull({
      dir, target, outFile: '', url: 'https://example.invalid/x',
      recordingName: 'rec.mp4', title: 'Demo', date: '6.10.26', dateSource: 'test',
      wantSummary: false, wantEmit: true, dropsRoot: drops,
      apiUrl: 'http://127.0.0.1:8000', corpus: 'real',
      emit: (occurrenceDir, opts) => (emitted = emitModule.emitDrop(occurrenceDir, opts)),
      post: async () => ({ status: 'created', jobId: 'job-1', httpStatus: 201 }),
      writeSidecar: () => {}, log: () => {},
    });

    assert.deepEqual(fs.readdirSync(emitted.path).sort(), ['metadata.json', 'transcript.txt']);
    const metadata = JSON.parse(fs.readFileSync(path.join(emitted.path, 'metadata.json'), 'utf8'));
    assert.ok(!('extractions' in metadata));
  } finally {
    fs.rmSync(src, { recursive: true, force: true });
    fs.rmSync(drops, { recursive: true, force: true });
  }
});

test('a partial generation carries only the document freshly written in this run', async () => {
  const fs = require('fs');
  const os = require('os');
  const path = require('path');
  const emitModule = require('../emit-drop.js');
  const src = fs.mkdtempSync(path.join(os.tmpdir(), 'finish-pull-partial-src-'));
  const drops = fs.mkdtempSync(path.join(os.tmpdir(), 'finish-pull-partial-drops-'));
  try {
    const dir = path.join(src, 'Demo', '6.10.26');
    fs.mkdirSync(dir, { recursive: true });
    const stem = '6.10.26 Demo';
    const target = path.join(dir, stem + '.txt');
    fs.writeFileSync(target, '[0:02] Goeke, Timothy: Changed transcript.\n');
    fs.writeFileSync(path.join(dir, stem + '.md'), 'stale summary\n');
    fs.writeFileSync(path.join(dir, stem + ' action items.md'), 'stale actions\n');
    fs.writeFileSync(path.join(dir, '_source.json'), JSON.stringify({
      url: 'https://example-my.sharepoint.com/personal/u/_layouts/15/stream.aspx?id=%2Frec%2Emp4',
      recordingName: 'rec.mp4', title: 'Demo', date: '6.10.26', dateSource: 'test',
    }));

    let emitted;
    await finishPull({
      dir, target, outFile: '', url: 'https://example.invalid/x',
      recordingName: 'rec.mp4', title: 'Demo', date: '6.10.26', dateSource: 'test',
      wantSummary: true, wantEmit: true, dropsRoot: drops,
      apiUrl: 'http://127.0.0.1:8000', corpus: 'real',
      generate: async () => {
        fs.writeFileSync(path.join(dir, stem + '.md'), 'fresh summary\n');
        return {
          documents: ['extraction-summary.md'],
          errors: [new Error('action generation failed')],
        };
      },
      emit: (occurrenceDir, opts) => (emitted = emitModule.emitDrop(occurrenceDir, opts)),
      post: async () => ({ status: 'created', jobId: 'job-1', httpStatus: 201 }),
      writeSidecar: () => {}, log: () => {},
    });

    assert.deepEqual(fs.readdirSync(emitted.path).sort(), [
      'extraction-summary.md', 'metadata.json', 'transcript.txt',
    ]);
    assert.equal(fs.readFileSync(path.join(emitted.path, 'extraction-summary.md'), 'utf8'), 'fresh summary\n');
    const metadata = JSON.parse(fs.readFileSync(path.join(emitted.path, 'metadata.json'), 'utf8'));
    assert.deepEqual(metadata.extractions, { archSummary: 'extraction-summary.md' });
  } finally {
    fs.rmSync(src, { recursive: true, force: true });
    fs.rmSync(drops, { recursive: true, force: true });
  }
});

test('--no-emit stops after the summaries', async () => {
  const { order, opts } = harness({ wantEmit: false });
  await finishPull(opts);
  assert.deepEqual(order.map((step) => step[0]), ['sidecar', 'log', 'generate']);
});

test('an explicit output file writes no sidecar and hands nothing off', async () => {
  // `--out somewhere.txt` is a one-off dump, not an occurrence in the archive.
  const { order, opts } = harness({ outFile: '/tmp/one-off.txt' });
  await finishPull(opts);
  assert.deepEqual(order.map((step) => step[0]), ['generate']);
});

// The emit runs against a real occurrence directory here, so the ordering
// claim is checked against what emit-drop actually reads: the drop it produces
// must carry both generated documents, which is only true if generation
// already ran.
test('the emitted drop carries the documents generation just wrote', async () => {
  const fs = require('fs');
  const os = require('os');
  const path = require('path');
  const emitModule = require('../emit-drop.js');

  const src = fs.mkdtempSync(path.join(os.tmpdir(), 'finish-pull-src-'));
  const drops = fs.mkdtempSync(path.join(os.tmpdir(), 'finish-pull-drops-'));
  try {
    const dir = path.join(src, 'Demo', '6.10.26');
    fs.mkdirSync(dir, { recursive: true });
    const stem = '6.10.26 Demo';
    const target = path.join(dir, stem + '.txt');
    fs.writeFileSync(target, '[0:02] Goeke, Timothy: Morning.\n');
    fs.writeFileSync(
      path.join(dir, '_source.json'),
      JSON.stringify({
        url: 'https://example-my.sharepoint.com/personal/u/_layouts/15/stream.aspx?id=%2Frec%2Emp4',
        recordingName: 'rec.mp4', title: 'Demo', date: '6.10.26',
        dateSource: 'test', pulledAt: '2026-06-10T18:15:41.000Z',
      })
    );

    let emitted = null;
    await finishPull({
      dir, target, outFile: '', url: 'https://example.invalid/x',
      recordingName: 'rec.mp4', title: 'Demo', date: '6.10.26', dateSource: 'test',
      wantSummary: true, wantEmit: true, dropsRoot: drops,
      apiUrl: 'http://127.0.0.1:8000', corpus: 'real',
      // The real generateDocs would call a model; this writes exactly the two
      // files it writes, which is the only part the emit reads.
      generate: async (txtPath) => {
        const base = txtPath.replace(/\.[^.]+$/, '');
        fs.writeFileSync(base + '.md', '## Decisions\n\n| D1 | Use SFTP | [0:02] |\n');
        fs.writeFileSync(base + ' action items.md', '## Goeke, Timothy\n\n| A1 | Ship it | [0:02] |\n');
        return { documents: ['extraction-summary.md', 'extraction-action-items.md'], errors: [] };
      },
      emit: (occurrenceDir, opts) => {
        emitted = emitModule.emitDrop(occurrenceDir, opts);
        return emitted;
      },
      post: async () => ({ status: 'created', jobId: 'job-1', httpStatus: 201 }),
      writeSidecar: () => {},
      log: () => {},
    });

    assert.ok(emitted, 'the emit ran');
    assert.deepEqual(fs.readdirSync(emitted.path).sort(), [
      'extraction-action-items.md', 'extraction-summary.md', 'metadata.json', 'transcript.txt',
    ]);
    const metadata = JSON.parse(fs.readFileSync(path.join(emitted.path, 'metadata.json'), 'utf8'));
    assert.equal(metadata.schemaVersion, 3);
    assert.deepEqual(metadata.extractions, {
      archSummary: 'extraction-summary.md',
      actionItems: 'extraction-action-items.md',
    });
  } finally {
    fs.rmSync(src, { recursive: true, force: true });
    fs.rmSync(drops, { recursive: true, force: true });
  }
});

test('an unterminated final Ollama NDJSON record is written', async () => {
  const fs = require('fs');
  const os = require('os');
  const path = require('path');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'finish-pull-ndjson-'));
  const input = path.join(dir, '6.10.26 Demo.txt');
  const output = path.join(dir, '6.10.26 Demo.md');
  const prompt = path.join(dir, 'prompt.md');
  const originalFetch = global.fetch;
  try {
    fs.writeFileSync(input, '[0:02] Goeke, Timothy: Morning.\n');
    fs.writeFileSync(prompt, 'Produce a summary.\n');
    global.fetch = async () => ({
      ok: true,
      body: {
        async *[Symbol.asyncIterator]() {
          yield Buffer.from(JSON.stringify({ message: { content: 'Final record content' } }));
        },
      },
    });

    await summarizeTranscript(input, output, prompt);
    assert.equal(fs.readFileSync(output, 'utf8'), 'Final record content\n');
  } finally {
    global.fetch = originalFetch;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
