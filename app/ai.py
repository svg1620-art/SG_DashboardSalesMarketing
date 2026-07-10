"""Анализ и рекомендации по запросу через Claude API.

По нажатию кнопки собирает агрегированные данные текущей страницы (они
суммируют все сделки в системе под активным фильтром), передаёт их модели
claude-opus-4-8 и возвращает краткий анализ: закономерности, аномалии,
рекомендации. Автоматически ничего не запускается.
"""
import html
import json
import re

from . import metrics

PAGE_TITLES = {
    "sources": "По источникам",
    "months": "По месяцам",
    "managers": "По менеджерам",
}

SYSTEM_PROMPT = (
    "Ты — старший аналитик отдела продаж и маркетинга сервиса "
    "DashboardSales&Marketing. Тебе дают агрегированные метрики воронки продаж "
    "(из amoCRM) по выбранному разрезу. Проанализируй их и дай КРАТКИЙ, "
    "предметный вывод строго по данным, без воды и без общих фраз. "
    "Пиши по-русски. Верни ровно три раздела в формате Markdown:\n"
    "## Закономерности\n(2–4 пункта списком)\n"
    "## Аномалии\n(2–4 пункта: что выбивается, где просадка/выброс, с цифрами)\n"
    "## Рекомендации\n(3–6 конкретных действий нумерованным списком, каждое — "
    "с опорой на цифру из данных). Не выдумывай данные, которых нет."
)


def gather_data(page: str, f: dict, config) -> dict:
    """Компактный срез метрик страницы для передачи модели."""
    if page == "sources":
        d = metrics.by_source(f)
        return {"total": _clean(d["total"]),
                "sources": [_clean(r) for r in d["rows"][:40]]}
    if page == "months":
        d = metrics.by_month(f, config)
        return {"total": _clean(d["total"]),
                "months": [_clean(r) for r in d["rows"]],
                "client_type_cards": metrics.client_type_cards(f)}
    if page == "managers":
        d = metrics.by_manager(f)
        return {"total": _clean(d["total"]),
                "managers": [_clean(r) for r in d["rows"][:40]],
                "cards": metrics.manager_cards(f)["cards"]}
    return {}


_DROP = {"raw"}


def _clean(row: dict) -> dict:
    """Убирает служебные/тяжёлые поля и приводит значения к сериализуемым."""
    out = {}
    for k, v in row.items():
        if k in _DROP:
            continue
        out[k] = v
    return out


def _filter_summary(f: dict) -> str:
    parts = []
    if f.get("date_from") or f.get("date_to"):
        parts.append(f"период {f.get('date_from')}–{f.get('date_to')}")
    if f.get("manager_id"):
        parts.append(f"менеджер #{f['manager_id']}")
    if f.get("source"):
        parts.append(f"источник {f['source']}")
    if f.get("client_type"):
        parts.append(f"тип клиента {f['client_type']}")
    return ", ".join(parts) or "весь период, без доп. фильтров"


def analyze(page: str, f: dict, config) -> str:
    """Возвращает Markdown-анализ от модели (или бросает исключение)."""
    data = gather_data(page, f, config)
    user = (
        f"Разрез: «{PAGE_TITLES.get(page, page)}». "
        f"Фильтр: {_filter_summary(f)}.\n\n"
        f"Данные (JSON):\n{json.dumps(data, ensure_ascii=False, default=str)}"
    )
    return _message(SYSTEM_PROMPT, user, config)


def _message(system: str, user: str, config) -> str:
    """Изолированный вызов Claude (патчится в тестах)."""
    import anthropic

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    kwargs = dict(
        model=config.AI_MODEL,
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    try:
        resp = client.messages.create(
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            **kwargs,
        )
    except TypeError:
        # старый SDK без thinking/output_config — минимальный вызов
        resp = client.messages.create(**kwargs)
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


# --- Безопасный минимальный Markdown → HTML для вывода ---

def render_markdown(text: str) -> str:
    lines = (text or "").split("\n")
    out, in_ul, in_ol = [], False, False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>"); in_ul = False
        if in_ol:
            out.append("</ol>"); in_ol = False

    for raw in lines:
        line = html.escape(raw.strip())
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        if not line:
            close_lists()
            continue
        if line.startswith("## "):
            close_lists()
            out.append(f"<h4>{line[3:]}</h4>")
        elif line.startswith("# "):
            close_lists()
            out.append(f"<h4>{line[2:]}</h4>")
        elif re.match(r"^(-|•)\s+", line):
            if not in_ul:
                close_lists(); out.append("<ul>"); in_ul = True
            item = re.sub(r"^(-|•)\s+", "", line)
            out.append("<li>" + item + "</li>")
        elif re.match(r"^\d+[.)]\s+", line):
            if not in_ol:
                close_lists(); out.append("<ol>"); in_ol = True
            item = re.sub(r"^\d+[.)]\s+", "", line)
            out.append("<li>" + item + "</li>")
        else:
            close_lists()
            out.append(f"<p>{line}</p>")
    close_lists()
    return "\n".join(out)
