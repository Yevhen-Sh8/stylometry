# DIMS — Інтегральна оцінка дезінформаційних ризиків

Веб-застосунок для апробації **удосконаленої методики моніторингу інформації у відкритих джерелах із застосуванням стилометричного методу** (Шерстюк Є.І., НУОУ, спеціальність 126 — Інформаційні системи та технології).

---

## Що це

Інструмент реалізує дисертаційний науковий результат — методику **DIMS** (Disinformation Information Monitoring Score), яка поєднує стилометричний аналіз на основі метрики Burrows Delta з п'ятьма індикаторами ризику:

```
R_DIMS = w₁·I_content + w₂·I_coord + w₃·I_dynamics + w₄·I_impact + w₅·I_source
```

| Індикатор | Зміст |
|---|---|
| `I_content` | Змістовий аналіз: маніпулятивні маркери, тональність |
| `I_coord` | Координаційний: синхронність публікацій між джерелами |
| `I_dynamics` | Динамічний: темп поширення, часові патерни |
| `I_impact` | Вплив: охоплення, тиражування |
| `I_source` | Ризик джерела: домен, власник, редакційні ознаки |

**Грейди** (за Наказом МО України № 46): `F → B → S → SS → SSS`

---

## Функціональність

### Додавання джерел
- **Файли** — drag & drop: TXT, PDF, DOCX, RTF, HTML
- **Вручну** — вставити URL (автофетч), HTML-код (очистка) або plain text
- **Пошук новин** — три режими:
  - Google News RSS (мови: RU, DE, FR, UA, EN)
  - RSS/Atom стрічка будь-якого ресурсу (ТАСС, RT, Sputnik тощо)
  - Telegram публічний канал — з агрегацією постів в один документ для надійного Burrows Delta

### Аналіз
- **Burrows Delta** або **Cosine Delta** — стилометрична відстань між джерелами
- **Еталони мов** (uk, ru, en, pl, de) — z-оцінки за великим корпусом мови, тож
  відстань пари не залежить від решти набору
- **Автоматичний поріг θ_Δ** — пара ближча, ніж 99 % випадкових пар незалежних
  текстів такої довжини; перцентиль і вердикт пари (*strong* / *possible*)
- **Довірчий інтервал** відстані перевибіркою тексту (блоковий бутстреп)
- **Дендрограма** — кластеризація за стилем
- **PCA/MDS/t-SNE** — проєкція джерел у 2D
- **Теплокарта** відстаней з порогом θ_Δ
- Рівні обсягу тексту: < 500 слів — замало, < 2 500 — орієнтовно, ≥ 2 500 — надійно

### Звіт
- PDF/HTML звіт з повним DIMS-розкладом
- Форма щоденного моніторингу (експорт DOCX)
- Журнал сесій

---

## Запуск

### Вимоги
- Python 3.9+
- macOS / Linux

### Встановлення

```bash
git clone https://github.com/Yevhen-Sh8/stylometry.git
cd stylometry
pip install -r requirements.txt
```

### Запуск

```bash
python3 app.py
```

Відкрити у браузері: **http://localhost:5001**

### Production-деплой

Проєкт є повноцінним Python/Flask застосунком із науковими залежностями
(`numpy`, `scipy`, `scikit-learn`, `matplotlib`) і файловими операціями для
звітів. Його потрібно деплоїти як Python web service або Docker container, а не
як статичний сайт.

Універсальний production-контракт:

```bash
pip install -r requirements.txt
export MPLCONFIGDIR=/tmp/matplotlib
gunicorn app:app --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-1} --timeout ${WEB_TIMEOUT:-180}
```

Підтримані варіанти:

- **Render / Railway / Fly.io / VPS** — рекомендовано; використати `Dockerfile`
  або `Procfile`.
- **GitHub** — джерело коду та CI/CD, але не runtime для Flask-застосунку.
- **Vercel** — можна використовувати тільки для окремого frontend або
  serverless-обгортки; для цього проєкту як є не рекомендовано через важкі
  Python-залежності та довгі обчислення.
- **Cloudflare Workers / Pages** — не використовувати для повного застосунку:
  Workers не запускає Flask/Python backend. Cloudflare доречно лишити для DNS,
  CDN або окремого статичного frontend, якщо API розгорнуто на Python-хостингу.

Docker-запуск локально:

```bash
docker build -t dims-stylometry .
docker run --rm -p 5001:5001 -e PORT=5001 dims-stylometry
```

### Деплой на Railway

У репозиторії є `railway.json`, `Dockerfile`, `Procfile` і `runtime.txt`.
Railway має запускати застосунок як Docker-based Python web service.

