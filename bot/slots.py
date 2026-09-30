"""Свободные окна: рабочие часы минус перерывы, занятые записи и слишком близкое время."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .config import Config


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def free_slots(cfg: Config, day: date, minutes: int, busy: list[tuple[datetime, datetime]], now: datetime) -> list[datetime]:
    """Начала свободных окон на день для услуги длительностью minutes. busy — занятые интервалы (aware datetime)."""
    wd = cfg.week.get(day.weekday())
    if wd is None or day.isoformat() in cfg.days_off:
        return []
    tz = cfg.tz
    start = datetime.combine(day, wd.start, tz)
    end = datetime.combine(day, wd.end, tz)
    breaks = [(datetime.combine(day, a, tz), datetime.combine(day, b, tz)) for a, b in wd.breaks]
    earliest = now + timedelta(minutes=cfg.min_lead_minutes)
    step = timedelta(minutes=cfg.slot_step)
    length = timedelta(minutes=minutes)
    out = []
    t = start
    while t + length <= end:
        t_end = t + length
        if t >= earliest and not any(_overlaps(t, t_end, a, b) for a, b in breaks + busy):
            out.append(t)
        t += step
    return out


def days_with_slots(cfg: Config, minutes: int, busy: list[tuple[datetime, datetime]], now: datetime) -> list[date]:
    today = now.astimezone(cfg.tz).date()
    return [d for d in (today + timedelta(days=i) for i in range(cfg.days_ahead))
            if free_slots(cfg, d, minutes, busy, now)]


def is_free(cfg: Config, start: datetime, minutes: int, busy: list[tuple[datetime, datetime]], now: datetime) -> bool:
    """Повторная проверка перед записью: окно всё ещё свободно (кто-то мог занять его раньше)."""
    return start in free_slots(cfg, start.astimezone(cfg.tz).date(), minutes, busy, now)


RU_DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
RU_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def human_day(d: date) -> str:
    return f"{RU_DAYS[d.weekday()]}, {d.day} {RU_MONTHS[d.month - 1]}"


def human_dt(dt: datetime, cfg: Config) -> str:
    dt = dt.astimezone(cfg.tz)
    return f"{human_day(dt.date())} в {dt:%H:%M}"
