from pathlib import Path

from nonebug import NONEBOT_INIT_KWARGS
import pytest


def pytest_configure(config: pytest.Config) -> None:
    # Extend nonebot.adapters.__path__ to find our local source tree
    # This is needed for editable installs where nonebot.adapters is
    # a regular package (not namespace) in site-packages
    import nonebot.adapters

    project_root = Path(__file__).resolve().parent.parent
    adapters_path = str(project_root / "nonebot" / "adapters")
    if adapters_path not in nonebot.adapters.__path__:
        nonebot.adapters.__path__.insert(0, adapters_path)

    config.stash[NONEBOT_INIT_KWARGS] = {"driver": "~httpx"}