1. У Railway створити **New Project**.
2. Обрати **Deploy from GitHub repo**.
3. Вибрати репозиторій `Yevhen-Sh8/stylometry`.
4. Після першого деплою відкрити **Settings → Networking** і натиснути
   **Generate Domain**.
5. Перевірити `/healthz`: відповідь має бути `{"status":"ok"}`.

Railway автоматично передає змінну `PORT`; застосунок уже слухає саме її.
Команда запуску зафіксована в `railway.json`:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-1} --timeout ${WEB_TIMEOUT:-180}
```

### Деплой на Render

Для Render потрібно створювати **Web Service**, не Static Site. У репозиторії є
`render.yaml`, який фіксує Docker runtime, free plan, порт `10000`,
`WEB_CONCURRENCY=1` і healthcheck `/healthz`.

Ручне створення:

1. Render Dashboard → **New** → **Web Service**.
2. Підключити репозиторій `Yevhen-Sh8/stylometry`.
3. Runtime / Environment: **Docker**.
4. Instance type: **Free**.
5. Health Check Path: `/healthz`.
6. Environment Variables:
   - `PORT=10000`
   - `WEB_CONCURRENCY=1`
   - `WEB_TIMEOUT=180`
   - `MPLCONFIGDIR=/tmp/matplotlib`
   - `DIMS_ADMIN_TOKEN=<довгий випадковий токен для змін у застосунку>`
   - `MONITOR_TOKEN=<окремий токен для cron, опційно>`
7. Створити сервіс і дочекатися deploy.
8. Перевірити `https://<service>.onrender.com/healthz`.

Render free instance може засинати після простою, тому перший запит після паузи
буде повільним.

Якщо `DIMS_ADMIN_TOKEN` заданий, усі дії, що змінюють стан застосунку
(завантаження файлів, додавання URL/тексту, очищення корпусу, запуск аналізу,
збереження налаштувань і запуск моніторингу), потребують заголовок
`X-DIMS-Admin-Token`. Вебінтерфейс попросить цей токен при першій такій дії та
збереже його локально в браузері.

### Автоматичний моніторинг

У вкладці **Моніторинг** можна створювати теми з окремими ключовими словами для
`RU / UA / EN / DE / FR`. Ручний запуск виконує пошук у Google News, збережених
RSS-стрічках і збережених Telegram-каналах, після чого додає матеріали в чергу
для перегляду та імпорту.

Для запуску за розкладом є endpoint:

```bash
POST /api/monitor/cron
```

Якщо на Render задано `MONITOR_TOKEN`, cron-запит має передавати такий самий
токен у заголовку. Якщо `MONITOR_TOKEN` не задано, endpoint приймає
`DIMS_ADMIN_TOKEN`:

```bash
X-Monitor-Token: <token>
```

У репозиторії є GitHub Actions workflow `.github/workflows/monitoring.yml`, який
викликає цей endpoint кожні 6 годин. Для нього потрібно додати GitHub Secrets:

- `MONITOR_URL` — наприклад `https://stylometry-vjxv.onrender.com`
- `MONITOR_TOKEN` — той самий токен, що в Render; опційно, якщо замість нього
  використовується `DIMS_ADMIN_TOKEN`
- `DIMS_ADMIN_TOKEN` — запасний токен для cron і той самий токен, який заданий
  на Render

### Інтеграція з ІАС (окремий сервіс)

DIMS може працювати як окремий сервіс ІАС підтримки прийняття рішень. Сканер
періодично читає БД модуля моніторингу інформаційного простору (лише
читання, будь-яка СУБД через SQLAlchemy) і оцінює змінені події за методикою.
Якщо знаходить ознаки скоординованої атаки, сповіщає через webhook і
`GET /api/v1/alerts`. Машинний API v1 (`/api/v1/assess`, `/alerts`,
`/alerts/{id}/review`, `/feedback`, `/status`) захищено сервісними токенами
`DIMS_SERVICE_TOKENS`.

```bash
cp deploy/ias/.env.example deploy/ias/.env   # заповнити
docker compose -f deploy/ias/docker-compose.yml --env-file deploy/ias/.env up -d --build
```

Деталі — `docs/ias_integration_ua.md`, специфікація — `docs/openapi_v1.yaml`.

---

## Структура проєкту

