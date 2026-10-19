# Changelog

## [2026-10-19] - Переход с Twitter на Telegram

### Changed
- Заменена публикация в Twitter/X API на Telegram-канал:
  - Создан скрипт `stoneage_telegram.py` для загрузки и редактирования видео в канале.
  - В `run_stoneage.sh` вызов `stoneage_tweeter.py` заменен на `stoneage_telegram.py`.
  - В `.env` добавлены `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`.
  - Добавлено локальное сохранение состояния в `telegram_state.json` (ID редактируемого сообщения).
- Механика обновления: скрипт вызывает `editMessageMedia` для обновления существующего поста в канале. При устаревании или ошибке редактирования выполняется удаление старого и публикация нового без звука (`disable_notification=True`).
- Включен фоновый планировщик LaunchAgent (`com.stoneage.daily.plist`) на регулярный запуск в 9:01 и 14:31 / 15:03 EST.

### What to verify
- Зайти в канал [@vadimkassetest1](https://t.me/vadimkassetest1) в Telegram.
- Убедиться, что опубликован единственный пост с видео и ценами Brent/бензин.
- При последующих запусках по расписанию пост обновляется на месте без новых звуковых уведомлений.
