/* Inspect a generated offline bundle; no patient state is modified. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function main() {
  const bundle = path.resolve(process.argv[2]);
  const out = path.resolve(process.argv[3]);
  await fs.mkdir(out, {recursive: true});
  const summary = JSON.parse(await fs.readFile(path.join(bundle, 'summary.json'), 'utf8'));
  const expectedImages = summary.cases.reduce((sum, record) => sum + record.images.length, 0);
  const browser = await chromium.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE});
  const errors = [], requests = [], result = {};
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {if (/^https?:/.test(request.url())) requests.push(request.url());});
    await page.goto(pathToFileURL(path.join(bundle, 'index.html')).href);
    await page.evaluate(() => {for (const image of document.images) image.loading = 'eager';});
    await page.waitForFunction(() => [...document.images].every(image => image.complete && image.naturalWidth > 0));
    Object.assign(result, await page.evaluate(() => ({title: document.title,
      sections: document.querySelectorAll('section').length, images: document.images.length,
      loaded: [...document.images].filter(image => image.complete && image.naturalWidth > 0).length})));
    assert.equal(result.sections, summary.cases.length);
    assert.equal(result.images, expectedImages);
    assert.equal(result.loaded, expectedImages);
    await page.screenshot({path: path.join(out, 'desktop.png')});
    await page.locator('nav a').filter({hasText: /^p2$/}).click();
    assert.equal(new URL(page.url()).hash, '#p2');
    await page.screenshot({path: path.join(out, 'p2-desktop.png')});
    for (const width of [390, 320]) {
      await page.setViewportSize({width, height: 844});
      result['width_' + width] = await page.evaluate(() => ({bodyWidth: document.body.scrollWidth,
        viewport: innerWidth, overflow: document.body.scrollWidth > innerWidth}));
      assert.equal(result['width_' + width].overflow, false);
      await page.screenshot({path: path.join(out, 'mobile-' + width + '.png')});
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, []);
    await fs.writeFile(path.join(out, 'verification.json'), JSON.stringify({result, errors, httpRequests: requests}, null, 2));
    console.log(JSON.stringify({result, errors, httpRequests: requests}));
  } finally {
    await browser.close();
  }
}
main().catch(error => {console.error(error.stack); process.exit(1);});
