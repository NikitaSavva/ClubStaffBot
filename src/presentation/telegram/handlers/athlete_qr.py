from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka, inject

from application.athlete_qr import (
    GetAthleteQrTokenInteractor,
    GetAthleteQrTokenQuery,
)
from application.identity.errors import (
    AthletePermissionRequiredError,
    AthleteProfileNotFoundError,
    UserNotFoundError,
)
from presentation.telegram.presenters.athlete_qr import (
    build_athlete_permission_denied_screen,
    build_athlete_profile_not_found_screen,
    build_my_qr_screen,
)
from presentation.telegram.presenters.menu import RolePanel
from presentation.telegram.qr import generate_qr_png
from presentation.telegram.screen import RenderMode, TelegramScreenRenderer
from presentation.telegram.ui_context import (
    NavigationContext,
    RootScreen,
    clear_flow_context,
    set_navigation_context,
)

MY_QR_ACTION = "athlete.my_qr"


@inject
async def handle_my_qr(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[GetAthleteQrTokenInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return

    await clear_flow_context(state)
    await set_navigation_context(
        state,
        NavigationContext(
            root_screen=RootScreen.ROLE_PANEL,
            active_role=RolePanel.ATHLETE.value,
        ),
    )
    try:
        result = await interactor(
            GetAthleteQrTokenQuery(
                actor_telegram_id=callback.from_user.id,
            )
        )
    except AthleteProfileNotFoundError:
        screen = build_athlete_profile_not_found_screen()
    except (AthletePermissionRequiredError, UserNotFoundError):
        screen = build_athlete_permission_denied_screen()
    else:
        screen = build_my_qr_screen(generate_qr_png(result.token))

    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=screen,
        mode=RenderMode.NEW,
        editable_message=message,
    )


def create_athlete_qr_router() -> Router:
    router = Router(name=__name__)
    router.callback_query.register(
        handle_my_qr,
        F.data == MY_QR_ACTION,
    )
    return router
