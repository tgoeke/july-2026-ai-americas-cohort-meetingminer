#!/usr/bin/env node
/*
 * migrate-layout.js — reorganize the existing library into the per-occurrence
 * layout, and fix dates that the old date logic got wrong.
 *
 *   FROM  "<Title>/<M.D.YY> <Title>.txt"          (all occurrences in one folder)
 *   TO    "<Title>/<M.D.YY>/<M.D.YY> <Title>.txt" (one folder per occurrence)
 *
 * Also cleans up three things the old layout accumulated:
 *   - folder names carrying a raw Teams stamp
 *     ("… Weekly Connect-20260721_113417/") or a leading date
 *     ("6.30.26 R2C Functional Demo …/") — both become "<Title>/<M.D.YY>/";
 *   - undated pulls from before date prefixing existed ("Touchbase/Touchbase.txt"),
 *     dated from the pull log's recording name or the mp4's mvhd time;
 *   - a group whose date disagrees with the recording it came from (observed:
 *     "Northwind Contract Data Template Mapping Review- NA" filed as 7.16.26 — the
 *     day it was PULLED — when the recording is -20260714_140512-).
 *
 *   node migrate-layout.js            # print the plan, change nothing
 *   node migrate-layout.js --apply    # do it
 *
 * Nothing is ever overwritten: a move whose target already exists is skipped
 * and reported. Run seed-pull-log.js first so date corrections can be checked
 * against the real recording names.
 */
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const apply = process.argv.includes('--apply');
const fixDates = process.argv.includes('--fix-dates');

// ---- shared helpers, kept identical to grab-teams-transcript.js -------------
function dateToPrefix(d) {
  return `${d.getMonth() + 1}.${d.getDate()}.${String(d.getFullYear()).slice(2)}`;
}
function stampDate(name) {
  const m = (name || '').match(/-(20\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(UTC)?/);
  if (!m) return null;
  const [, Y, M, D, h, mi, s, utc] = m;
  if (utc) return { prefix: dateToPrefix(new Date(Date.UTC(+Y, +M - 1, +D, +h, +mi, +s))), utc: true };
  return { prefix: `${Number(M)}.${Number(D)}.${Y.slice(2)}`, utc: false };
}
function splitLeadingDate(s) {
  const m = (s || '').match(/^\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2}|\d{4})(?:\s*[-.]\s*|\s+)(\S.*)$/);
  if (!m) return { date: '', title: (s || '').trim() };
  const [, M, D, Y, rest] = m;
  const yy = Number(Y.slice(-2));
  if (+M < 1 || +M > 12 || +D < 1 || +D > 31 || yy < 20 || yy > 40)
    return { date: '', title: (s || '').trim() };
  return { date: `${Number(M)}.${Number(D)}.${Y.slice(-2)}`, title: rest.trim() };
}
function mp4Date(file) {
  let fd;
  try {
    const sz = fs.statSync(file).size;
    fd = fs.openSync(file, 'r');
    const scan = (off, len) => {
      const b = Buffer.alloc(len);
      fs.readSync(fd, b, 0, len, off);
      const i = b.indexOf('mvhd');
      if (i < 0 || i + 20 > b.length) return null;
      const secs = b[i + 4] === 1 ? Number(b.readBigUInt64BE(i + 8)) : b.readUInt32BE(i + 8);
      return new Date((secs - 2082844800) * 1000);
    };
    const win = Math.min(sz, 4 << 20);
    const d = scan(0, win) || scan(sz - win, win);
    return d && d.getFullYear() > 2010 && d.getTime() < Date.now() + 86400000 ? d : null;
  } catch { return null; }
  finally { if (fd !== undefined) try { fs.closeSync(fd); } catch {} }
}
// Title-only keys for matching a folder against a recording filename. SharePoint
// drops punctuation from upload names ("Contracts-Amendments …" arrives as
// "ContractsAmendments …"), which splits a word and defeats a word-wise
// comparison — so we also keep a key with every separator squashed out.
function titleKeys(n) {
  const bare = (n || '').toLowerCase()
    .replace(/\.(mp4|mov|webm)$/, '')
    .replace(/-?\s*\d{8}[_-]\d{6}(utc)?.*$/, '')
    .replace(/-?\s*meeting recording.*$/, '');
  const undated = splitLeadingDate(bare).title || bare;   // hand-named uploads
  return {
    words: undated.replace(/[^a-z0-9]+/g, ' ').trim(),
    squashed: undated.replace(/[^a-z0-9]+/g, ''),
  };
}

