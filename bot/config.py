"""Настройки бота: услуги, график, адрес и тексты берутся из config.yaml — под нового мастера меняется только он."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from zoneinfo import ZoneInfo

import yaml


@dataclass(frozen=True)
class Service:
    name: str
    minutes: int
    price: int
    description: str = ""


@dataclass(frozen=True)
class Day:
    start: time
    end: time
    breaks: tuple[tuple[time, time], ...] = ()


@dataclass
class Config:
    business: str
    master: str
    services: list[Service]
    # 0 = понедельник … 6 = воскресенье; None — выходной
    week: dict[int, Day | None]
    address: str = ""
    how_to_get: str = ""
    phone: str = ""
    faq: str = ""
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("Europe/Moscow"))
    slot_step: int = 30
    days_ahead: int = 14
    min_lead_minutes: int = 60
    cancel_before_hours: int = 3
    reminders_hours: tuple[int, ...] = (24, 2)
    days_off: tuple[str, ...] = ()          # отдельные выходные «ГГГГ-ММ-ДД»
    demo: bool = False                      # демо-режим: кнопка «Хочу такого бота»
    demo_contact: str = ""


def _t(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def load_config(path: str) -> Config:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    services = [Service(s["name"], int(s["minutes"]), int(s["price"]), s.get("description", "")) for s in raw["services"]]
    if not services:
        raise ValueError("В config.yaml нет ни одной услуги")
    week: dict[int, Day | None] = {}
    for i, key in enumerate(WEEKDAYS):
        d = (raw.get("schedule") or {}).get(key)
        if not d:
            week[i] = None
            continue
        breaks = tuple((_t(a), _t(b)) for a, b in (x.split("-") for x in d.get("breaks", [])))
        start, end = d["hours"].split("-")
        week[i] = Day(_t(start), _t(end), breaks)
    return Config(
        business=raw["business"], master=raw.get("master", ""), services=services, week=week,
        address=raw.get("address", ""), how_to_get=raw.get("how_to_get", ""), phone=raw.get("phone", ""),
        faq=raw.get("faq", ""), tz=ZoneInfo(raw.get("timezone", "Europe/Moscow")),
        slot_step=int(raw.get("slot_step_minutes", 30)), days_ahead=int(raw.get("days_ahead", 14)),
        min_lead_minutes=int(raw.get("min_lead_minutes", 60)), cancel_before_hours=int(raw.get("cancel_before_hours", 3)),
        reminders_hours=tuple(int(x) for x in raw.get("reminders_hours", [24, 2])),
        days_off=tuple(str(x) for x in raw.get("days_off", [])),
        demo=bool(raw.get("demo", False)), demo_contact=raw.get("demo_contact", ""),
    )


@dataclass
class Env:
    bot_token: str
    admin_ids: tuple[int, ...]
    config_path: str
    db_path: str
    ai_key: str
    ai_base_url: str
    ai_model: str


def load_env() -> Env:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Не задан BOT_TOKEN — токен бота от @BotFather (в файле .env)")
    admins = tuple(int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x)
    return Env(
        bot_token=token, admin_ids=admins,
        config_path=os.environ.get("CONFIG_PATH", "config.yaml"),
        db_path=os.environ.get("DB_PATH", "bookings.sqlite3"),
        ai_key=os.environ.get("AI_API_KEY", "").strip(),
        ai_base_url=os.environ.get("AI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
        ai_model=os.environ.get("AI_MODEL", "openrouter/free"),
    )
