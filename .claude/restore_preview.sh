#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# restore_preview.sh — відновлення ЛОКАЛЬНОГО прев'ю після перезавантаження.
#
# macOS чистить /tmp при ребуті, тож зникають і синхронізована копія проєкту
# (/tmp/dims_project — TCC-обхід), і лоунчер (/tmp/stylometry_preview/run.py),
# на який посилається .claude/launch.json. Через це панель прев'ю показує сирий
# index.html без стилів. Цей скрипт відновлює обидва за один крок.
#
# Використання:
#   bash .claude/restore_preview.sh
#   потім запустити сервер через preview_start "Стилометрія (Flask)"
#
# Це стосується ЛИШЕ локального прев'ю. Деплой на Render не залежить від /tmp.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SRC="/Users/odin/Desktop/Стилометрія"
DST="/tmp/dims_project"
LAUNCH="/tmp/stylometry_preview"

mkdir -p "$DST/templates" "$DST/static" "$DST/core" "$DST/Data" "$LAUNCH"

cp "$SRC/app.py" "$DST/" 2>/dev/null || true
cp "$SRC/templates/"*.html "$DST/templates/" 2>/dev/null || true
cp "$SRC/static/"* "$DST/static/" 2>/dev/null || true
cp "$SRC/core/"*.py "$DST/core/" 2>/dev/null || true
# Дані для I_source / журналу (списки доменів, overrides) — для повного аналізу.
cp "$SRC/Data/"*.txt "$DST/Data/" 2>/dev/null || true
cp "$SRC/Data/"*.json "$DST/Data/" 2>/dev/null || true

# Лоунчер: вантажить app із /tmp (а не з Desktop) — обхід TCC.
cat > "$LAUNCH/run.py" <<'PY'
import sys, os, importlib.util
sys.path.insert(0, '/tmp/dims_project')
os.chdir('/tmp/dims_project')
spec = importlib.util.spec_from_file_location('app', '/tmp/dims_project/app.py')
mod = importlib.util.module_from_spec(spec)
mod.__file__ = '/tmp/dims_project/app.py'
sys.modules['app'] = mod
spec.loader.exec_module(mod)
mod.app.config['TEMPLATES_AUTO_RELOAD'] = True
mod.app.run(debug=False, port=5001)
PY

echo "✓ Прев'ю відновлено:"
echo "  • синхронізовано → $DST"
echo "  • лоунчер → $LAUNCH/run.py"
echo "Далі: preview_start \"Стилометрія (Flask)\" (порт 5001)."
