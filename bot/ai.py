"""Ответы на вопросы клиентов через ИИ (любой OpenAI-совместимый API: OpenRouter, YandexGPT-прокси, GigaChat-прокси).
Ассистент знает только то, что написано в config.yaml, и не выдумывает цены и свободное время."""

from __future__ import annotations

import logging

import httpx

from .config import Config
from .slots import RU_DAYS

log = logging.getLogger("bot")


def knowledge(cfg: Config) -> str:
    services = "\n".join(f"- {s.name}: {s.price} ₽, {s.minutes} мин" + (f" — {s.description}" if s.description else "")
                         for s in cfg.services)
    schedule = []
    for i in range(7):
        d = cfg.week.get(i)
        schedule.append(f"{RU_DAYS[i]}: " + (f"{d.start:%H:%M}–{d.end:%H:%M}" if d else "выходной"))
    return (f"Название: {cfg.business}\nМастер: {cfg.master}\nАдрес: {cfg.address}\nКак добраться: {cfg.how_to_get}\n"
            f"Телефон: {cfg.phone}\nУслуги и цены:\n{services}\nГрафик: " + "; ".join(schedule) + f"\n\nЧастые вопросы:\n{cfg.faq}")


def system_prompt(cfg: Config) -> str:
    return ("Ты — вежливый администратор, отвечаешь клиентам в Telegram коротко (1–4 предложения), по-русски, на «вы». "
            "Отвечай только по фактам ниже. Не придумывай цены, скидки, свободное время и услуги, которых нет в списке. "
            "Если ответа нет в данных — скажи, что уточнишь у мастера. Для записи предлагай нажать кнопку «Записаться» — "
            "свободное время видно только там.\n\n" + knowledge(cfg))


async def answer(cfg: Config, key: str, base_url: str, model: str, question: str) -> str | None:
    """Ответ ИИ или None, если ИИ не настроен или недоступен (тогда вопрос уходит мастеру)."""
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(f"{base_url}/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={
                "model": model, "max_tokens": 300, "temperature": 0.2,
                "messages": [{"role": "system", "content": system_prompt(cfg)}, {"role": "user", "content": question[:1000]}],
            })
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        return text or None
    except Exception as e:  # сеть, лимиты, неверный ключ — не роняем бота
        log.warning("ИИ не ответил: %s", e)
        return None
