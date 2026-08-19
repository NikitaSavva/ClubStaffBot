import argparse
import asyncio
from urllib.parse import quote

from bootstrap.config import Settings
from bootstrap.container import create_container
from bootstrap.development import create_development_invite


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a development-only reception BotInvite.",
    )
    parser.add_argument(
        "--bot-username",
        help="Optional Telegram bot username used to print a ready deep link.",
    )
    return parser


async def run(bot_username: str | None) -> str:
    # BaseSettings loads the required application configuration from environment.
    settings = Settings()  # type: ignore[call-arg]
    container = create_container(settings)
    try:
        raw_token = await create_development_invite(container)
    finally:
        await container.close()

    if bot_username:
        normalized_username = bot_username.removeprefix("@")
        encoded_token = quote(raw_token, safe="")
        return f"https://t.me/{normalized_username}?start={encoded_token}"
    return raw_token


def main() -> None:
    args = build_parser().parse_args()
    output = asyncio.run(run(args.bot_username))
    print(output)


if __name__ == "__main__":
    main()
