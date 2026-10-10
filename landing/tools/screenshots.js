// Знімає скріншоти справжнього інтерфейсу DIMS на синтетичному демо-наборі
// (landing/demo-corpus) і кладе їх у landing/static/img/*.webp та og-*.png.
//
// Потрібно: запущений застосунок (PORT=5055 python3 app.py), зібраний і
// розданий лендинг (python3 -m http.server 8088 -d landing/dist), Node +
// Playwright, Python із Pillow (.venv). Запуск із кореня репозиторію:
//   node landing/tools/screenshots.js
// Змінні: APP_URL (типово http://localhost:5055), SITE_URL (http://localhost:8088),
//         CHROMIUM (шлях до chromium, якщо Playwright не знаходить свій).
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const APP = process.env.APP_URL || 'http://localhost:5055';
const SITE = process.env.SITE_URL || 'http://localhost:8088';
const IMG = path.join(ROOT, 'static', 'img');
const SOURCES = [
  ['Канал A (демо)', 'a_kanal_A.txt'],
  ['Канал B (демо)', 'b_kanal_B.txt'],
  ['Канал C (демо)', 'c_kanal_C.txt'],
  ['Новинний сайт 1 (демо)', 'd_novyny_1.txt'],
  ['Новинний сайт 2 (демо)', 'e_novyny_2.txt'],
];

(async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'dims-shots-'));
  const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});

  // 1. Застосунок: робоче середовище, результати, звіт.
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  await ctx.addInitScript(() => localStorage.setItem('dims-theme', 'dark'));
  const page = await ctx.newPage();
  await page.goto(APP);
  await page.request.post(`${APP}/api/clear`);
  await page.reload();
  await page.addStyleTag({ content: '#toast{display:none!important}' });
  await page.click('#tabbtn-text');
  for (const [label, file] of SOURCES) {
    await page.fill('#manualLabel', label);
    await page.fill('#manualInput', fs.readFileSync(path.join(ROOT, 'demo-corpus', file), 'utf8').trim());
    const added = page.waitForResponse(r => r.url().includes('/api/add-text'));
    await page.click('#btnAddManual');
    await added;
  }
  await page.click('#tabbtn-files');
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(tmp, 'workspace.png') });
  await page.click('#btnAnalyze');
  await page.waitForSelector('#sectionResults:not(.hidden)', { timeout: 180000 });
  await page.waitForTimeout(2000);
  await (await page.$('#sectionResults')).screenshot({ path: path.join(tmp, 'results.png') });
  const light = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  const report = await light.newPage();
  await report.goto(`${APP}/report`);
  await report.waitForTimeout(1500);
  await report.screenshot({ path: path.join(tmp, 'report.png') });

  // 2. Обрізання й WebP (Pillow). Межі підібрано під поточну розкладку застосунку.
  execFileSync(path.join(ROOT, '..', '.venv', 'bin', 'python'), ['-c', `
from PIL import Image
tmp, out = ${JSON.stringify(tmp)}, ${JSON.stringify(IMG)}
def save(img, name, width):
    if img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    img.convert("RGB").save(f"{out}/{name}.webp", "WEBP", quality=80, method=6)
save(Image.open(f"{tmp}/workspace.png"), "workspace-dark", 1600)
r = Image.open(f"{tmp}/results.png")
save(r.crop((0, 520, r.width, 1840)), "indicators-dark", 1400)
save(r.crop((0, 1840, r.width, r.height - 190)), "pairs-dark", 1400)
rep = Image.open(f"{tmp}/report.png")
save(rep.crop((634, 58, 2246, 1135)), "report", 1200)  # шапка й цифри, без підсумку (у демо немає даних охоплення)
`], { stdio: 'inherit' });

  // 3. Прев'ю для соцмереж 1200×630 з головного блоку лендингу.
  for (const lang of ['uk', 'en', 'pl', 'de']) {
    const og = await browser.newContext({ viewport: { width: 1200, height: 630 }, colorScheme: 'dark' });
    const p = await og.newPage();
    await p.goto(`${SITE}/${lang}/`, { waitUntil: 'networkidle' });
    await p.addStyleTag({ content: `
      .topbar, .hero .lead, .hero .actions, .offer, .matrix-caption, .matrix-stats { display: none !important; }
      .matrix td.cell { animation: none !important; }
      .hero { padding: 0 !important; height: 630px; display: flex; align-items: center; }
      .hero-grid { grid-template-columns: 1fr 0.95fr !important; gap: 44px !important; padding-inline: 60px !important; max-width: none !important; }
      .hero h1 { font-size: 54px !important; }
      .hero-copy { gap: 26px !important; }
      .og-brand { display: flex; align-items: center; gap: 14px; }
      .og-brand .brand-mark { width: 46px; height: 46px; font-size: 22px; }
      .og-brand .brand-word { font-size: 30px; }` });
    await p.evaluate(() => {
      const brand = document.createElement('div');
      brand.className = 'og-brand';
      brand.innerHTML = '<span class="brand-mark">D</span><span class="brand-word">DIM<span>S</span></span>';
      document.querySelector('.hero-copy').prepend(brand);
    });
    await p.waitForTimeout(400);
    await p.screenshot({ path: path.join(IMG, `og-${lang}.png`) });
    await og.close();
  }
  await browser.close();
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log('Готово. Тепер: python3 landing/build.py');
})().catch(e => { console.error(e); process.exit(1); });
