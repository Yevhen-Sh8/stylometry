---
name: dims-deploy-check
description: Pre/post-deploy checklist for the DIMS app on Render — verify DIMS_DATA_DIR + persistent disk, /healthz, WEB_CONCURRENCY, monitoring cron. Use before shipping a release or after a Render deploy to confirm it is healthy. Trigger — "deploy check", "перевір деплой", "render checklist", "готовність до деплою".
disable-model-invocation: true
---

# DIMS deploy check

Чекліст і автоперевірка деплою на Render. Викликати **перед** мерджем у main та **після** деплою.

## Pre-deploy (перед мерджем)

- [ ] `deploy-config-reviewer` (subagent) — конфіги узгоджені
- [ ] CI зелений АБО червоні чеки лише від Cloudflare (їх ігноруємо — не наш рантайм)
- [ ] У **Render → Environment** задано:
  - `DIMS_DATA_DIR=/var/data`  ← інакше SQLite-стан і журнал скидатимуться
  - `PORT=10000`, `WEB_CONCURRENCY=1`, `WEB_TIMEOUT=180`, `MPLCONFIGDIR=/tmp/matplotlib`
  - `MONITOR_TOKEN=<секрет>` (якщо моніторинг-cron захищений)
- [ ] **Render → Disks**: диск з точкою монтування `/var/data`
- [ ] GitHub Secrets для `.github/workflows/monitoring.yml`: `MONITOR_URL`, `MONITOR_TOKEN`

## Post-deploy (після деплою) — автоперевірка

Запитати у користувача базовий URL сервісу (напр. `https://stylometry-xxxx.onrender.com`), потім:

```bash
BASE="<service-url>"   # без слешу в кінці

echo "=== /healthz ===" 
curl -fsS "$BASE/healthz" && echo " ✓" || echo " ✗ healthz FAIL"

echo "=== головна сторінка ===" 
curl -fsS -o /dev/null -w "HTTP %{http_code}\n" "$BASE/"

echo "=== monitor cron (якщо є MONITOR_TOKEN) ===" 
# curl -fsS -X POST "$BASE/api/monitor/cron" -H "X-Monitor-Token: <token>"
```

## Ключова перевірка бага, що PR #11 виправляв

Саме тут раніше падало на Render (multi-worker):
1. Додати 2 джерела (`/api/add-text` або через UI)
2. Запустити `/api/analyze`
3. Відкрити `/report` — має показати результат (не «Немає результатів»)
4. Експорт Анкети `/api/export/daily-form` — має сформувати DOCX

Якщо крок 3-4 порожній → перевір що `DIMS_DATA_DIR` вказує на спільний/постійний шлях, бачний усім воркерам.
