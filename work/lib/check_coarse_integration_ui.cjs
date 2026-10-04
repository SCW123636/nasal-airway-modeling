// Read-only UI verification in a fresh browser context; no review decisions.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const base = process.argv[2] || 'http://127.0.0.1:8769';
const out = path.join(root, '07_cfd_pipeline', 'workspace', 'qa');
const cases = ['p0', 'p1', 'p2', 'p3', 'p3t1'];
const inputs = cases.map(c => path.join(root, '06_auto_landmarks', c, 'landmarks.json'));
const digest = async p => crypto.createHash('sha256').update(await fs.readFile(p)).digest('hex');
(async () => {
  const before = await Promise.all(inputs.map(digest));
  const browser = await chromium.launch({headless: true, channel: 'chrome'});
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base + '/workspace/index.html#overview');
    await page.locator('#total-results').filter({hasText: '0'}).waitFor();
    assert.match(await page.locator('#overview-localization').textContent(), /4 组扫描.*1 组粗定位不适用/);
    await page.locator('#project-report summary').click();
    const overview = page.frameLocator('#overview-report iframe');
    const card = overview.locator('#coarse-localization');
    await card.waitFor();
    assert.equal(await card.locator('tr').count(), 6);
    assert.match(await card.textContent(), /带质量警告的粗定位参考：p2/);
    const rows = await card.locator('tr').allTextContents();
    assert(rows.some(row => row.startsWith('p2') && row.includes('1.832 mm') && row.includes('粗定位不适用')));
    assert(rows.some(row => row.startsWith('p0') && row.includes('3 位独立患者') && row.includes('2.58 mm')));
    await page.screenshot({path: path.join(out, 'coarse-integration-desktop.png')});
    await page.setViewportSize({width: 390, height: 844});
    const bounds = await card.evaluate(el => ({width: innerWidth, scroll: document.documentElement.scrollWidth}));
    assert(bounds.scroll <= bounds.width + 1, JSON.stringify(bounds));
    await page.screenshot({path: path.join(out, 'coarse-integration-mobile.png')});
    await page.locator('[data-step=review]').click();
    const review = page.frameLocator('#panel-review iframe');
    await review.locator('#coarse-summary').waitFor();
    assert.match(await review.locator('#coarse-summary').textContent(), /本例采用|本例粗定位不可用/);
    assert.match(await review.locator('#coarse-summary').textContent(), /正式解剖审核分别记录/);
    const manifest = await (await page.request.get(base + '/viewer/workspace_data.json')).json();
    const patients = manifest.cases.filter(c => c.type === 'patient_preview');
    assert.equal(patients.length, 5);
    assert.equal(manifest.patient_cfd_results, 0);
    for (const item of patients) {
      assert(item.localization_summary);
      assert(item.coarse_localization);
      assert(item.coarse_adjustment);
      assert.equal(item.localization_summary.clinical_acceptance, false);
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(await Promise.all(inputs.map(digest)), before);
    const report = {status: 'pass', desktop: '1440x1000', mobile: '390x844',
      coarse_cases: 5, reference_warning_visible: true, patient_cfd_results: 0,
      original_candidates_unchanged: true, errors};
    await fs.writeFile(path.join(out, 'coarse-integration-verification.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode = 1;});
