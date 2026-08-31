from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka, inject

from application.identity.errors import (
    AthletePermissionRequiredError,
    AthleteProfileNotFoundError,
    UserNotFoundError,
)
from application.subscriptions import (
    GetMySubscriptionInteractor,
    GetMySubscriptionQuery,
)
from presentation.telegram.presenters.menu import RolePanel
from presentation.telegram.presenters.subscriptions import (
    build_athlete_permission_denied_screen,
    build_athlete_profile_not_found_screen,
    build_my_subscription_screen,
)
from presentation.telegram.screen import RenderMode, TelegramScreenRenderer
from presentation.telegram.ui_context import (
    NavigationContext,
    RootScreen,
    clear_flow_context,
    set_navigation_context,
)

MY_SUBSCRIPTION_ACTION = "athlete.my_subscription"


@inject
async def handle_my_subscription(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[GetMySubscriptionInteractor],
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
            GetMySubscriptionQuery(
                actor_telegram_id=callback.from_user.id,
            )
        )
    except AthleteProfileNotFoundError:
        screen = build_athlete_profile_not_found_screen()
    except (AthletePermissionRequiredError, UserNotFoundError):
        screen = build_athlete_permission_denied_screen()
    else:
        screen = build_my_subscription_screen(result)

    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=screen,
        mode=RenderMode.NEW,
        editable_message=message,
    )


def create_my_subscription_router() -> Router:
    router = Router(name=__name__)
    router.callback_query.register(
        handle_my_subscription,
        F.data == MY_SUBSCRIPTION_ACTION,
    )
    return router
