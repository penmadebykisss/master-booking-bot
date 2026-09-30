"""Диалоги бота: запись (услуга → день → время → контакт → подтверждение), мои записи и отмена,
цены, адрес, вопросы к ИИ или мастеру, сводки записей для мастера."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, KeyboardButton, Message, ReplyKeyboardMarkup,
                           ReplyKeyboardRemove)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import ai
from .config import Config, Env
from .db import DB, Booking
from .slots import days_with_slots, free_slots, human_day, human_dt, is_free

log = logging.getLogger("bot")

BTN_BOOK, BTN_MINE, BTN_PRICES, BTN_WHERE, BTN_ASK = "📅 Записаться", "🗂 Мои записи", "💅 Услуги и цены", "📍 Как добраться", "❓ Задать вопрос"
BTN_TODAY, BTN_TOMORROW, BTN_WEEK = "📋 Сегодня", "📋 Завтра", "📋 Неделя"
BTN_DEMO = "🤖 Хочу такого бота"


class SvcCb(CallbackData, prefix="s"):
    i: int


class DayCb(CallbackData, prefix="d"):
    i: int
    d: str  # ГГГГММДД


class TimeCb(CallbackData, prefix="t"):
    i: int
    t: str  # ГГГГММДДЧЧММ


class NavCb(CallbackData, prefix="n"):
    to: str
    i: int = -1


class ConfirmCb(CallbackData, prefix="c"):
    ok: bool


class CancelCb(CallbackData, prefix="x"):
    id: int


class Booking_(StatesGroup):
    contact = State()
    confirm = State()


class Ask(StatesGroup):
    question = State()


def build_router(cfg: Config, env: Env, db: DB) -> Router:
    r = Router()
    is_admin = lambda uid: uid in env.admin_ids  # noqa: E731
    now = lambda: datetime.now(cfg.tz)  # noqa: E731

    def menu(uid: int) -> ReplyKeyboardMarkup:
        rows = [[KeyboardButton(text=BTN_BOOK), KeyboardButton(text=BTN_MINE)],
                [KeyboardButton(text=BTN_PRICES), KeyboardButton(text=BTN_WHERE)],
                [KeyboardButton(text=BTN_ASK)]]
        if cfg.demo:
            rows[2].append(KeyboardButton(text=BTN_DEMO))
        if is_admin(uid):
            rows.append([KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_TOMORROW), KeyboardButton(text=BTN_WEEK)])
        return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

    def busy_window():
        n = now()
        return db.busy(n - timedelta(days=1), n + timedelta(days=cfg.days_ahead + 1))

    def booking_line(b: Booking, with_client: bool = False) -> str:
        s = f"{human_dt(b.start, cfg)} — {b.service}"
        if with_client:
            who = b.name + (f" (@{b.username})" if b.username else "")
            s += f"\n   {who}, {b.phone}"
        return s

    async def notify_admins(bot: Bot, text: str) -> None:
        for aid in env.admin_ids:
            try:
                await bot.send_message(aid, text)
            except Exception as e:
                log.warning("Не удалось уведомить мастера %s: %s", aid, e)

    # ---------- старт и меню ----------

    @r.message(CommandStart())
    async def start(m: Message, state: FSMContext):
        await state.clear()
        hello = f"Здравствуйте! Это бот записи «{cfg.business}»"
        if cfg.master:
            hello += f", мастер — {cfg.master}"
        hello += ".\n\nЗдесь можно записаться в свободное время, посмотреть цены и свои записи или задать вопрос."
        if cfg.demo:
            hello += "\n\n🧪 Это демо: записи тестовые, ничего не случится. Попробуйте записаться — так бот будет работать у вас."
        await m.answer(hello, reply_markup=menu(m.from_user.id))

    @r.message(F.text == BTN_PRICES)
    async def prices(m: Message):
        lines = [f"• {s.name} — {s.price} ₽, {s.minutes} мин" + (f"\n  {s.description}" if s.description else "") for s in cfg.services]
        await m.answer("Услуги и цены:\n\n" + "\n".join(lines))

    @r.message(F.text == BTN_WHERE)
    async def where(m: Message):
        parts = [p for p in [f"📍 {cfg.address}" if cfg.address else "", cfg.how_to_get, f"☎️ {cfg.phone}" if cfg.phone else ""] if p]
        await m.answer("\n\n".join(parts) or "Адрес уточните у мастера.")

    @r.message(F.text == BTN_DEMO)
    async def demo(m: Message):
        await m.answer("Такой бот делается под мастера или салон за 1–2 дня: ваши услуги, цены, график, напоминания клиентам, "
                       "уведомления вам о каждой записи, ответы ИИ на частые вопросы. Можно подключить оплату и VK/MAX.\n\n"
                       f"Написать разработчику: {cfg.demo_contact}")

    # ---------- запись ----------

    @r.message(F.text == BTN_BOOK)
    async def book(m: Message, state: FSMContext):
        await state.clear()
        kb = InlineKeyboardBuilder()
        for i, s in enumerate(cfg.services):
            kb.button(text=f"{s.name} · {s.price} ₽", callback_data=SvcCb(i=i))
        kb.adjust(1)
        await m.answer("Выберите услугу:", reply_markup=kb.as_markup())

    async def show_days(c: CallbackQuery, i: int):
        s = cfg.services[i]
        days = days_with_slots(cfg, s.minutes, busy_window(), now())
        kb = InlineKeyboardBuilder()
        for d in days:
            kb.button(text=human_day(d), callback_data=DayCb(i=i, d=d.strftime("%Y%m%d")))
        kb.adjust(2)
        kb.row(InlineKeyboardButton(text="← Услуги", callback_data=NavCb(to="svc").pack()))
        text = f"{s.name} — выберите день:" if days else f"На ближайшие {cfg.days_ahead} дней свободных окон для «{s.name}» нет 😔"
        await c.message.edit_text(text, reply_markup=kb.as_markup())

    @r.callback_query(SvcCb.filter())
    async def pick_service(c: CallbackQuery, callback_data: SvcCb):
        await show_days(c, callback_data.i)
        await c.answer()

    @r.callback_query(NavCb.filter(F.to == "svc"))
    async def back_services(c: CallbackQuery):
        kb = InlineKeyboardBuilder()
        for i, s in enumerate(cfg.services):
            kb.button(text=f"{s.name} · {s.price} ₽", callback_data=SvcCb(i=i))
        kb.adjust(1)
        await c.message.edit_text("Выберите услугу:", reply_markup=kb.as_markup())
        await c.answer()

    @r.callback_query(NavCb.filter(F.to == "days"))
    async def back_days(c: CallbackQuery, callback_data: NavCb):
        await show_days(c, callback_data.i)
        await c.answer()

    @r.callback_query(DayCb.filter())
    async def pick_day(c: CallbackQuery, callback_data: DayCb):
        s = cfg.services[callback_data.i]
        d = datetime.strptime(callback_data.d, "%Y%m%d").date()
        slots = free_slots(cfg, d, s.minutes, busy_window(), now())
        kb = InlineKeyboardBuilder()
        for t in slots:
            kb.button(text=f"{t:%H:%M}", callback_data=TimeCb(i=callback_data.i, t=t.strftime("%Y%m%d%H%M")))
        kb.adjust(4)
        kb.row(InlineKeyboardButton(text="← Другой день", callback_data=NavCb(to="days", i=callback_data.i).pack()))
        text = f"{s.name}, {human_day(d)} — выберите время:" if slots else "На этот день окна уже заняли — выберите другой."
        await c.message.edit_text(text, reply_markup=kb.as_markup())
        await c.answer()

    @r.callback_query(TimeCb.filter())
    async def pick_time(c: CallbackQuery, callback_data: TimeCb, state: FSMContext):
        start = datetime.strptime(callback_data.t, "%Y%m%d%H%M").replace(tzinfo=cfg.tz)
        await state.set_state(Booking_.contact)
        await state.update_data(i=callback_data.i, t=callback_data.t)
        s = cfg.services[callback_data.i]
        await c.message.edit_text(f"{s.name}, {human_dt(start, cfg)}.")
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
                                 resize_keyboard=True, one_time_keyboard=True)
        await c.message.answer("Оставьте номер телефона для связи — нажмите кнопку ниже или напишите номер сообщением.",
                               reply_markup=kb)
        await c.answer()

    @r.message(Booking_.contact)
    async def got_contact(m: Message, state: FSMContext):
        phone = m.contact.phone_number if m.contact else (m.text or "")
        digits = re.sub(r"\D", "", phone)
        if len(digits) < 10:
            await m.answer("Похоже, это не номер телефона. Напишите номер, например +7 900 123-45-67.")
            return
        data = await state.get_data()
        s = cfg.services[data["i"]]
        start = datetime.strptime(data["t"], "%Y%m%d%H%M").replace(tzinfo=cfg.tz)
        name = (m.contact.first_name if m.contact and m.contact.first_name else m.from_user.full_name) or "Клиент"
        await state.update_data(phone=phone if phone.startswith("+") else "+" + digits if len(digits) == 11 else phone, name=name)
        await state.set_state(Booking_.confirm)
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Подтвердить", callback_data=ConfirmCb(ok=True))
        kb.button(text="✖️ Отмена", callback_data=ConfirmCb(ok=False))
        await m.answer("Проверьте запись:", reply_markup=ReplyKeyboardRemove())
        await m.answer(f"{s.name} — {s.price} ₽\n{human_dt(start, cfg)} ({s.minutes} мин)\n{name}, {phone}",
                       reply_markup=kb.as_markup())

    @r.callback_query(ConfirmCb.filter(), Booking_.confirm)
    async def confirm(c: CallbackQuery, callback_data: ConfirmCb, state: FSMContext, bot: Bot):
        data = await state.get_data()
        await state.clear()
        if not callback_data.ok:
            await c.message.edit_text("Запись отменена.")
            await c.message.answer("Чем ещё помочь?", reply_markup=menu(c.from_user.id))
            return await c.answer()
        s = cfg.services[data["i"]]
        start = datetime.strptime(data["t"], "%Y%m%d%H%M").replace(tzinfo=cfg.tz)
        if not is_free(cfg, start, s.minutes, busy_window(), now()):
            await c.message.edit_text("Увы, это время только что заняли. Выберите, пожалуйста, другое — «📅 Записаться».")
            await c.message.answer("Меню:", reply_markup=menu(c.from_user.id))
            return await c.answer()
        b = db.add(c.from_user.id, c.from_user.username or "", data["name"], data["phone"], s.name, s.price, start, s.minutes)
        # Напоминания, время которых уже прошло к моменту записи, не отправляем
        for h in cfg.reminders_hours:
            if start - now() <= timedelta(hours=h):
                db.mark_reminded(b.id, h)
        await c.message.edit_text(f"Готово! Вы записаны:\n{s.name}, {human_dt(start, cfg)}.\n\n"
                                  + (f"📍 {cfg.address}\n" if cfg.address else "")
                                  + "Напомню заранее. Отменить запись можно в «🗂 Мои записи».")
        await c.message.answer("Меню:", reply_markup=menu(c.from_user.id))
        await notify_admins(bot, "🆕 Новая запись\n" + booking_line(b, with_client=True))
        await c.answer("Записали!")

    # ---------- мои записи ----------

    @r.message(F.text == BTN_MINE)
    async def mine(m: Message):
        items = db.upcoming_for(m.from_user.id, now())
        if not items:
            return await m.answer("У вас нет предстоящих записей. Записаться — «📅 Записаться».")
        for b in items:
            kb = InlineKeyboardBuilder()
            if b.start - now() > timedelta(hours=cfg.cancel_before_hours):
                kb.button(text="Отменить запись", callback_data=CancelCb(id=b.id))
            await m.answer(booking_line(b), reply_markup=kb.as_markup() if list(kb.buttons) else None)

    @r.callback_query(CancelCb.filter())
    async def cancel(c: CallbackQuery, callback_data: CancelCb, bot: Bot):
        b = db.get(callback_data.id)
        if not b or b.user_id != c.from_user.id or b.status != "active":
            await c.message.edit_text("Эта запись уже отменена.")
            return await c.answer()
        if b.start - now() <= timedelta(hours=cfg.cancel_before_hours):
            return await c.answer(f"Отменить можно не позже чем за {cfg.cancel_before_hours} ч — позвоните мастеру: {cfg.phone}",
                                  show_alert=True)
        db.cancel(b.id)
        await c.message.edit_text("Запись отменена: " + booking_line(b))
        await notify_admins(bot, "❌ Клиент отменил запись\n" + booking_line(b, with_client=True))
        await c.answer("Отменено")

    # ---------- для мастера ----------

    async def agenda(m: Message, days_from: int, days: int, title: str):
        if not is_admin(m.from_user.id):
            return
        start = datetime.combine((now() + timedelta(days=days_from)).date(), datetime.min.time(), cfg.tz)
        items = db.between(start, start + timedelta(days=days))
        if not items:
            return await m.answer(f"{title}: записей нет.")
        await m.answer(f"{title}:\n\n" + "\n".join(booking_line(b, with_client=True) for b in items))

    @r.message(F.text == BTN_TODAY)
    @r.message(Command("today"))
    async def today(m: Message):
        await agenda(m, 0, 1, "Записи на сегодня")

    @r.message(F.text == BTN_TOMORROW)
    @r.message(Command("tomorrow"))
    async def tomorrow(m: Message):
        await agenda(m, 1, 1, "Записи на завтра")

    @r.message(F.text == BTN_WEEK)
    @r.message(Command("week"))
    async def week(m: Message):
        await agenda(m, 0, 7, "Записи на 7 дней")

    # ---------- вопросы ----------

    @r.message(F.text == BTN_ASK)
    async def ask(m: Message, state: FSMContext):
        await state.set_state(Ask.question)
        await m.answer("Напишите ваш вопрос одним сообщением.")

    async def handle_question(m: Message, bot: Bot):
        reply = await ai.answer(cfg, env.ai_key, env.ai_base_url, env.ai_model, m.text or "")
        if reply:
            await m.answer(reply, reply_markup=menu(m.from_user.id))
        else:
            await m.answer("Передал вопрос мастеру — ответят здесь в ближайшее время.", reply_markup=menu(m.from_user.id))
        who = m.from_user.full_name + (f" (@{m.from_user.username})" if m.from_user.username else f" (id {m.from_user.id})")
        await notify_admins(bot, f"❓ Вопрос от {who}:\n{m.text}" + (f"\n\n🤖 Ответ ИИ:\n{reply}" if reply else ""))

    @r.message(Ask.question, F.text)
    async def got_question(m: Message, state: FSMContext, bot: Bot):
        await state.clear()
        await handle_question(m, bot)

    @r.message(F.text)
    async def free_text(m: Message, bot: Bot):
        await handle_question(m, bot)

    return r
