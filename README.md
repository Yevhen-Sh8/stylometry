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
- **Burrows Delta** — стилометрична відстань між джерелами
- **Дендрограма** — кластеризація за стилем
- **PCA/MDS/t-SNE** — проєкція джерел у 2D
- **Теплокарта** відстаней з порогом θ_Δ
- Виявлення **підозрілих пар** (Delta < порогу)
- Автоматичне попередження про короткі тексти (< 500 слів)

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
gunicorn app:app --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-2} --timeout ${WEB_TIMEOUT:-180}
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
gunicorn app:app --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-2} --timeout ${WEB_TIMEOUT:-180}
```

---

## Структура проєкту

```
stylometry/
├── app.py                  # Flask-сервер, всі API-ендпоінти
├── core/
│   ├── analysis.py         # Burrows Delta, detect_script, DIMS-оцінки
│   ├── extractors.py       # Парсинг PDF, DOCX, RTF, HTML
│   ├── monitoring_forms.py # Форма щоденного моніторингу
│   ├── monitoring_log.py   # Журнал сесій
│   └── scraper.py          # Завантаження URL, RSS, Telegram
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

- **Мінімальний обсяг тексту**: Burrows Delta надійний при ≥ 500 слів на документ (Burrows 2002, Eder 2013). Для Telegram-постів рекомендується агрегація 15–20 постів одного каналу в один документ.
- **Одномовний корпус**: стилометричний компонент порівнює *стиль*, а не зміст — змішування мовних сімей (кирилиця + латиниця) знижує достовірність.
- **Відкриті джерела**: застосунок працює виключно з публічно доступними матеріалами.

---

## Наукова база

- Burrows, J. (2002). *Delta: A measure of stylistic difference and a guide to likely authorship*. Literary and Linguistic Computing, 17(3).
- Eder, M., Rybicki, J., Kestemont, M. (2016). *Stylometry with R: A package for computational text analysis*. R Journal, 8(1).
- Kestemont, M. (2014). *Function words in authorship attribution*. EACL Workshop on Language Technology for Digital Humanities.
- Наказ Міністерства оборони України № 46 «Методика НУЗРКС».

---

## Автор

Шерстюк Євген Іванович  
Ад'юнкт кафедри, Національний університет оборони України  
Спеціальність 126 — Інформаційні системи та технології
