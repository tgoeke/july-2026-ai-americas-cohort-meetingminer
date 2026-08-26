// Probe: for each stream URL given on argv, sniff driveId/itemId from player
// traffic and print the driveItem's createdDateTime / lastModifiedDateTime plus
// the video facet duration — the authoritative "when was this recorded" signals.
const { chromium } = require('playwright');
const path = require('path');
const PROFILE = path.join(__dirname, '.transcript-profile');

function watchForItemIds(page, origin) {
  const found = {};
  page.on('request', r => {
    if (found.driveId) return;
    const m = r.url().match(/\/drives\/([^/]+)\/items\/([^/?]+)/i);
    if (m && (r.url().startsWith(origin) || /svc\.ms/.test(r.url()))) {
      found.driveId = decodeURIComponent(m[1]);
      found.itemId = decodeURIComponent(m[2]);
    }
  });
  return found;
}

(async () => {
  const urls = process.argv.slice(2);
  const ctx = await chromium.launchPersistentContext(PROFILE, {
    headless: true, channel: 'chrome', viewport: { width: 1400, height: 1000 },
  });
  for (const url of urls) {
    const page = await ctx.newPage();
    const u = new URL(url);
    const ids = watchForItemIds(page, u.origin);
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(6000);
    for (let i = 0; i < 24 && !ids.driveId; i++) await page.waitForTimeout(500);
    const site = (u.searchParams.get('id') || '').match(/^\/(personal|sites|teams)\/[^/]+/i);
    if (!ids.driveId || !site) { console.log('NO IDS for', url); await page.close(); continue; }
    const cookies = await ctx.cookies(u.origin);
    const ua = await page.evaluate(() => navigator.userAgent);
    const H = { Cookie: cookies.map(c => `${c.name}=${c.value}`).join('; '), 'User-Agent': ua, Accept: 'application/json' };
    const base = `${u.origin}${site[0]}/_api/v2.0/drives/${ids.driveId}/items/${ids.itemId}`;
    const r = await fetch(`${base}?select=id,name,size,createdDateTime,lastModifiedDateTime,video,media,fileSystemInfo`, { headers: H });
    const body = await r.text();
    console.log('--- ' + decodeURIComponent(u.searchParams.get('id')).split('/').pop());
    console.log('HTTP ' + r.status);
    try {
      const j = JSON.parse(body);
      console.log(JSON.stringify({
        name: j.name, size: j.size,
        createdDateTime: j.createdDateTime,
        lastModifiedDateTime: j.lastModifiedDateTime,
        fileSystemInfo: j.fileSystemInfo,
        durationMs: j.video && j.video.duration,
      }, null, 2));
      const iso = j.createdDateTime;
      if (iso) console.log('created (local): ' + new Date(iso).toLocaleString('en-US', { timeZone: 'America/New_York' }));
      const lm = j.lastModifiedDateTime;
      if (lm) console.log('modified (local): ' + new Date(lm).toLocaleString('en-US', { timeZone: 'America/New_York' }));
    } catch { console.log(body.slice(0, 400)); }
    await page.close();
  }
  await ctx.close();
})();
