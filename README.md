# Лісовий архів — Telegram-бот

Бот запам'ятовує документи з порадами для життя в лісі (PDF, DOCX, TXT) і відповідає на питання звірів, завжди вказуючи, з якого документа взято пораду.

- Вимоги, з'ясовані із замовником, і ухвалені рішення: [docs/requirements.md](docs/requirements.md)
- Архітектура: [docs/architecture.md](docs/architecture.md)

## Запуск

```bash
cp .env.example .env   # вписати TELEGRAM_BOT_TOKEN і GROQ_API_KEY
docker compose up --build
```
