from datetime import date, datetime, timedelta

import pytest

from bot.ai import system_prompt
from bot.config import load_config
from bot.db import DB
from bot.slots import days_with_slots, free_slots, human_dt, is_free

CFG = load_config("config.example.yaml")
TZ = CFG.tz
MON = date(2026, 10, 5)  # понедельник


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)


EARLY = at(MON, 0) - timedelta(days=1)  # «сейчас» — накануне, чтобы не мешало min_lead


def test_config_loaded():
    assert CFG.services[0].minutes == 120 and CFG.week[6] is None and CFG.week[0].breaks


def test_working_day_grid_respects_break_and_end():
    slots = free_slots(CFG, MON, 60, [], EARLY)
    times = [f"{t:%H:%M}" for t in slots]
    assert times[0] == "10:00" and times[-1] == "19:00"
    assert "13:30" not in times and "14:00" not in times and "14:30" not in times and "15:00" in times


def test_long_service_does_not_cross_break_or_close():
    times = [f"{t:%H:%M}" for t in free_slots(CFG, MON, 180, [], EARLY)]
    assert "11:00" in times and "11:30" not in times  # 11:30+3ч залезает на перерыв
    assert "17:00" in times and "17:30" not in times  # позже — не успевает до 20:00


def test_day_off_and_sunday():
    assert free_slots(CFG, MON + timedelta(days=6), 60, [], EARLY) == []  # воскресенье


def test_busy_slots_excluded():
    busy = [(at(MON, 12), at(MON, 14))]
    times = [f"{t:%H:%M}" for t in free_slots(CFG, MON, 60, busy, EARLY)]
    assert "11:00" in times and "11:30" not in times and "12:00" not in times and "13:00" not in times


def test_min_lead_time():
    now = at(MON, 10, 10)
    times = [f"{t:%H:%M}" for t in free_slots(CFG, MON, 60, [], now)]
    assert times[0] == "11:30"  # не раньше чем через 60 минут, по сетке 30 минут


def test_days_with_slots_skips_sunday():
    days = days_with_slots(CFG, 60, [], at(MON, 9))
    assert MON in days and all(d.weekday() != 6 for d in days) and len(days) <= CFG.days_ahead


def test_is_free_rechecks_race():
    busy = [(at(MON, 12), at(MON, 13))]
    assert is_free(CFG, at(MON, 11), 60, busy, EARLY)
    assert not is_free(CFG, at(MON, 12), 60, busy, EARLY)
    assert not is_free(CFG, at(MON, 11, 15), 60, [], EARLY)  # не по сетке


def test_db_roundtrip_cancel_and_reminders(tmp_path):
    db = DB(str(tmp_path / "b.sqlite3"))
    b = db.add(1, "ivan", "Иван", "+79000000000", "Маникюр с покрытием", 2000, at(MON, 12), 120)
    assert db.busy(at(MON, 0), at(MON, 23)) == [(at(MON, 12), at(MON, 14))]
    assert [x.id for x in db.upcoming_for(1, EARLY)] == [b.id]
    now = at(MON, 12) - timedelta(hours=20)
    assert [x.id for x in db.due_reminders(now, 24)] == [b.id]
    assert db.due_reminders(now, 2) == []
    db.mark_reminded(b.id, 24)
    assert db.due_reminders(now, 24) == []
    db.cancel(b.id)
    assert db.busy(at(MON, 0), at(MON, 23)) == [] and db.upcoming_for(1, EARLY) == []


def test_human_format():
    assert human_dt(at(MON, 12), CFG) == "пн, 5 октября в 12:00"


def test_ai_prompt_contains_facts():
    p = system_prompt(CFG)
    assert "2000 ₽" in p and "Не придумывай цены" in p and "вс: выходной" in p
