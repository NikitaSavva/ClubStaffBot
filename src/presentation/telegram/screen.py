import hashlib
from dataclasses import dataclass
from enum import StrEnum

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardMarkup,
    InputFile,
    InputMediaPhoto,
    Message,
)

from presentation.telegram.ui_context import (
    ActiveUiMessage,
    UiMessageKind,
    get_active_ui_message,
    set_active_ui_message,
)

logger = structlog.get_logger()


class BannerContext(StrEnum):
    ROLE_SELECTOR = "role_selector"
    ADMIN_PANEL = "admin_panel"
    TRAINER_PANEL = "trainer_panel"
    ATHLETE_PANEL = "athlete_panel"


@dataclass(frozen=True, slots=True)
class BannerFileIds:
    role_selector: str | None = None
    admin_panel: str | None = None
    trainer_panel: str | None = None
    athlete_panel: str | None = None

    def get(self, context: BannerContext) -> str | None:
        file_id = {
            BannerContext.ROLE_SELECTOR: self.role_selector,
            BannerContext.ADMIN_PANEL: self.admin_panel,
            BannerContext.TRAINER_PANEL: self.trainer_panel,
            BannerContext.ATHLETE_PANEL: self.athlete_panel,
        }[context]
        return file_id or None


@dataclass(frozen=True, slots=True)
class TelegramScreen:
    text: str
    reply_markup: InlineKeyboardMarkup | None = None
    banner: BannerContext | None = None
    media: str | InputFile | None = None
    media_key: str | None = None

    def __post_init__(self) -> None:
        if self.banner is not None and self.media is not None:
            raise ValueError("Screen cannot contain both banner and media")
        if self.media is not None and not self.media_key:
            raise ValueError("Dynamic screen media requires media_key")


@dataclass(frozen=True, slots=True)
class _ResolvedScreen:
    text: str
    reply_markup: InlineKeyboardMarkup | None
    media: str | InputFile | None
    media_key: str | None
    content_fingerprint: str
    keyboard_fingerprint: str

    @property
    def kind(self) -> UiMessageKind:
        if self.media is None:
            return UiMessageKind.TEXT
        return UiMessageKind.MEDIA


