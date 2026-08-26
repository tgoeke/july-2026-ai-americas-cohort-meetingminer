'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const { generateDocs, runStandaloneSummary } = require('../grab-teams-transcript.js');

test('generateDocs records a partial failure but still writes and selects the fresh document', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'generate-docs-partial-'));
  try {
    const transcript = path.join(dir, '6.10.26 Demo.txt');
    fs.writeFileSync(transcript, '[0:02] Goeke, Timothy: Morning.\n');
    const calls = [];

    const result = await generateDocs(transcript, {
      summarize: async (_txtPath, outputPath) => {
        calls.push(outputPath);
        if (outputPath.endsWith(' action items.md')) {
          throw new Error('action request failed');
        }
        fs.writeFileSync(outputPath, 'fresh architecture summary\n');
      },
      addCounts: () => assert.fail('action counts require a successful action document'),
    });

    assert.deepEqual(calls, [
      path.join(dir, '6.10.26 Demo.md'),
      path.join(dir, '6.10.26 Demo action items.md'),
    ]);
    assert.deepEqual(result.documents, ['extraction-summary.md']);
    assert.equal(result.errors.length, 1);
    assert.match(result.errors[0].message, /action request failed/);
    assert.equal(
      fs.readFileSync(path.join(dir, '6.10.26 Demo.md'), 'utf8'),
      'fresh architecture summary\n'
    );
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('standalone summarization reports returned generation failures and exits nonzero', async () => {
  const diagnostics = [];
  const exitCode = await runStandaloneSummary('meeting.txt', '', {
    generate: async () => ({
      documents: [],
      errors: [new Error('summary request failed'), new Error('action request failed')],
    }),
    error: (message) => diagnostics.push(message),
  });

  // Before this regression, the no-output `--summarize` branch discarded this
  // result and the CLI exited successfully despite both requests failing.
  assert.equal(exitCode, 1);
  assert.deepEqual(diagnostics, [
    'Summary/action-items generation failed: summary request failed',
    'Summary/action-items generation failed: action request failed',
  ]);
});

test('the --summarize CLI exits nonzero when both document requests fail', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'standalone-summarize-failure-'));
  const server = http.createServer((_request, response) => {
    response.statusCode = 503;
    response.end('summarizer unavailable');
  });
  try {
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    const transcript = path.join(dir, '6.10.26 Demo.txt');
    fs.writeFileSync(transcript, '[0:02] Goeke, Timothy: Morning.\n');
    const { code, stderr } = await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [
        path.join(__dirname, '..', 'grab-teams-transcript.js'), '--summarize', transcript,
      ], {
        env: {
          ...process.env,
          OLLAMA_URL: `http://127.0.0.1:${server.address().port}`,
        },
      });
      let stderr = '';
      child.stderr.on('data', (chunk) => { stderr += chunk; });
      child.on('error', reject);
      child.on('close', (code) => resolve({ code, stderr }));
    });

    // Before this fix, generateDocs returned these failures but the CLI
    // discarded them and exited 0.
    assert.equal(code, 1);
    assert.match(stderr, /Summary\/action-items generation failed: Ollama HTTP 503/);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