// ---- what the pull log knows about each recording ---------------------------
// Each logged recording gives us a title key and its true occurrence date (an
// explicit date in the name beats the Teams stamp — see the tool's date notes).
function logCandidates() {
  const p = path.join(ROOT, 'pulls.jsonl');
  const all = [];
  if (!fs.existsSync(p)) return all;
  for (const line of fs.readFileSync(p, 'utf8').split('\n')) {
    let j; try { j = JSON.parse(line); } catch { continue; }
    const name = j.recordingName;
    if (!name || all.some(c => c.name === name)) continue;
    const bare = name.replace(/\.(mp4|mov|webm)$/i, '').replace(/-?\s*Meeting Recording.*$/i, '');
    const explicit = splitLeadingDate(bare).date;
    const st = stampDate(name);
    const date = explicit || (st ? st.prefix : '');
    if (!date) continue;
    all.push({ name, date, url: j.url, keys: titleKeys(name) });
  }
  return all;
}

// ---- plan ------------------------------------------------------------------
const cands = logCandidates();
const moves = [];      // { from, to }
const notes = [];      // human-readable remarks
const stuck = [];      // things needing a manual call
const disagree = [];   // existing date vs. the recording it came from
const sources = [];    // { dir, rec } -> _source.json to write

const skipDir = d => d.startsWith('.') || d === 'node_modules' ||
  fs.existsSync(path.join(ROOT, d, '_index.json'));   // batch mirrors stay as-is

for (const dirName of fs.readdirSync(ROOT).sort()) {
  let st; try { st = fs.statSync(path.join(ROOT, dirName)); } catch { continue; }
  if (!st.isDirectory() || skipDir(dirName)) continue;

  const absDir = path.join(ROOT, dirName);
  const entries = fs.readdirSync(absDir, { withFileTypes: true });
  // Already migrated? (contains only M.D.YY subfolders)
  const subDates = entries.filter(e => e.isDirectory() && splitLeadingDate(e.name + ' x').date);
  const files = entries.filter(e => e.isFile() && !e.name.startsWith('.'));
  if (!files.length && subDates.length) { notes.push(`${dirName}/ — already per-occurrence, left alone.`); continue; }
  if (!files.length) continue;

  // The series title: folder name minus a leading date and minus a raw stamp.
  const origBase = splitLeadingDate(dirName).title;
  const title = origBase.replace(/-?\s*\d{8}[_-]\d{6}(UTC)?.*$/, '').replace(/-?\s*Meeting Recording.*$/i, '').trim();

  // Group the files by the date prefix they already carry.
  const groups = new Map();   // date ('' = undated) -> [{ name, suffix }]
  for (const f of files) {
    const lead = splitLeadingDate(f.name);
    const date = lead.date;
    const rest = date ? lead.title : f.name;
    // Everything after the old title is the suffix to preserve
    // (".txt", ".vtt", " action items.md", ...).
    let suffix;
    if (rest.startsWith(origBase)) suffix = rest.slice(origBase.length);
    else if (rest.startsWith(title)) suffix = rest.slice(title.length);
    else suffix = null;       // an outlier file — moved verbatim
    const g = groups.get(date) || [];
    g.push({ name: f.name, suffix });
    groups.set(date, g);
  }

  // Cross-check the group dates against the recordings we know were pulled.
  const fk = titleKeys(title);
  const cand = cands.filter(c => c.keys.words === fk.words || c.keys.squashed === fk.squashed);
  for (const c of cand) c.matchedFolder = dirName;
  const claimed = new Set(cand.filter(c => groups.has(c.date)).map(c => c.name));
  const free = cand.filter(c => !claimed.has(c.name));
  // A date the folder name itself asserts is human-written (hand-named archive
  // upload) and outranks anything inferred from a fuzzy title match — title
  // matching alone can't tell two occurrences of a series apart.
  const assertedDate = splitLeadingDate(dirName).date;

  // Dated groups are resolved before undated ones, so a real transcript group
  // gets first claim on a correction rather than a stray loose file.
  const ordered = [...groups.entries()].sort((a, b) => (a[0] ? 0 : 1) - (b[0] ? 0 : 1));
  const resolved = new Set();
  for (const [date, gfiles] of ordered) {
    let useDate = date, why = '';
    // Filling in a MISSING date is new information; changing one that is
    // already there is a judgment call, so it needs --fix-dates. (The date on
    // disk can be flat wrong: files have been stamped with the day they were
    // pulled rather than the day of the meeting.)
    if (!date || !cand.some(c => c.date === date)) {
      const pick = free.length === 1 ? free[0] : (cand.length === 1 && !claimed.size ? cand[0] : null);
      if (pick && date && date === assertedDate) {
        notes.push(`${dirName}/ — keeping ${date} (asserted by the folder name) even though the ` +
          `closest logged recording is "${pick.name}" (${pick.date}).`);
      } else if (pick && date) {
        disagree.push({ dir: dirName, from: date, to: pick.date, rec: pick.name });
        if (fixDates) {
          useDate = pick.date;
          why = `date corrected ${date} -> ${useDate} (the recording is "${pick.name}")`;
          claimed.add(pick.name);
          free.length = 0;
        }
      } else if (pick) {
        useDate = pick.date;
        why = `dated ${useDate} from the pull log ("${pick.name}")`;
        claimed.add(pick.name);
        free.length = 0;
      } else if (!date) {
        // No log match — fall back to the video's own encode time, then to the
        // folder's own occurrence if it turned out to have exactly one (loose
        // files belong with the meeting they were dropped next to).
        const mp4 = gfiles.map(f => f.name).find(n => /\.mp4$/i.test(n));
        const d = mp4 && mp4Date(path.join(absDir, mp4));
        if (d) { useDate = dateToPrefix(d); why = `dated ${useDate} from the video's encode time`; }
        else if (resolved.size === 1) {
          useDate = [...resolved][0];
          why = `loose file(s) filed with this folder's only occurrence, ${useDate}`;
        }
      }
    }
    if (useDate) resolved.add(useDate);
    if (!useDate) {
      stuck.push(`${dirName}/ — ${gfiles.length} undated file(s), no recording in the pull log and no ` +
        `video to read a date from: ${gfiles.map(f => f.name).join(', ')}`);
      continue;
    }
    if (why) notes.push(`${dirName}/ — ${why}`);

    const destDir = path.join(title, useDate);
    for (const f of gfiles) {
      const newName = f.suffix === null ? f.name : `${useDate} ${title}${f.suffix}`;
      moves.push({ from: path.join(dirName, f.name), to: path.join(destDir, newName) });
    }
    const rec = cand.find(c => c.date === useDate);
    if (rec && rec.url) sources.push({ dir: destDir, rec: {
      url: rec.url, recordingName: rec.name, title, date: useDate,
      dateSource: 'migrate-layout.js (from pulls.jsonl)', migratedAt: new Date().toISOString(),
    } });
  }
}