```
stylometry/
├── app.py                  # Flask-сервер, всі API-ендпоінти
├── core/
│   ├── analysis.py         # Burrows/Cosine Delta, токенізатор, DIMS-оцінки
│   ├── reference.py        # Еталонна статистика мов, авто-поріг, перцентилі
│   ├── extractors.py       # Парсинг PDF, DOCX, RTF, HTML
│   ├── monitoring_forms.py # Форма щоденного моніторингу
│   ├── monitoring_log.py   # Журнал сесій
│   ├── scraper.py          # Завантаження URL, RSS, Telegram
│   ├── ias_service.py      # Безстанова оцінка події для ІАС
│   ├── ias_scanner.py      # Сканер БД модуля моніторингу ІАС
│   ├── ias_store.py        # Сховище оцінок і сповіщень сервісу
│   └── api_v1.py           # REST API v1 (сервісні токени)
├── deploy/ias/             # docker-compose + .env.example для ІАС
├── Data/reference/         # Еталони мов (uk, ru, en, pl, de) + README з ліцензіями
├── benchmarks/             # Бенчмарк авторства ELTeC-ukr (протокол і результати)
├── tools/                  # validation.py, build_reference.py, authorship_benchmark.py
├── static/
│   ├── app.js              # Фронтенд (vanilla JS)
│   └── style.css           # Стилі (темна/світла тема)
├── templates/
│   ├── index.html          # Головна сторінка
│   └── report.html         # Звіт аналізу
├── docs/                   # Документація методики
└── requirements.txt
```

---

## API

| Метод | Ендпоінт | Опис |
|---|---|---|
| `POST` | `/api/add-url` | Додати джерело за URL |
| `POST` | `/api/add-text` | Додати plain text |
| `POST` | `/api/add-html` | Додати HTML (автоочистка) |
| `POST` | `/api/upload` | Завантажити файл |
| `POST` | `/api/fetch-rss` | Отримати RSS/Atom стрічку |
| `POST` | `/api/fetch-telegram` | Скрейпити Telegram канал |
| `POST` | `/api/search-news` | Пошук у Google News RSS |
| `POST` | `/api/analyze` | Запустити аналіз |
| `GET`  | `/api/export/daily-form` | Форма щоденного моніторингу |
| `DELETE` | `/api/source/<id>` | Видалити джерело |
| `POST` | `/api/clear` | Очистити всі джерела |

---

## Методологічні обмеження

- **Мінімальний обсяг тексту**: надійна атрибуція за Delta потребує ~2 500–5 000 слів на джерело (Eder 2015); нижче 500 слів результат лише орієнтовний. На бенчмарку ELTeC-ukr при 500 словах знаходиться 1–12 % пар спільного автора, при 5 000 — 31–51 % за ≈ 1 % хибних спрацювань (`benchmarks/README.md`). Тому дописи одного каналу агрегуються в один документ.
- **Автоматичний поріг** відкалібровано для 100 найчастотніших слів (MFW = 100); для іншої кількості ознак, змішаних мов, функціональних слів чи n-грам поріг задається вручну (типово 0,8).
- **Одномовний корпус**: стилометричний компонент порівнює *стиль*, а не зміст — змішування мовних сімей (кирилиця + латиниця) знижує достовірність.
- **Відкриті джерела**: застосунок працює виключно з публічно доступними матеріалами.

---

## Наукова база

- Burrows, J. (2002). *Delta: A measure of stylistic difference and a guide to likely authorship*. Literary and Linguistic Computing, 17(3).
- Eder, M., Rybicki, J., Kestemont, M. (2016). *Stylometry with R: A package for computational text analysis*. R Journal, 8(1).
- Kestemont, M. (2014). *Function words in authorship attribution*. EACL Workshop on Language Technology for Digital Humanities.
- Eder, M. (2015). *Does size matter? Authorship attribution, small samples, big problem*. Digital Scholarship in the Humanities, 30(2), 167–182.
- Smith, P. W. H., Aldridge, W. (2011). *Improving authorship attribution: Optimizing Burrows' Delta method*. Journal of Quantitative Linguistics, 18(1), 63–88.
- Evert, S. et al. (2017). *Understanding and explaining Delta measures for authorship attribution*. Digital Scholarship in the Humanities, 32(suppl. 2), ii4–ii16.
- Yesypenko, D., Nazarenko, M. (2021). *ELTeC-ukr: Ukrainian novel collection* (v0.5.0). Zenodo. https://doi.org/10.5281/zenodo.4662731
- Наказ Міністерства оборони України № 46 «Методика НУЗРКС».

---

## Автор

Шерстюк Євген Іванович  
Ад'юнкт кафедри, Національний університет оборони України  
Спеціальність 126 — Інформаційні системи та технології
