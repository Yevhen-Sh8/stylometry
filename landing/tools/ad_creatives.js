// Малює рекламні картинки DIMS для соцмереж із текстів landing/marketing/ads.json:
//   квадрат 1080×1080 (стрічка Facebook/Instagram/LinkedIn) і 1080×1920 (Stories/Reels).
// Підписи прикладу (назви каналів, рівні схожості) беруться з landing/i18n/<мова>.json,
// числа — з landing/config.json → demo_matrix, тож картинка показує той самий
// реальний прогон DIMS, що й сайт.
//
// Запуск із кореня репозиторію (потрібні Node і Playwright):
//   node landing/tools/ad_creatives.js
// Змінна CHROMIUM — шлях до chromium, якщо Playwright не знаходить свій.
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, 'marketing', 'creatives');
const ads = JSON.parse(fs.readFileSync(path.join(ROOT, 'marketing', 'ads.json'), 'utf8'));
const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'config.json'), 'utf8'));
const fontsCss = 'file://' + path.join(ROOT, 'static', 'fonts.css');

function severity(d, thr) {  // ті самі межі, що core.analysis.classify_severity
  if (d < thr * 0.3) return 'critical';
  if (d < thr * 0.6) return 'high';
  if (d < thr) return 'moderate';
  return 'clear';
}

function pairs() {
  const { values, threshold } = cfg.demo_matrix;
  const out = [];
  for (let i = 0; i < values.length; i++)
    for (let j = i + 1; j < values.length; j++)
      if (values[i][j] < threshold) out.push({ a: i, b: j, d: values[i][j], level: severity(values[i][j], threshold) });
  return out.sort((x, y) => x.d - y.d);
}

const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function html(lang, format) {
  const t = JSON.parse(fs.readFileSync(path.join(ROOT, 'i18n', `${lang}.json`), 'utf8'));
  const c = ads[lang].creative;
  const tall = format === 'story';
  const rows = pairs().slice(0, tall ? 4 : 3).map(p => `
    <li><span class="names">${esc(t.demo.sources[p.a])} <b>↔</b> ${esc(t.demo.sources[p.b])}</span>
      <span class="meter m-${p.level}"><i></i><i></i><i></i><i></i></span>
      <span class="lvl l-${p.level}">${esc(t.demo.levels[p.level])}</span></li>`).join('');
  return `<!doctype html><html lang="${lang}"><head><meta charset="utf-8">
<link rel="stylesheet" href="${fontsCss}">
<style>
  :root { --bg:#0f172a; --card:#111c2f; --line:#223148; --t0:#f8fafc; --t1:#cbd5e1; --t2:#94a3b8; --accent:#60a5fa; --red:#f87171; --orange:#fb923c; --amber:#facc15; --off:#29384f; }
  * { box-sizing: border-box; margin: 0; }
  body { width: 1080px; height: ${tall ? 1920 : 1080}px; background: var(--bg); color: var(--t0);
         font-family: 'DM Sans', 'Onest', system-ui, sans-serif; padding: ${tall ? '150px 84px 140px' : '76px 76px'};
         display: flex; flex-direction: column; gap: ${tall ? 64 : 40}px; overflow: hidden; }
  .brand { display: flex; align-items: center; gap: 18px; }
  .mark { width: 64px; height: 64px; border-radius: 8px; background: var(--t0); color: var(--card); display: flex; align-items: center; justify-content: center; font: 800 32px/1 'JetBrains Mono', monospace; }
  .word { font-weight: 800; font-size: 42px; letter-spacing: -0.01em; } .word span { color: var(--accent); }
  h1 { font-size: ${tall ? 92 : 74}px; line-height: 1.04; letter-spacing: -0.03em; font-weight: 800; text-wrap: balance; }
  .card { background: var(--card); border: 2px solid var(--line); border-radius: 16px; padding: ${tall ? '34px 38px' : '26px 32px'}; }
  .card-title { font: 600 24px/1.2 'JetBrains Mono', monospace; letter-spacing: .06em; text-transform: uppercase; color: var(--t2); margin-bottom: 8px; }
  ul { list-style: none; padding: 0; }
  li { display: grid; grid-template-columns: 1fr auto; grid-template-areas: "n m" "n l"; gap: 6px 22px; align-items: center; padding: ${tall ? 22 : 16}px 0; border-bottom: 2px solid var(--line); }
  li:last-child { border-bottom: 0; }
  .names { grid-area: n; font-size: ${tall ? 36 : 31}px; font-weight: 700; } .names b { color: var(--t2); font-weight: 400; }
  .meter { grid-area: m; justify-self: end; display: flex; gap: 6px; } .meter i { width: 34px; height: 14px; border-radius: 4px; background: var(--off); }
  .m-critical i { background: var(--red); } .m-high i:nth-child(-n+3) { background: var(--orange); } .m-moderate i:nth-child(-n+2) { background: var(--amber); }
  .lvl { grid-area: l; justify-self: end; font-size: ${tall ? 25 : 22}px; font-weight: 700; }
  .l-critical { color: var(--red); } .l-high { color: var(--orange); } .l-moderate { color: var(--amber); }
  .sub { font-size: ${tall ? 40 : 33}px; line-height: 1.35; color: var(--t1); }
  .cta { margin-top: auto; display: flex; align-items: center; justify-content: space-between; gap: 24px; }
  .btn { background: var(--accent); color: #0b1220; font-weight: 800; font-size: ${tall ? 40 : 34}px; padding: ${tall ? '30px 46px' : '24px 38px'}; border-radius: 10px; }
  .demo { font: 500 22px/1.3 'JetBrains Mono', monospace; color: var(--t2); text-align: right; max-width: 380px; }
</style></head><body>
  <div class="brand"><div class="mark">D</div><div class="word">DIM<span>S</span></div></div>
  <h1>${esc(c.headline)}</h1>
  <div class="card"><div class="card-title">${esc(t.demo.title)} · ${esc(t.demo.tag)}</div><ul>${rows}</ul></div>
  <p class="sub">${esc(c.subline)}</p>
  <div class="cta"><span class="btn">${esc(c.cta)}</span><span class="demo">${esc(c.note || '')}</span></div>
</body></html>`;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'dims-ads-'));
  const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
  for (const lang of Object.keys(ads)) {
    for (const [format, h] of [['square', 1080], ['story', 1920]]) {
      const file = path.join(tmp, `${lang}-${format}.html`);
      fs.writeFileSync(file, html(lang, format));
      const page = await browser.newPage({ viewport: { width: 1080, height: h } });
      await page.goto('file://' + file, { waitUntil: 'networkidle' });
      await page.evaluate(() => document.fonts.ready);
      const overflow = await page.evaluate(() => document.body.scrollHeight - innerHeight);
      if (overflow > 0) console.warn(`${lang}-${format}: текст не вміщується на ${overflow}px`);
      await page.screenshot({ path: path.join(OUT, `dims-${lang}-${format}.png`) });
      await page.close();
    }
  }
  await browser.close();
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log('Готово:', OUT);
})().catch(e => { console.error(e); process.exit(1); });
