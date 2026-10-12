from __future__ import annotations

import importlib
import pkgutil
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import DateTime

import models
import services.reservation_engine as reservation_engine
from core.database import Base
from core.time_utils import utc_now
from services.reservation_engine import ReservationError, _guard_duplicate


for _, module_name, _ in pkgutil.iter_modules(models.__path__):
    importlib.import_module(f"models.{module_name}")


@pytest.mark.parametrize("process_timezone", ["UTC", "Pacific/Kiritimati", "America/Los_Angeles"])
def test_utc_now_is_aware_utc_regardless_of_process_timezone(monkeypatch, process_timezone):
    monkeypatch.setenv("TZ", process_timezone)

    value = utc_now()

    assert value.tzinfo is timezone.utc
    assert value.utcoffset() == timedelta(0)


def test_all_python_datetime_defaults_and_onupdates_return_aware_utc():
    checked: list[str] = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if not isinstance(column.type, DateTime) or not column.type.timezone:
                continue
            for label, generator in (("default", column.default), ("onupdate", column.onupdate)):
                if generator is None or not generator.is_callable:
                    continue
                value = generator.arg(None)
                checked.append(f"{table.name}.{column.name}.{label}")
                assert value.tzinfo is not None
                assert value.utcoffset() == timedelta(0)
    assert checked


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def first(self):
        return self.value


class _FakeSession:
    def __init__(self, value):
        self.value = value

    async def execute(self, _statement):
        return _FakeResult(self.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("age_seconds", "must_reject", "process_timezone"),
    [
        (89, True, "America/Mexico_City"),
        (89, True, "Pacific/Kiritimati"),
        (91, False, "America/Mexico_City"),
        (91, False, "Pacific/Kiritimati"),
    ],
)
async def test_duplicate_window_is_exactly_utc_and_naive_sqlite_values_are_utc(
    monkeypatch, age_seconds, must_reject, process_timezone
):
    fixed_now = datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc)
    naive_created_at = (fixed_now - timedelta(seconds=age_seconds)).replace(tzinfo=None)
    session = _FakeSession(SimpleNamespace(created_at=naive_created_at))
    monkeypatch.setenv("TZ", process_timezone)
    monkeypatch.setattr(reservation_engine, "utc_now", lambda: fixed_now)

    if must_reject:
        with pytest.raises(ReservationError) as caught:
            await _guard_duplicate(session, "clienta@example.com")
        assert caught.value.code == "duplicate"
    else:
        await _guard_duplicate(session, "clienta@example.com")
