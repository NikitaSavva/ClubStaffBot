from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka, inject

from application.identity.errors import (
    AdministratorPermissionRequiredError,
    AthletePermissionRequiredError,
    AthleteProfileNotFoundError,
    TrainerPermissionRequiredError,
    UserNotFoundError,
)
from application.training_sessions import (
    GetCurrentWeekScheduleInteractor,
    GetCurrentWeekScheduleQuery,
)
from domain.identity import SystemRoleCode
from presentation.telegram.presenters.menu import RolePanel
from presentation.telegram.presenters.schedules import (
    ADMINISTRATIVE_PERMISSION_DENIED_TEXT,
    ATHLETE_PERMISSION_DENIED_TEXT,
    TRAINER_PERMISSION_DENIED_TEXT,
    build_athlete_profile_not_found_screen,
    build_permission_denied_screen,
    build_schedule_screen,
)
from presentation.telegram.screen import RenderMode, TelegramScreenRenderer
from presentation.telegram.ui_context import (
    NavigationContext,
    RootScreen,
    clear_flow_context,
    get_navigation_context,
    set_navigation_context,
)

ATHLETE_SCHEDULE_ACTION = "athlete.schedule"
TRAINER_SCHEDULE_ACTION = "trainer.schedule"
ADMINISTRATIVE_SCHEDULE_ACTION = "administrator.schedule"


@inject
async def handle_current_week_schedule(
    callback: CallbackQuery,
    state: FSMContext,
    interactor: FromDishka[GetCurrentWeekScheduleInteractor],
    renderer: FromDishka[TelegramScreenRenderer],
) -> None:
    message = callback.message
    if not isinstance(message, Message):
        return

    selected_role = await _selected_role(callback.data, state)
    if selected_role is None:
        return

    await clear_flow_context(state)
    await set_navigation_context(
        state,
        NavigationContext(
            root_screen=RootScreen.ROLE_PANEL,
            active_role=_role_panel(selected_role).value,
        ),
    )
    try:
        result = await interactor(
            GetCurrentWeekScheduleQuery(
                actor_telegram_id=callback.from_user.id,
                selected_role=selected_role,
            )
        )
    except AthleteProfileNotFoundError:
        screen = build_athlete_profile_not_found_screen()
    except AthletePermissionRequiredError:
        screen = build_permission_denied_screen(
            ATHLETE_PERMISSION_DENIED_TEXT
        )
    except TrainerPermissionRequiredError:
        screen = build_permission_denied_screen(
            TRAINER_PERMISSION_DENIED_TEXT
        )
    except AdministratorPermissionRequiredError:
        screen = build_permission_denied_screen(
            ADMINISTRATIVE_PERMISSION_DENIED_TEXT
        )
    except UserNotFoundError:
        screen = build_permission_denied_screen(
            _permission_denied_text(selected_role)
        )
    else:
        screen = build_schedule_screen(result)

    await renderer.render(
        state=state,
        chat_id=message.chat.id,
        screen=screen,
        mode=RenderMode.NEW,
        editable_message=message,
    )


async def _selected_role(
    action: str | None,
    state: FSMContext,
) -> SystemRoleCode | None:
    navigation = await get_navigation_context(state)
    active_role = navigation.active_role if navigation is not None else None
    if (
        action == ATHLETE_SCHEDULE_ACTION
        and active_role == RolePanel.ATHLETE.value
    ):
        return SystemRoleCode.ATHLETE
    if (
        action == TRAINER_SCHEDULE_ACTION
        and active_role == RolePanel.TRAINER.value
    ):
        return SystemRoleCode.TRAINER
    if action == ADMINISTRATIVE_SCHEDULE_ACTION:
        if active_role == RolePanel.OWNER.value:
            return SystemRoleCode.OWNER
        if active_role == RolePanel.ADMINISTRATOR.value:
            return SystemRoleCode.ADMINISTRATOR
    return None


def _role_panel(role: SystemRoleCode) -> RolePanel:
    return {
        SystemRoleCode.ATHLETE: RolePanel.ATHLETE,
        SystemRoleCode.TRAINER: RolePanel.TRAINER,
        SystemRoleCode.ADMINISTRATOR: RolePanel.ADMINISTRATOR,
        SystemRoleCode.OWNER: RolePanel.OWNER,
    }[role]


def _permission_denied_text(role: SystemRoleCode) -> str:
    if role is SystemRoleCode.ATHLETE:
        return ATHLETE_PERMISSION_DENIED_TEXT
    if role is SystemRoleCode.TRAINER:
        return TRAINER_PERMISSION_DENIED_TEXT
    return ADMINISTRATIVE_PERMISSION_DENIED_TEXT


def create_schedule_router() -> Router:
    router = Router(name=__name__)
    router.callback_query.register(
        handle_current_week_schedule,
        F.data.in_(
            {
                ATHLETE_SCHEDULE_ACTION,
                TRAINER_SCHEDULE_ACTION,
                ADMINISTRATIVE_SCHEDULE_ACTION,
            }
        ),
    )
    return router
