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

## Development reception invite

After applying the database migrations, create a development-only reception invite with:

```bash
PYTHONPATH=src python -m entrypoints.create_dev_invite
```

Pass `--bot-username <username>` to print a ready Telegram deep link instead of the raw token. The command stores only the SHA-256 token hash and displays the raw token or link once.
