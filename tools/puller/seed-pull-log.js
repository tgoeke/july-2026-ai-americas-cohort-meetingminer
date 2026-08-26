#!/usr/bin/env node
/*
 * seed-pull-log.js — one-off backfill for pulls.jsonl.
 *
 * The pull log was added after the fact, so the URLs behind the existing local
 * library only survive in the scraping browser's own history (the tool drives a
 * persistent Chrome profile, so every recording it opened is in there). This
 * reads those stream.aspx visits out of .transcript-profile/Default/History and
 * appends them to pulls.jsonl, so --replay can rebuild anything.
 *
 *   node seed-pull-log.js            # show what would be added
 *   node seed-pull-log.js --apply    # append to pulls.jsonl
 *
 * Chrome keeps the DB locked, so it is copied before reading. Needs sqlite3.
 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const { execFileSync } = require('child_process');

const HISTORY = path.join(__dirname, '.transcript-profile', 'Default', 'History');
const PULL_LOG = path.join(__dirname, 'pulls.jsonl');
const apply = process.argv.includes('--apply');

if (!fs.existsSync(HISTORY)) {
  console.error(`No browser history at ${HISTORY}; nothing to seed from.`);
  process.exit(1);
}
const tmp = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'hist-')), 'History');
fs.copyFileSync(HISTORY, tmp);

// Chrome timestamps are microseconds since 1601-01-01.
const rows = execFileSync('sqlite3', ['-separator', '\t', tmp,
  "select datetime(last_visit_time/1000000-11644473600,'unixepoch') || 'Z', url from urls " +
  "where url like '%stream.aspx%' order by last_visit_time asc;"], { encoding: 'utf8' })
  .split('\n').map(l => l.trim()).filter(Boolean)
  .map(l => { const [when, url] = l.split('\t'); return { when: when.replace(' ', 'T'), url }; });

// One visit per recording: the player is opened repeatedly (and Stream appends
// per-visit referrer/isDarkMode params), so key on the recording file itself and
// keep the earliest visit.
const byRecording = new Map();
for (const r of rows) {
  let name = '';
  try { name = path.basename(decodeURIComponent(new URL(r.url).searchParams.get('id') || '')); } catch {}
  if (!name) continue;
  if (!byRecording.has(name)) byRecording.set(name, { ...r, recordingName: name });
}

const already = new Set();
if (fs.existsSync(PULL_LOG))
  for (const line of fs.readFileSync(PULL_LOG, 'utf8').split('\n')) {
    try { const j = JSON.parse(line); if (j.recordingName) already.add(j.recordingName); } catch {}
  }

const add = [...byRecording.values()].filter(r => !already.has(r.recordingName));
console.error(`${byRecording.size} distinct recordings in browser history; ` +
  `${add.length} not yet in pulls.jsonl.`);
for (const r of add) console.error(`  ${r.when.slice(0, 10)}  ${r.recordingName}`);

if (!apply) { console.error('\nDry run — re-run with --apply to append these to pulls.jsonl.'); process.exit(0); }
for (const r of add)
  fs.appendFileSync(PULL_LOG, JSON.stringify({
    when: r.when, url: r.url, recordingName: r.recordingName,
    event: 'seeded', source: 'browser-history',
  }) + '\n');
console.error(`\nAppended ${add.length} entries to ${PULL_LOG}.`);
