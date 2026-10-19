# Plan: Переход с Twitter на Telegram-канал (StoneAge)

## Context
Проект StoneAge генерирует видеоролик (59 сек) с живыми камерами VDOT, аудиопотоком радио и ценами на нефть Brent и бензин в Вирджинии.
Ранее скрипт `stoneage_tweeter.py` публиковал видео в Twitter через X API v1.1/v2, удаляя предыдущий твит, но из-за исчерпания кредитов X API (ошибка 402) постинг остановился, и фоновый агент был отключен.

## Goal
Перевести публикацию видео и данных из Twitter в Telegram-канал:
- Постинг в Telegram бесплатный и не требует оплаты API.
- Бот обновляет один закрепленный/единственный пост в канале (видео + текст).
- Механика надежна: в первую очередь используется редактирование медиа (`editMessageMedia`), а в случае превышения лимита давности Telegram — тихое удаление и отправка нового поста без звука (`disable_notification=True`).

## Approach
1. Создать модуль `stoneage_telegram.py`, заменяющий логику `stoneage_tweeter.py`.
2. В файле конфигурации `.env` добавить переменные:
   - `TELEGRAM_BOT_TOKEN` (токен от @BotFather)
   - `TELEGRAM_CHAT_ID` (ID канала или @username)
   - `TELEGRAM_MESSAGE_ID` (ID поста, который редактируется; обновляется автоматически)
3. Логика публикации:
   - Если `TELEGRAM_MESSAGE_ID` задан: попытка `editMessageMedia` (InputMediaVideo + caption).
   - Если попытка не удалась (например, сообщение удалено или истек таймаут Telegram): удалить старое (если доступно), отправить новое видео через `sendVideo` с параметром `disable_notification=True`, сохранить новый ID в `.env` или локальный стейт-файл (`state.json`).
4. Обновить оркестратор `run_stoneage.sh`: вызывать `stoneage_telegram.py` вместо `stoneage_tweeter.py`.
5. Снова включить расписание `launchd`: вернуть `com.stoneage.daily.plist.disabled` -> `com.stoneage.daily.plist` и загрузить в `launchctl`.

## Files touched
- `stoneage_telegram.py` (новый скрипт публикации в Telegram)
- `run_stoneage.sh` (замена вызова `stoneage_tweeter.py` на `stoneage_telegram.py`)
- `.env` (добавление настроек Telegram)
- `~/Library/LaunchAgents/com.stoneage.daily.plist` (реактивация задачи)
- `README.md` (обновление описания под Telegram)

## Acceptance criteria
- [x] Бот успешно отправляет сгенерированное видео с текстом котировок в указанный Telegram-канал.
- [x] При повторном запуске бот обновляет существующее сообщение (заменяет видео и текст котировок), либо тихо пересоздает его без уведомления подписчиков.
- [x] Скрипт не падает при сетевых ошибках Telegram API.
- [x] Фоновый запуск дважды в день через launchd восстановлен и работает без ошибок в `stoneage.error.log`.

## Conventions to follow
- Использовать `requests` для вызовов Telegram Bot API (без необходимости ставить тяжелые сторонние библиотеки).
- Сохранять существующую структуру форматирования текста из `stoneage_tweeter.py` (`build_tweet_text` -> `build_telegram_caption`).
- Читать метаданные из `output/latest_meta.json`.

## What we evaluate after
- Запуск `stoneage_telegram.py` вручную и проверка появления/обновления видео в целевом Telegram-канале.
- Проверка лога `~/Library/Logs/stoneage.log`.
