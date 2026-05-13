# DIMS — Настанови для Claude Code

## Git-воркфлоу (ОБОВ'ЯЗКОВО)

Гілка `main` захищена. **Ніколи не комітити напряму в `main`.**

### Алгоритм кожної сесії

1. **Перевір поточну гілку** перед будь-якими змінами:
   ```bash
   git branch --show-current
   git status
   ```

2. **Якщо ти на `main` — одразу створи feature-гілку:**
   ```bash
   git checkout -b feature/<коротка-назва>
   # Приклади:
   # feature/telegram-merge
   # feature/export-fix
   # feature/ui-cleanup
   ```

3. **Роби зміни і комітить у feature-гілці.**

4. **Пуш feature-гілки:**
   ```bash
   git push -u origin feature/<назва>
   ```

5. **Створи PR через `/opt/homebrew/bin/gh`:**
   ```bash
   /opt/homebrew/bin/gh pr create --title "..." --body "..."
   ```
   > `gh` є за шляхом `/opt/homebrew/bin/gh`, але НЕ в $PATH шеллу Claude.

6. **Ніколи не використовуй `git push origin main` напряму** — буде відхилено.

---

## Preview-сервер

Файли редагуються в `/Users/odin/Desktop/Стилометрія/`.
Preview працює з `/tmp/dims_project/` (TCC-обмеження macOS).

**Після будь-яких змін — синхронізувати:**
```bash
cp "/Users/odin/Desktop/Стилометрія/app.py" /tmp/dims_project/
cp "/Users/odin/Desktop/Стилометрія/templates/"* /tmp/dims_project/templates/
cp "/Users/odin/Desktop/Стилометрія/static/"* /tmp/dims_project/static/
cp "/Users/odin/Desktop/Стилометрія/core/"*.py /tmp/dims_project/core/
```

Launch config: `.claude/launch.json` → `/usr/bin/python3 /tmp/stylometry_preview/run.py`

---

## Проект

**DIMS** — «Удосконалена методика моніторингу інформації у відкритих джерелах із застосуванням стилометричного методу» (дисертація Шерстюка Є.І., НУОУ, спеціальність 126).

### Ключові файли
| Файл | Призначення |
|---|---|
| `app.py` | Flask-сервер, всі API-ендпоінти |
| `core/analysis.py` | Burrows Delta, detect_script, DIMS-оцінки |
| `core/monitoring_forms.py` | Форма щоденного моніторингу |
| `static/app.js` | Весь фронтенд JS |
| `static/style.css` | Стилі |
| `templates/index.html` | Головна сторінка |
| `templates/report.html` | Звіт аналізу |

### Формула DIMS
```
R_DIMS = w1*I_content + w2*I_coord + w3*I_dynamics + w4*I_impact + w5*I_source
```
Грейди: F → B → S → SS → SSS (за Наказом МО України № 46).
