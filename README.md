# ClubStaffBot
MVP system for a sports club based on Telegram.
The system solves four main tasks:
- tracking athletes;
- tracking subscriptions;
- tracking schedules and attendance;
- automating the work of the administrator and coach.

The main user interface is a Telegram Bot.
For scenarios involving QR scanning and more complex UI, a Telegram Mini App is used.
The architecture is built from the outset with clear layer boundaries, following the principles of Clean Architecture, but without excessive DDD and enterprise overengineering.

## Configuration

Create a local environment file and replace every placeholder:

```bash
cp .env.example .env
```

Required Telegram values:

- `TELEGRAM_BOT_TOKEN` — token issued by BotFather;
- `TELEGRAM_OWNER_ID` — numeric Telegram ID of the bot owner.

Never commit `.env` or print the bot token in logs.

## Development run

Start PostgreSQL and Redis:

```bash
docker compose up -d postgres redis
```

Apply migrations:

```bash
alembic upgrade head
```

Run the API and bot in separate terminals:

```bash
PYTHONPATH=src uvicorn entrypoints.api:create_app --factory --reload
PYTHONPATH=src python -m entrypoints.bot
```

### Development reception invite and QR

After applying migrations, create the invite and QR in one command:

```bash
PYTHONPATH=src python -m entrypoints.create_dev_invite \
  --bot-username <bot_username>
```

The command stores only the SHA-256 token hash, prints the deep link once, and
writes the QR image to `static/reception-invite.png`. The generated `static/`
directory is ignored by Git and excluded from the Docker build context. The QR
contains the raw invite token, so treat the generated file as a registration
credential and expose it only at reception.

## Production run

The current MVP production-like deployment uses Docker Compose. On the target
host, create `.env` with production credentials and restrict access to it.

Build the application image:

```bash
docker compose build
```

Apply migrations from the same immutable image that will run the application:

```bash
docker compose run --rm api alembic upgrade head
```

Start the services in the background and verify their state:

```bash
docker compose up -d
docker compose ps
```

Only one bot polling process should run for the configured Telegram bot token.
Database backups, host firewall rules, secret delivery and TLS termination are
deployment responsibilities outside this repository.
