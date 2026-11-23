// Exercise the delivered UI with responses captured from its real API handlers.
// No network listener or external requests: routes are fulfilled in the browser.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright-core');

(async () => {
  const [artifacts, responsesFile, output] = process.argv.slice(2);
  if (!output) throw new Error('Usage: node review_dashboard.cjs ARTIFACT_DIR RESPONSES_JSON OUTPUT_DIR');
  const responses = JSON.parse(fs.readFileSync(responsesFile, 'utf8'));
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 900}, timezoneId: 'Asia/Hong_Kong'});
    await page.clock.install({time: new Date('2026-12-02T00:30:00+08:00')});
    const errors = [], requests = [], checks = [];
    page.on('pageerror', e => errors.push(e.message));
    let forceError = false;
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.hostname !== 'dashboard.test') return route.abort();
      if (url.pathname === '/api/stats') {
        const key = `${url.searchParams.get('start')}|${url.searchParams.get('end')}`;
        requests.push(key);
        const body = responses[key];
        return route.fulfill({status: forceError || !body ? 503 : 200,
          contentType: 'application/json', body: JSON.stringify(forceError || !body ? {message: 'Review service unavailable'} : body)});
      }
      const name = url.pathname === '/' ? 'index.html' : 'dashboard.html';
      return route.fulfill({status: 200, contentType: 'text/html', body: fs.readFileSync(path.join(artifacts, name), 'utf8')});
    });
    await page.goto('http://dashboard.test/dashboard');
    assert.equal(await page.locator('#end').inputValue(), '2026-12-02');
    assert.equal(await page.locator('#start').inputValue(), '2026-11-03');
    checks.push('Default dates use Hong Kong local date at 00:30, with no UTC shift');
    async function select(start, end) {
      await page.locator('#start').fill(start); await page.locator('#end').fill(end);
      const response = page.waitForResponse(r => r.url().includes('/api/stats?'));
      await page.locator('#apply').click(); await response;
      await page.waitForFunction(() => !document.querySelector('#status').textContent.startsWith('Loading'));
    }
    await select('2026-12-01', '2026-12-02');
    async function cards() { return page.locator('#cards .v').allTextContents(); }
    assert.deepEqual(await cards(), ['3', '1', '25.0%', '4.0 h', '3.1%', '2']);
    const roomRows = await page.locator('#roomsBody tr').allTextContents();
    assert.equal(roomRows.length, 5);
    assert.match(roomRows[0], /Atlas/); assert.match(roomRows[0], /underused/);
    assert.match(await page.locator('#topBody').innerText(), /2026-12-01/);
    assert.match(await page.locator('#cancelText').innerText(), /25.0%/);
    assert.equal(await page.locator('#weekdayBody tr').count(), 7);
    assert.equal(await page.locator('#hourBody tr').count(), 13);
    for (const id of ['roomsChart', 'weekdayChart', 'hourChart', 'cancelChart'])
      assert.ok((await page.locator(`#${id}`).innerText()).length > 5, id);
    checks.push('Known two-day fixture renders correct totals, all five rooms, day/hour charts, cancellation and readable tables');
    await page.screenshot({path: path.join(output, 'desktop.png'), fullPage: true});
    await page.locator('#roomsTable th[data-key="name"]').click();
    assert.match(await page.locator('#roomsBody tr').first().innerText(), /Atlas/);
    await page.locator('#roomsTable th[data-key="name"]').click();
    assert.match(await page.locator('#roomsBody tr').first().innerText(), /Everest/);
    checks.push('Room table sorts by name in both directions');
    await select('2026-12-01', '2026-12-01');
    assert.deepEqual((await cards()).slice(0, 4), ['2', '0', '0.0%', '3.0 h']);
    await select('2026-12-02', '2026-12-02');
    assert.deepEqual((await cards()).slice(0, 4), ['1', '1', '50.0%', '1.0 h']);
    checks.push('Changing dates changes active hours/count and cancellation denominator');
    await select('2026-11-01', '2026-11-30');
    assert.match(await page.locator('#status').innerText(), /No booking records/);
    checks.push('Empty range has an explanatory message');
    await page.locator('#start').fill('2026-12-03'); await page.locator('#end').fill('2026-12-01');
    await page.locator('#apply').click();
    assert.match(await page.locator('#status').innerText(), /start date must be on or before/);
    forceError = true;
    await select('2026-12-01', '2026-12-02');
    assert.match(await page.locator('#status').innerText(), /Could not load analytics/);
    checks.push('Invalid range and API error are visible');
    forceError = false;
    await page.locator('#preset7').click();
    assert.equal(await page.locator('#start').inputValue(), '2026-11-26');
    await page.locator('#presetLast').click();
    assert.equal(await page.locator('#start').inputValue(), '2026-11-01');
    assert.equal(await page.locator('#end').inputValue(), '2026-11-30');
    checks.push('Last seven days and last month presets use correct calendar boundaries');
    await select('2026-12-01', '2026-12-02');
    await page.setViewportSize({width: 390, height: 844});
    const mobile = await page.evaluate(() => ({width: innerWidth, scrollWidth: document.documentElement.scrollWidth}));
    assert.ok(mobile.scrollWidth <= mobile.width + 1);
    await page.screenshot({path: path.join(output, 'mobile.png'), fullPage: true});
    checks.push('390px mobile page has no horizontal document overflow');
    assert.deepEqual(errors, []);
    const result = {passed: true, browser: await browser.version(), source: path.resolve(artifacts),
      method: 'Unmodified HTML in Chromium; HTTP requests intercepted with JSON from real delivered handlers independently executed in Seatbelt. No live HTTP listener.',
      checks, requests, errors, mobile};
    fs.writeFileSync(path.join(output, 'browser-result.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
