// Browser acceptance against an unchanged file, with a fresh Chrome profile.
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright-core');

(async () => {
  const [source, output] = process.argv.slice(2);
  if (!source || !output) throw new Error('Usage: node review_html_deck.cjs HTML OUTPUT_DIR');
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
  });
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 800}});
    await page.route('http://**/*', route => route.abort());
    await page.route('https://**/*', route => route.abort());
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(pathToFileURL(path.resolve(source)).href);
    const count = await page.locator('.slide').count();
    const checks = [];
    async function check(label, index) {
      const observed = await page.evaluate(() => ({
        active: [...document.querySelectorAll('.slide')].findIndex(s => s.classList.contains('active')),
        activeCount: document.querySelectorAll('.slide.active').length,
        counter: document.querySelector('#counter').textContent,
        progress: document.querySelector('#bar').style.width,
      }));
      const pass = observed.active === index && observed.activeCount === 1 && observed.counter === `${index + 1} / ${count}`;
      checks.push({label, pass, ...observed});
      if (!pass) throw new Error(`Navigation failed: ${label}`);
    }
    await check('initial', 0);
    await page.screenshot({path: path.join(output, 'desktop.png')});
    for (let i = 1; i <= count; i++) {
      await page.locator('#next').click();
      await check(`next ${i}`, i % count);
    }
    await page.locator('#prev').click(); await check('previous wraps', count - 1);
    await page.keyboard.press('Home'); await check('home', 0);
    await page.keyboard.press('ArrowRight'); await check('right', 1);
    await page.keyboard.press('ArrowLeft'); await check('left', 0);
    await page.keyboard.press('Space'); await check('space', 1);
    await page.keyboard.press('PageDown'); await check('page down', 2);
    await page.keyboard.press('PageUp'); await check('page up', 1);
    await page.keyboard.press('End'); await check('end', count - 1);
    await page.setViewportSize({width: 390, height: 844});
    await page.keyboard.press('Home');
    await page.screenshot({path: path.join(output, 'mobile.png')});
    const layout = [];
    for (let i = 0; i < count; i++) {
      layout.push(await page.locator('.slide.active').evaluate(el => ({
        title: el.querySelector('h1,h2')?.textContent,
        width: el.clientWidth, scrollWidth: el.scrollWidth,
        horizontalOverflow: el.scrollWidth > el.clientWidth + 1,
        height: el.clientHeight, scrollHeight: el.scrollHeight,
      })));
      await page.locator('#next').click();
    }
    const result = {source: path.resolve(source), browser: await browser.version(), count, checks, errors, mobileLayout: layout,
      navigationPassed: checks.every(c => c.pass) && !errors.length,
      horizontalOverflowSlides: layout.filter(x => x.horizontalOverflow).map(x => x.title)};
    fs.writeFileSync(path.join(output, 'browser-result.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
