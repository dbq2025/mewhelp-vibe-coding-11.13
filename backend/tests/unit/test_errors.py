"""错误码与异常基类的单元测试：错误码是对前端的契约，改错就是事故。"""

import pytest

from app.core.errors import (
    CODE_FORBIDDEN,
    CODE_INVALID_PARAM,
    CODE_NOT_FOUND,
    AppError,
    ForbiddenError,
    InvalidParamError,
    NotFoundError,
    SessionBusyError,
)


def test_app_error_keeps_code_message_and_status() -> None:
    err = AppError(code=5000, message="boom", http_status=500)

    assert (err.code, err.message, err.http_status) == (5000, "boom", 500)
    assert str(err) == "boom"


@pytest.mark.parametrize(
    ("factory", "code", "status"),
    [
        (InvalidParamError, CODE_INVALID_PARAM, 400),
        (ForbiddenError, CODE_FORBIDDEN, 403),
        (NotFoundError, CODE_NOT_FOUND, 404),
        (SessionBusyError, 4009, 409),
    ],
)
def test_domain_errors_map_to_expected_code_and_status(
    factory: type[AppError], code: int, status: int
) -> None:
    err = factory()

    assert err.code == code
    assert err.http_status == status


def test_forbidden_message_does_not_leak_resource_existence() -> None:
    # 越权与不存在必须同码同文案，否则可被用来探测订单号是否存在
    assert "不存在" in ForbiddenError().message