class TelegramScreenRenderer:
    def __init__(
        self,
        bot: Bot,
        banner_file_ids: BannerFileIds,
    ) -> None:
        self._bot = bot
        self._banner_file_ids = banner_file_ids

    async def render(
        self,
        *,
        state: FSMContext,
        chat_id: int,
        screen: TelegramScreen,
        editable_message: Message | None = None,
    ) -> ActiveUiMessage:
        resolved = self._resolve(screen)
        active = await get_active_ui_message(state)
        if active is None and editable_message is not None:
            active = self._active_from_message(editable_message)

        if active is None:
            return await self._send(state, chat_id, resolved)

        if active.kind is not resolved.kind:
            return await self._send(state, chat_id, resolved)

        try:
            await self._edit(active, resolved)
        except TelegramBadRequest as error:
            if not _is_message_not_modified(error):
                return await self._fallback_send(
                    state=state,
                    chat_id=chat_id,
                    active=active,
                    screen=resolved,
                    error=error,
                )
        except TelegramAPIError as error:
            return await self._fallback_send(
                state=state,
                chat_id=chat_id,
                active=active,
                screen=resolved,
                error=error,
            )

        updated = self._updated_active(active, resolved)
        await set_active_ui_message(state, updated)
        return updated

    def _resolve(self, screen: TelegramScreen) -> _ResolvedScreen:
        media = screen.media
        media_key = screen.media_key
        if screen.banner is not None:
            media = self._banner_file_ids.get(screen.banner)
            media_key = (
                f"banner:{screen.banner.value}" if media is not None else None
            )
        return _ResolvedScreen(
            text=screen.text,
            reply_markup=screen.reply_markup,
            media=media,
            media_key=media_key,
            content_fingerprint=_fingerprint(screen.text),
            keyboard_fingerprint=_keyboard_fingerprint(screen.reply_markup),
        )

    async def _edit(
        self,
        active: ActiveUiMessage,
        screen: _ResolvedScreen,
    ) -> None:
        same_content = (
            active.content_fingerprint == screen.content_fingerprint
        )
        same_keyboard = (
            active.keyboard_fingerprint == screen.keyboard_fingerprint
        )
        if same_content and same_keyboard and active.media_key == screen.media_key:
            return

        if active.kind is UiMessageKind.TEXT:
            if same_content:
                await self._bot.edit_message_reply_markup(
                    chat_id=active.chat_id,
                    message_id=active.message_id,
                    reply_markup=screen.reply_markup,
                )
                return
            await self._bot.edit_message_text(
                chat_id=active.chat_id,
                message_id=active.message_id,
                text=screen.text,
                reply_markup=screen.reply_markup,
            )
            return

        if active.media_key != screen.media_key:
            if screen.media is None:
                raise RuntimeError("Resolved media screen has no media")
            await self._bot.edit_message_media(
                chat_id=active.chat_id,
                message_id=active.message_id,
                media=InputMediaPhoto(
                    media=screen.media,
                    caption=screen.text,
                ),
                reply_markup=screen.reply_markup,
            )
            return
        if same_content:
            await self._bot.edit_message_reply_markup(
                chat_id=active.chat_id,
                message_id=active.message_id,
                reply_markup=screen.reply_markup,
            )
            return
        await self._bot.edit_message_caption(
            chat_id=active.chat_id,
            message_id=active.message_id,
            caption=screen.text,
            reply_markup=screen.reply_markup,
        )

    async def _send(
        self,
        state: FSMContext,
        chat_id: int,
        screen: _ResolvedScreen,
    ) -> ActiveUiMessage:
        if screen.media is None:
            sent = await self._bot.send_message(
                chat_id=chat_id,
                text=screen.text,
                reply_markup=screen.reply_markup,
            )
        else:
            sent = await self._bot.send_photo(
                chat_id=chat_id,
                photo=screen.media,
                caption=screen.text,
                reply_markup=screen.reply_markup,
            )
        active = ActiveUiMessage(
            chat_id=sent.chat.id,
            message_id=sent.message_id,
            kind=screen.kind,
            media_key=screen.media_key,
            content_fingerprint=screen.content_fingerprint,
            keyboard_fingerprint=screen.keyboard_fingerprint,
        )
        await set_active_ui_message(state, active)
        return active

    async def _fallback_send(
        self,
        *,
        state: FSMContext,
        chat_id: int,
        active: ActiveUiMessage,
        screen: _ResolvedScreen,
        error: TelegramAPIError,
    ) -> ActiveUiMessage:
        logger.warning(
            "telegram_screen_edit_failed",
            chat_id=active.chat_id,
            message_id=active.message_id,
            error_type=type(error).__name__,
        )
        return await self._send(state, chat_id, screen)

    @staticmethod
    def _updated_active(
        active: ActiveUiMessage,
        screen: _ResolvedScreen,
    ) -> ActiveUiMessage:
        return ActiveUiMessage(
            chat_id=active.chat_id,
            message_id=active.message_id,
            kind=screen.kind,
            media_key=screen.media_key,
            content_fingerprint=screen.content_fingerprint,
            keyboard_fingerprint=screen.keyboard_fingerprint,
        )

    @staticmethod
    def _active_from_message(message: Message) -> ActiveUiMessage:
        is_media = bool(message.photo)
        text = message.caption if is_media else message.text
        return ActiveUiMessage(
            chat_id=message.chat.id,
            message_id=message.message_id,
            kind=(UiMessageKind.MEDIA if is_media else UiMessageKind.TEXT),
            media_key=None,
            content_fingerprint=_fingerprint(text or ""),
            keyboard_fingerprint=_keyboard_fingerprint(message.reply_markup),
        )


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _keyboard_fingerprint(
    reply_markup: InlineKeyboardMarkup | None,
) -> str:
    if reply_markup is None:
        return _fingerprint("")
    return _fingerprint(
        reply_markup.model_dump_json(exclude_none=True)
    )


def _is_message_not_modified(error: TelegramBadRequest) -> bool:
    return "message is not modified" in error.message.lower()
