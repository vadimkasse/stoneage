# Plan: Очистка проекта stoneage и архивация исходников

## Context
В проекте `/Users/vadimkasse/Projects/stoneage` накопились неиспользуемые файлы объемом ~270 МБ:
- Устаревший кэш профиля браузера Chrome `private/browser_session/` (122 МБ).
- Архивные видеоролики в `output/` (15 файлов .mp4 общим весом ~90 МБ).
- Старый скрипт `stoneage_tweeter.py` и лог `cron.log`.
- 5 файлов резервных копий `.bak`.
- Исходники графики `the StoneAge/` (52 МБ) и неиспользуемый шрифт `HomeVideo-Regular.ttf`.

## Goal
1. Удалить ненужный кэш, старые видео (оставив последнее актуальное и `latest_meta.json`), устаревший код твиттера, старый крон-лог и `.bak` файлы.
2. Переместить в папку `archive/` исходники графики (`the StoneAge/`), неиспользуемый шрифт и файлы примеров.
3. Обеспечить сохранность данных: перемещение удаляемых файлов через временную директорию `_trash/` перед финальным удалением.

## Approach
1. Создать локальную папку `_trash/` для безопасного промежуточного хранения удаляемых файлов:
   - `private/browser_session/`
   - 15 старых mp4-файлов из `output/` (сохраняем `20261027_0903_cam4554_Bloomberg_Radio.mp4` и `latest_meta.json`)
   - `stoneage_tweeter.py`
   - `cron.log`
   - `.bak` файлы: `README.md.bak`, `run_stoneage.sh.bak`, `stoneage_telegram.py.bak`, `.env.bak`, `telegram_state.json.bak`.
2. Создать папку `archive/` в корне проекта (`/Users/vadimkasse/Projects/stoneage/archive/`).
3. Переместить в `archive/`:
   - папку `the StoneAge/`
   - `HomeVideo-Regular.ttf`
   - `camera_catalog.example.csv`
   - `camera_pool.example.json`
4. Добавить `archive/` и `_trash/` в `.gitignore` (если еще не добавлены), чтобы не засорять git.
5. Проверить работоспособность генератора и скрипта Telegram (dry run).
6. Зафиксировать изменения в `CHANGELOG.md`.

## Files touched
- `private/browser_session/` (в `_trash/`)
- `output/*.mp4` (старые, в `_trash/`)
- `stoneage_tweeter.py` (в `archive/`)
- `cron.log` (в `_trash/`)
- `*.bak` (в `_trash/`)
- `the StoneAge/` (в `archive/`)
- `HomeVideo-Regular.ttf` (в `archive/`)
- `camera_catalog.example.csv` (в `archive/`)
- `camera_pool.example.json` (в `archive/`)
- `.gitignore`
- `CHANGELOG.md`

## Acceptance criteria
- [x] Все удаляемые файлы предварительно перемещены в `_trash/`.
- [x] В `output/` остались только последнее видео и `latest_meta.json`.
- [x] Исходники дизайна и неиспользуемые шрифты/шаблоны перемещены в `archive/`.
- [x] Рабочие файлы проекта (`stoneage_generator.py`, `stoneage_telegram.py`, `run_stoneage.sh`, `the_StoneAge_layer.png`, `.env`, `telegram_state.json`) не затронуты.
- [x] `CHANGELOG.md` обновлен.

## Conventions to follow
- Правило Data Safety: удаление через `_trash/`, удаление самого `_trash/` только после финального подтверждения пользователя.
- Не трогать боевые данные и рабочие шрифты (`HomeVideo-Bold.ttf`, `flintstone.ttf`).

## What we evaluate after
- Структура каталога проекта стала чистой и компактной (объем проекта уменьшится более чем в 2 раза).
- Скрипты генератора и отправщика работают штатно.
