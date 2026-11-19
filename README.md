# Learning Center Management Bot

A lightweight Telegram bot for managing a learning center. It brings students, groups, attendance, test results, and parent communication together in one place.

The bot is written in Python and stores data in a local SQLite database. It does not require a separate database server.

## Features

- Manage students, groups, teachers, schedules, and classrooms
- Record attendance, including late arrivals and excused absences
- Notify parents when a student is absent or late
- Create tests and exams, record scores, and calculate percentages and IELTS-style bands
- Compare a student's results with previous tests
- Generate attendance, at-risk student, and group reports; export CSV
- Send weekly summaries to parents
- Separate access for super admins, admins, teachers, and parents
- Maintain an audit log, database backups, and role-based data access

## Roles

- **Super admin:** manage admins, audit logs, and backups
- **Admin:** manage students, groups, teachers, and announcements
- **Teacher:** manage assigned groups, attendance, tests, and scores
- **Parent:** view only their child's attendance, schedule, and results

## Requirements

- Python (the repository uses a standard-library SQLite database)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/yaqubovmehmed/learning-center-management-bot.git
cd learning-center-management-bot
```

### 2. Install dependencies and configure the bot

**Windows**
```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env
```

**Linux / macOS**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Set at least one of `SUPERADMIN_IDS` or `BOOTSTRAP_CODE` in `.env`. Keep tokens and secrets private.

### 3. Start the bot

```bash
python main.py
```

You can also use `run.bat` on Windows or `run.sh` on Linux/macOS.

## First-time setup

1. Start the bot and send it `/start` in Telegram.
2. If `SUPERADMIN_IDS` is configured, you will enter as an administrator.
3. Otherwise, claim the first admin account with `/claim YOUR_CODE`, using the `BOOTSTRAP_CODE` from `.env`.
4. Remove the bootstrap code from `.env` after it has been used.

For the optional inline group-schedule search, enable inline mode for the bot with [@BotFather](https://t.me/BotFather)'s `/setinline` command. The bot is designed for private chats and leaves groups automatically.

## Configuration

| Variable | Purpose |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token |
| `SUPERADMIN_IDS` | Comma-separated Telegram IDs for super admins |
| `BOOTSTRAP_CODE` | Optional one-time code to claim the first admin |
| `SECRET_PEPPER` | Secret used to protect invitation links; generated if omitted |
| `DB_PATH` | SQLite path; defaults to `data/excellence.db` |
| `TIMEZONE` | Time zone; defaults to `Asia/Tashkent` |
| `DIGEST_WEEKDAY`, `DIGEST_HOUR` | Day and hour for weekly summaries |

## Daily workflow

1. Create a group and assign a teacher.
2. Add students and send parents their invitation links.
3. Mark attendance; the bot notifies parents about absences.
4. Create a test, enter scores, and publish the results.
5. Review attendance, at-risk student, and CSV reports.

## Data and backups

- Database: `data/excellence.db`
- Daily backups: `data/backups/` (kept for 14 days)
- Logs: `logs/bot.log`

Backups run daily at 03:00 while the bot is running.

## Testing

The offline smoke test does not require a Telegram token:

```bash
python tests/smoke_test.py
```

The repository's current test suite reports 61 checks. GitHub Actions runs the checks on each push.

## Docker

```bash
copy .env.example .env
# Fill in .env, then:
docker compose up -d --build
docker compose logs -f
```

The database and backups remain under `./data`.

## Security

- The bot is intended for private chats and checks roles before serving data.
- Invitation links are single-use, expire after 72 hours, and are stored in hashed form.
- Phone numbers are confirmed using Telegram's contact-sharing button.
- Important actions are written to an audit log.
- CSV exports guard against spreadsheet formula injection.
- Never commit `.env`, `data/`, or `.secret_pepper`.

## Known limitations

- Only one bot process can use a given token at a time.
- Inline mode exposes only group schedules; student and parent data are never public.
- Incomplete forms are lost if the bot restarts.
- Weekly summaries and backups run only while the bot process is active.

## License

MIT. See [LICENSE](LICENSE).
