from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import clock


def test_today_uses_home_assistant_time_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    # Kiritimati (UTC+14) und Baker Island (UTC−12) liegen 26 Stunden auseinander.
    monkeypatch.setenv(clock.TZ_ENV_VAR, "Pacific/Kiritimati")
    east = clock.today()
    monkeypatch.setenv(clock.TZ_ENV_VAR, "Etc/GMT+12")
    west = clock.today()

    assert east == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
    assert east > west


@pytest.mark.parametrize("value", ["", "Mars/Olympus_Mons"])
def test_missing_or_unknown_zone_falls_back_to_local_time(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(clock.TZ_ENV_VAR, value)

    assert clock.local_zone() is None
    assert clock.today() == date.today()
