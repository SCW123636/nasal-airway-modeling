import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [sourceArg, packagesArg] = process.argv.slice(2);
if (!sourceArg || !packagesArg) throw new Error('Supply source Markdown and bundled package directory');
const source = path.resolve(sourceArg);
const { marked } = await import(pathToFileURL(path.join(packagesArg, 'marked/lib/marked.esm.js')));
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const sections = [];
let headingCount = 0;
const renderer = new marked.Renderer();
renderer.heading = function ({ tokens, depth }) {
  const text = this.parser.parseInline(tokens);
  const id = `heading-${++headingCount}`;
  if (depth === 2) sections.push({ id, text });
  return `<h${depth} id="${id}">${text}</h${depth}>\n`;
};
renderer.image = function ({ href, text }) {
  const file = path.resolve(path.dirname(source), href);
  if (!fs.existsSync(file)) throw new Error(`Missing figure: ${file}`);
  const ext = path.extname(file).toLowerCase();
  const type = ext === '.png' ? 'image/png' : ext === '.jpg' ? 'image/jpeg' : null;
  if (!type) throw new Error(`Unsupported figure: ${ext}`);
  return `<img src="data:${type};base64,${fs.readFileSync(file).toString('base64')}" alt="${escape(text)}">`;
};
renderer.table = function (token) {
  return `<div class="table-wrap">${marked.Renderer.prototype.table.call(this, token)}</div>\n`;
};
const content = marked.parse(fs.readFileSync(source, 'utf8'), { renderer, gfm: true });
const toc = sections.map(({ id, text }) => `<li><a href="#${id}">${text}</a></li>`).join('\n');
const title = path.basename(source, '.md');
const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>${escape(title)}</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; color: #252a2d; background: #fff; font: 16px/1.85 "Microsoft YaHei", "PingFang SC", sans-serif; letter-spacing: 0; }
main { max-width: 980px; margin: 0 auto; padding: 32px 44px 60px; }
h1 { font-size: 28px; line-height: 1.45; font-weight: 600; margin: 8px 0 20px; }
h2 { font-size: 23px; line-height: 1.5; font-weight: 600; margin: 44px 0 18px; padding-top: 12px; border-top: 1px solid #d7dfe1; }
h3 { font-size: 18px; line-height: 1.6; font-weight: 600; margin: 28px 0 12px; }
p, li { overflow-wrap: anywhere; }
p { margin: 14px 0; }
strong { font-weight: 600; }
a { color: #08766c; text-underline-offset: 3px; }
blockquote { margin: 20px 0; padding: 2px 0 2px 18px; border-left: 3px solid #8abbb4; color: #364849; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: 12px 0; border-top: 1px solid #e4e8e9; border-bottom: 1px solid #e4e8e9; }
code { font-family: Consolas, "Microsoft YaHei", monospace; font-size: .91em; overflow-wrap: anywhere; }
ol, ul { padding-left: 1.65em; }
li { margin: 7px 0; }
.table-wrap { overflow-x: auto; margin: 20px 0; }
table { width: 100%; border-collapse: collapse; font-size: 14px; line-height: 1.7; }
th, td { padding: 10px 12px; border-bottom: 1px solid #dfe5e6; text-align: left; vertical-align: top; min-width: 90px; overflow-wrap: anywhere; }
th { background: #edf3f1; font-weight: 600; }
img { display: block; width: 100%; height: auto; margin: 22px 0 14px; }
nav { margin: 0 0 26px; border-bottom: 1px solid #d7dfe1; padding-bottom: 12px; }
summary { font-weight: 600; }
nav ol { columns: 2; column-gap: 30px; }
nav li { break-inside: avoid; }
@media (max-width: 600px) {
  main { padding: 20px 18px 42px; }
  h1 { font-size: 25px; }
  h2 { font-size: 21px; }
  nav ol { columns: 1; }
  th, td { padding: 8px; min-width: 88px; }
}
@media print {
  @page { size: A4; margin: 18mm 16mm; }
  body { font-size: 11pt; }
  main { padding: 0; max-width: none; }
  nav { display: none; }
  h1 { font-size: 20pt; }
  h2 { font-size: 15pt; break-after: avoid; }
  h3 { font-size: 12pt; break-after: avoid; }
  img, tr, blockquote { break-inside: avoid; }
  a { color: inherit; }
  .table-wrap { overflow: visible; }
}
</style>
</head>
<body>
<main>
<nav aria-label="文档目录"><details><summary>目录</summary><ol>${toc}</ol></details></nav>
${content}
</main>
</body>
</html>
`;
const destination = source.replace(/\.md$/i, '.html');
fs.writeFileSync(destination, html, 'utf8');
console.log(JSON.stringify({ destination, sections: sections.length,
  embeddedFigures: (content.match(/src="data:image/g) || []).length,
  bytes: fs.statSync(destination).size }));
