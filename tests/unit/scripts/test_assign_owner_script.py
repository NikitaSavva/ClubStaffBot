import sys

import pytest

from application.identity import AssignOwnerResult
from application.identity.errors import (
    OwnerAlreadyAssignedError,
    RequiredSystemRoleMissingError,
    UserNotFoundError,
)
from domain.identity import SystemRoleCode
from scripts import assign_owner


def test_parser_accepts_one_positive_telegram_id() -> None:
    args = assign_owner.build_parser().parse_args(["123456789"])

    assert args.telegram_id == 123456789


@pytest.mark.parametrize("raw_value", ["0", "-1", "not-an-integer"])
def test_parser_rejects_invalid_telegram_id(raw_value: str) -> None:
    with pytest.raises(SystemExit) as error:
        assign_owner.build_parser().parse_args([raw_value])

    assert error.value.code == 2


@pytest.mark.parametrize("owner_was_assigned", [True, False])
def test_main_reports_success_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    owner_was_assigned: bool,
) -> None:
    async def successful_run(telegram_id: int) -> AssignOwnerResult:
        assert telegram_id == 123456789
        return AssignOwnerResult(
            target_user_id=101,
            owner_was_assigned=owner_was_assigned,
            current_role_codes=(SystemRoleCode.OWNER,),
        )

    monkeypatch.setattr(assign_owner, "run", successful_run)
    monkeypatch.setattr(sys, "argv", ["assign_owner", "123456789"])

    assert assign_owner.main() == 0
    output = capsys.readouterr()
    assert "OWNER" in output.out
    assert output.err == ""


@pytest.mark.parametrize(
    ("controlled_error", "expected_exit_code", "expected_message"),
    [
        (UserNotFoundError(), 2, "does not exist"),
        (RequiredSystemRoleMissingError(), 3, "system role is missing"),
        (OwnerAlreadyAssignedError(), 4, "already assigned"),
    ],
)
def test_main_maps_controlled_errors_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    controlled_error: Exception,
    expected_exit_code: int,
    expected_message: str,
) -> None:
    async def failing_run(telegram_id: int) -> AssignOwnerResult:
        del telegram_id
        raise controlled_error

    monkeypatch.setattr(assign_owner, "run", failing_run)
    monkeypatch.setattr(sys, "argv", ["assign_owner", "123456789"])

    assert assign_owner.main() == expected_exit_code
    output = capsys.readouterr()
    assert output.out == ""
    assert expected_message in output.err
    assert "Traceback" not in output.err
