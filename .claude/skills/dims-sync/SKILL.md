---
name: dims-sync
description: Sync edited files from /Users/odin/Desktop/Стилометрія to /tmp/dims_project so the preview server (port 5001) picks them up. Use after editing app.py, templates/*, static/*, or core/*.py. Triggers — "синхронізуй", "sync preview", "перезалити в /tmp", "оновити preview-сервер".
---

# DIMS sync

Через TCC-обмеження macOS preview-сервер працює з `/tmp/dims_project/`, а редагування — у `/Users/odin/Desktop/Стилометрія/`. Після будь-якої правки потрібно скопіювати файли.

## Виконати

```bash
SRC="/Users/odin/Desktop/Стилометрія"
DST="/tmp/dims_project"

mkdir -p "$DST/templates" "$DST/static" "$DST/core"

cp "$SRC/app.py" "$DST/" 2>/dev/null
cp "$SRC/templates/"*.html "$DST/templates/" 2>/dev/null
cp "$SRC/static/"* "$DST/static/" 2>/dev/null
cp "$SRC/core/"*.py "$DST/core/" 2>/dev/null

echo "✓ Synced to $DST"
ls -la "$DST/templates/" "$DST/static/" | head -20
```

## Після синку

Якщо preview-сервер запущений з `TEMPLATES_AUTO_RELOAD=True`, Flask підхопить шаблони автоматично.
Для змін у Python-коді (`app.py`, `core/*.py`) — рестартуй сервер.

## Після перезавантаження (інтерфейс «без стилів»)

macOS чистить `/tmp` при ребуті → зникають і копія проєкту, і лоунчер
`run.py`, а панель показує сирий `index.html` без CSS. Відновити одним кроком:

```bash
bash .claude/restore_preview.sh
```

Скрипт пересинхронізує `/tmp/dims_project` і відтворить
`/tmp/stylometry_preview/run.py`. Далі запустити сервер через
`preview_start "Стилометрія (Flask)"`. Це стосується **лише локального
прев'ю** — деплой на Render не залежить від `/tmp`.
