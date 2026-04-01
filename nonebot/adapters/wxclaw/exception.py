from typing_extensions import override

from nonebot.exception import (
    ActionFailed as BaseActionFailed,
    AdapterException,
    ApiNotAvailable as BaseApiNotAvailable,
    NetworkError as BaseNetworkError,
)


class WxClawAdapterException(AdapterException):
    def __init__(self, *args: object) -> None:
        super().__init__("WxClaw", *args)


class ApiNotAvailable(WxClawAdapterException, BaseApiNotAvailable):
    pass


class NetworkError(WxClawAdapterException, BaseNetworkError):
    pass


class ActionFailed(WxClawAdapterException, BaseActionFailed):
    def __init__(
        self,
        *,
        ret: int | None = None,
        errcode: int | None = None,
        errmsg: str | None = None,
    ) -> None:
        self.ret = ret
        self.errcode = errcode
        self.errmsg = errmsg

    @override
    def __repr__(self) -> str:
        return (
            f"ActionFailed(ret={self.ret}, errcode={self.errcode},"
            f" errmsg={self.errmsg!r})"
        )


class SessionExpiredError(ActionFailed):
    pass
