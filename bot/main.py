"""Запуск бота (long polling — сервер с белым IP и HTTPS не нужен) и фоновые напоминания клиентам."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import Config, load_config, load_env
from .db import DB
from .handlers import CancelCb, build_router
from .slots import human_dt

log = logging.getLogger("bot")


async def reminders(bot: Bot, cfg: Config, db: DB) -> None:
    """Раз в минуту: кому пора напомнить о записи (за 24 ч, за 2 ч — настраивается в config.yaml)."""
    while True:
        try:
            now = datetime.now(cfg.tz)
            for h in cfg.reminders_hours:
                for b in db.due_reminders(now, h):
                    kb = InlineKeyboardBuilder()
                    if (b.start - now).total_seconds() > cfg.cancel_before_hours * 3600:
                        kb.button(text="Не смогу прийти — отменить", callback_data=CancelCb(id=b.id))
                    text = (f"Напоминаю о записи: {b.service}, {human_dt(b.start, cfg)}."
                            + (f"\n📍 {cfg.address}" if cfg.address else "") + "\nЖдём вас!")
                    try:
                        await bot.send_message(b.user_id, text, reply_markup=kb.as_markup() if list(kb.buttons) else None)
                    except Exception as e:
                        log.warning("Напоминание %s не отправлено: %s", b.id, e)
                    db.mark_reminded(b.id, h)
        except Exception:
            log.exception("Ошибка в цикле напоминаний")
        await asyncio.sleep(60)


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    env = load_env()
    cfg = load_config(env.config_path)
    db = DB(env.db_path)
    bot = Bot(env.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(build_router(cfg, env, db))
    me = await bot.get_me()
    log.info("Бот @%s запущен: %s, услуг %d, мастеров для уведомлений %d, ИИ %s",
             me.username, cfg.business, len(cfg.services), len(env.admin_ids), "вкл" if env.ai_key else "выкл")
    task = asyncio.create_task(reminders(bot, cfg, db))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