// ---- report / execute ------------------------------------------------------
const realMoves = moves.filter(m => m.from !== m.to);
console.log(`${apply ? 'APPLYING' : 'PLAN (dry run)'} — ${realMoves.length} file move(s)\n`);
let lastDir = '';
for (const m of realMoves) {
  const d = path.dirname(m.from);
  if (d !== lastDir) { console.log(`  ${d}/`); lastDir = d; }
  console.log(`      ${path.basename(m.from)}\n        -> ${m.to}`);
}
if (notes.length) { console.log('\nDate findings:'); for (const n of notes) console.log('  - ' + n); }
if (stuck.length) { console.log('\nNeeds a manual date (left in place):'); for (const s of stuck) console.log('  - ' + s); }
if (disagree.length) {
  console.log(`\nDate disagreements ${fixDates ? '(being corrected)' : '(NOT corrected — pass --fix-dates)'}:`);
  for (const d of disagree)
    console.log(`  - ${d.dir}/ is filed as ${d.from}, but its recording is "${d.rec}" (${d.to}).`);
}
const orphans = cands.filter(c => !c.matchedFolder);
if (orphans.length) {
  console.log('\nLogged recordings not matched to any local folder — "--replay" will (re)pull these:');
  for (const o of orphans) console.log(`  - ${o.date}  ${o.name}`);
}

if (!apply) { console.log('\nDry run — nothing moved. Re-run with --apply.'); process.exit(0); }

let moved = 0, skipped = 0;
for (const m of realMoves) {
  const from = path.join(ROOT, m.from), to = path.join(ROOT, m.to);
  if (fs.existsSync(to)) { console.log(`  SKIP (target exists): ${m.to}`); skipped++; continue; }
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.renameSync(from, to);
  moved++;
}
for (const s of sources) {
  const d = path.join(ROOT, s.dir);
  if (!fs.existsSync(d)) continue;
  const p = path.join(d, '_source.json');
  if (!fs.existsSync(p)) fs.writeFileSync(p, JSON.stringify(s.rec, null, 2) + '\n');
}
// Drop the now-empty old folders.
let pruned = 0;
for (const dirName of fs.readdirSync(ROOT)) {
  const abs = path.join(ROOT, dirName);
  try {
    if (!fs.statSync(abs).isDirectory() || skipDir(dirName)) continue;
    if (!fs.readdirSync(abs).length) { fs.rmdirSync(abs); pruned++; }
  } catch {}
}
console.log(`\nMoved ${moved}, skipped ${skipped}, pruned ${pruned} empty folder(s). ` +
  `Wrote ${sources.length} _source.json sidecar(s).`);
