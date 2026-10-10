# Лендинг DIMS

Статичний багатомовний сайт-презентація DIMS зі збором заявок у ранній доступ.
Мови: українська, англійська, польська, німецька. Сервер не потрібен: готові
файли лежать у `landing/dist/` і викладаються на будь-який хостинг статики.

## Структура

| Шлях | Що це |
|---|---|
| `config.json` | Ціни, ліміти тарифів, адреса форми, контакти, домен сайту |
| `i18n/*.json` | Тексти сторінок, по файлу на мову (структура однакова) |
| `templates/` | Шаблони Jinja2: головна, політика конфіденційності, 404, вибір мови |
| `static/` | Стилі, скрипт, шрифти (локально, без Google Fonts), зображення |
| `demo-corpus/` | Синтетичні демо-тексти, на яких зроблено скріншоти |
| `tools/screenshots.js` | Перезйомка скріншотів і прев'ю для соцмереж |
| `build.py` | Збирання сайту в `dist/` |
| `dist/` | **Готовий сайт** (генерується, але зберігається в git для деплою) |

## Як змінити тексти чи ціни

1. Відредагуйте `config.json` (ціни, ліміти) або `i18n/<мова>.json` (тексти).
   У текстах можна використовувати змінні: `{early_price}`, `{early_limit}`,
   `{price_year}`, `{price_month}`, `{free_analyses}`, `{free_sources}`, `{pro_sources}`.
2. Зберіть сайт:
   ```bash
   .venv/bin/python landing/build.py
   ```
3. Перевірте: `.venv/bin/python -m pytest tests/test_landing.py -q`.
   Тест падає, якщо `dist/` не перезібрано або переклади мають різну структуру.
4. Локальний перегляд: `python3 -m http.server 8088 -d landing/dist`, далі
   відкрийте http://localhost:8088.

Додаючи ключ в один переклад, додайте його в усі чотири, інакше збирання зупиниться.

## Підключення форми «Ранній доступ»

Без адреси форми сторінка показує, що запис ще не підключено. Найпростіші варіанти:

**Formspree** (безкоштовно до 50 заявок на місяць):
1. Зареєструйтеся на formspree.io і створіть форму.
2. Скопіюйте адресу виду `https://formspree.io/f/abcdwxyz`.
3. У `config.json`: `"endpoint": "https://formspree.io/f/abcdwxyz"`, `"provider_name": "Formspree"`.

**Web3Forms** (безкоштовно до 250 заявок на місяць, без реєстрації):
1. На web3forms.com введіть свій email і отримайте ключ доступу.
2. У `config.json`: `"endpoint": "https://api.web3forms.com/submit"`,
   `"provider_name": "Web3Forms"`, `"extra_fields": {"access_key": "<ключ>"}`.

Після зміни перезберіть сайт. Заявки надходитимуть на ваш email і в кабінет сервісу.
У форму вбудовано пастку для ботів (приховане поле) та обов'язкову згоду.

## Розгортання

### Vercel (рекомендовано, безкоштовно)
1. vercel.com → **Add New → Project** → імпортуйте репозиторій `stylometry`.
2. **Root Directory**: `landing/dist`. **Framework Preset**: Other. Build Command
   і Output Directory залиште порожніми.
3. **Deploy**. Кожен злитий у `main` PR оновлюватиме сайт автоматично.
4. Власний домен: Project → Settings → Domains.

### Інші варіанти
- **Netlify Drop**: перетягніть папку `landing/dist` на app.netlify.com/drop.
- **Cloudflare Pages**: підключіть репозиторій, build output directory — `landing/dist`.
- **GitHub Pages**: якщо сайт житиме за адресою `https://<user>.github.io/stylometry/`,
  встановіть `"base_path": "/stylometry/"` (потрібно для сторінки 404).

### Після отримання домену
Впишіть його в `config.json` → `"site_url": "https://ваш-домен"` і перезберіть.
Так з'являться канонічні адреси, `hreflang` для пошуковиків, `sitemap.xml` та
картинки-прев'ю для Facebook, LinkedIn і Telegram (`static/img/og-*.png`).

## Перед публікацією

- [ ] `contact_email` і `operator_name` у `config.json` (видно у футері та політиці).
- [ ] Підключено форму (розділ вище), перевірено тестовою заявкою.
- [ ] Політику конфіденційності переглянув юрист (текст у `i18n/*.json` → `privacy`).
- [ ] Для аудиторії з Німеччини потрібна сторінка Impressum (§ 5 DDG) з іменем і адресою.
- [ ] `app_url`: посилання на робочу демо-версію застосунку (з'явиться кнопка «Відкрити демо»).

## Оновлення скріншотів

Коли змінюється інтерфейс застосунку:

```bash
PORT=5055 DIMS_DATA_DIR=/tmp/dims-shots .venv/bin/python app.py &
.venv/bin/python landing/build.py && python3 -m http.server 8088 -d landing/dist &
node landing/tools/screenshots.js
.venv/bin/python landing/build.py
```

Скрипт завантажує в застосунок тексти з `demo-corpus/`, запускає аналіз і знімає
робоче середовище, підозрілі пари, профіль індикаторів та звіт. Матриця Δ у
головному блоці береться з `config.json → demo_matrix` (значення з того самого прогону).
