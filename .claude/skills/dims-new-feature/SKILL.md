---
name: dims-new-feature
description: Start a new feature branch following the DIMS git workflow — switch from main, pull latest, create feature/<name>. Use when starting any new code change. Argument is the short branch name (e.g. "telegram-merge", "export-fix"). Trigger — "нова фіча", "start feature", "feature branch".
disable-model-invocation: true
---

# DIMS — new feature branch

Гілка `main` захищена. Кожна зміна йде через `feature/*` → PR.

## Що робити

1. Прийми argument (`$ARGUMENTS`) — коротка назва без префіксу `feature/`.
2. Виконай:

```bash
NAME="$ARGUMENTS"
if [ -z "$NAME" ]; then
  echo "Помилка: вкажи назву гілки. Приклад: /dims-new-feature telegram-merge"
  exit 1
fi

# Не на main? Спитати чи зливати.
CURRENT=$(git branch --show-current)
if [ "$CURRENT" != "main" ]; then
  echo "⚠️  Поточна гілка: $CURRENT (не main). Все одно створити feature/$NAME від main?"
  exit 0
fi

git checkout main && \
git pull origin main && \
git checkout -b "feature/$NAME" && \
echo "✓ Створено feature/$NAME від актуального main"
```

3. Після завершення роботи:
   - `git add <files>`
   - `git commit -m "..."`
   - `git push -u origin feature/$NAME`
   - `/opt/homebrew/bin/gh pr create --title "..." --body "..."`
     (токен бери з `gh auth login` / env; **ніколи не вписуй у файл**)
