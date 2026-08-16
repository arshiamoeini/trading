from __future__ import annotations

import pytest
from pydantic import ValidationError

from option_platform.config import Settings

pytestmark = pytest.mark.unit


def test_live_trading_cannot_be_enabled() -> None:
    with pytest.raises(ValidationError):
        Settings(live_trading_enabled=True)
