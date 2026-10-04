import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const [documentArg, previewArg, packagesArg] = process.argv.slice(2);
const require = createRequire(path.join(packagesArg, 'package.json'));
const { chromium } = require('playwright');
const output = path.dirname(path.resolve(previewArg));
const candidates = [chromium.executablePath(),
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'];
const executablePath = candidates.find(file => fs.existsSync(file));
if (!executablePath) throw new Error('No installed Chromium browser found');
const browser = await chromium.launch({ executablePath, headless: true });
const results = { document: [], geometry: [], errors: [] };
const page = await browser.newPage();
page.on('pageerror', error => results.errors.push(error.message));
try {
  for (const width of [1365, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(pathToFileURL(path.resolve(documentArg)).href);
    const metrics = await page.evaluate(() => ({
      width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
      sections: document.querySelectorAll('h2').length,
      figures: [...document.images].map(img => ({ embedded: img.src.startsWith('data:image/'),
        rendered: img.complete && img.naturalWidth > 0 })),
      externalAssets: [...document.querySelectorAll('script[src],link[rel="stylesheet"]')].length,
      sourceAnchors: document.querySelectorAll('nav a').length,
      emphasisMarkersVisible: document.querySelector('main').innerText.includes('**'),
      allTocTargetsExist: [...document.querySelectorAll('nav a')].every(link => document.querySelector(link.getAttribute('href'))),
    }));
    if (metrics.scrollWidth > width || metrics.sections !== 19 || metrics.figures.length !== 3 ||
        !metrics.figures.every(img => img.embedded && img.rendered) || !metrics.allTocTargetsExist || metrics.emphasisMarkersVisible) {
      throw new Error(`Document layout or assets failed: ${JSON.stringify(metrics)}`);
    }
    results.document.push(metrics);
    if (width !== 320) {
      await page.screenshot({ path: path.join(output, `document-${width}-top.png`) });
      await page.getByRole('heading', { name: '12.1 示例：p0 右鼻孔入口', exact: true }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(output, `document-${width}-example.png`) });
      await page.locator('img').first().scrollIntoViewIfNeeded();
      await page.screenshot({ path: path.join(output, `document-${width}-figure.png`) });
    }
  }
  for (const width of [736, 390, 320]) {
    await page.setViewportSize({ width, height: 850 });
    await page.goto(pathToFileURL(path.resolve(previewArg)).href);
    const frame = await page.locator('iframe').contentFrame();
    await frame.locator('.plane-diagram').waitFor();
    await frame.locator('#plane-offset').fill('0');
    await frame.locator('#plane-angle').fill('0');
    const initial = await frame.locator('.plane-diagram').evaluate(svg => {
      const current = [...svg.querySelectorAll('line')].find(line => line.getAttribute('stroke-width') === '2.5');
      return { x1: current.getAttribute('x1'), y1: current.getAttribute('y1') };
    });
    await frame.locator('#plane-offset').fill('2');
    await frame.locator('#plane-angle').fill('30');
    const metrics = await frame.locator('#landmark-plane-geometry').evaluate(root => {
      const svg = root.querySelector('svg');
      const plane = [...svg.querySelectorAll('line')].find(line => line.getAttribute('stroke-width') === '2.5');
      const normal = [...svg.querySelectorAll('line')].find(line => line.hasAttribute('marker-end'));
      const vector = line => [Number(line.getAttribute('x2')) - Number(line.getAttribute('x1')),
        Number(line.getAttribute('y2')) - Number(line.getAttribute('y1'))];
      const p = vector(plane), n = vector(normal);
      const dot = p[0] * n[0] + p[1] * n[1];
      const textBounds = [...svg.querySelectorAll('text')].map(t => t.getBBox());
      return { width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
        x1: plane.getAttribute('x1'), y1: plane.getAttribute('y1'),
        perpendicularCosine: dot / Math.hypot(...p) / Math.hypot(...n),
        labelsFit: textBounds.every(b => b.x >= 0 && b.x + b.width <= svg.viewBox.baseVal.width + .1 && b.y >= 0 && b.y + b.height <= 290.1),
        offset: root.querySelector('#plane-offset-value').value,
        angle: root.querySelector('#plane-angle-value').value,
        detail: root.querySelector('#plane-detail').textContent };
    });
    if (metrics.scrollWidth > metrics.width || Math.abs(metrics.perpendicularCosine) > 1e-9 ||
        !metrics.labelsFit || metrics.offset !== '+2.0 mm' || metrics.angle !== '+30°' ||
        (initial.x1 === metrics.x1 && initial.y1 === metrics.y1)) {
      throw new Error(`Geometry interaction or layout failed: ${JSON.stringify(metrics)}`);
    }
    results.geometry.push(metrics);
    await page.screenshot({ path: path.join(output, `geometry-${width}.png`) });
  }
  if (results.errors.length) throw new Error(`Browser errors: ${results.errors.join('; ')}`);
  fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
} finally {
  await browser.close();
}
