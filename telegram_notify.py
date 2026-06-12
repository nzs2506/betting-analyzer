import json
import os
import re
from pathlib import Path

import requests


RESULTS_JSON = Path(os.getenv("RESULTS_JSON", "docs/results.json"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
MAX_RECIPIENTS = 4


def split_chat_ids(raw):
    return [chat_id for chat_id in re.split(r"[\s,;]+", raw.strip()) if chat_id]


def get_update_chat_ids():
    if not BOT_TOKEN:
        return []
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
            params={"offset": -20},
            timeout=20,
        )
        response.raise_for_status()
        updates = response.json().get("result", [])
    except Exception as exc:
        print(f"Could not read Telegram updates: {exc}")
        return []

    chat_ids = []
    for update in updates:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        text = message.get("text") or ""
        chat_id = chat.get("id")
        if chat_id and text.startswith("/start"):
            chat_ids.append(str(chat_id))
    return chat_ids


def get_chat_ids():
    raw_values = [
        os.getenv("TELEGRAM_CHAT_IDS", ""),
        os.getenv("TELEGRAM_CHAT_ID", ""),
        os.getenv("TELEGRAM_CHAT_ID_1", ""),
        os.getenv("TELEGRAM_CHAT_ID_2", ""),
        os.getenv("TELEGRAM_CHAT_ID_3", ""),
        os.getenv("TELEGRAM_CHAT_ID_4", ""),
    ]
    chat_ids = []
    seen = set()
    for raw in raw_values:
        for chat_id in split_chat_ids(raw):
            if chat_id not in seen:
                chat_ids.append(chat_id)
                seen.add(chat_id)

    for chat_id in get_update_chat_ids():
        if chat_id not in seen:
            chat_ids.append(chat_id)
            seen.add(chat_id)

    return chat_ids[:MAX_RECIPIENTS]


def fmt_anomaly(item):
    league = item["league"]
    match = item["match"]
    return (
        f"<b>{league}</b>\n"
        f"{match['home']} #{match['home_pos']} ({match['home_pts']} оч.) - "
        f"{match['away']} #{match['away_pos']} ({match['away_pts']} оч.)\n"
        f"Кэфы: 1 {match['home_odds']} | X {match.get('draw_odds') or '-'} | 2 {match['away_odds']}\n"
        f"<b>{match['value_team']}</b> выше в таблице, но кэф {match['value_odds']}\n"
        f"Время: {match['time']}"
    )


def fmt_result(item):
    match = item["match"]
    settlement = match.get("settlement") or {}
    icon = settlement.get("icon", "⚪")
    label = settlement.get("label", "матч не завершен")
    score = settlement.get("score")
    roi = settlement.get("roi")

    lines = [f"{icon} <b>Результат:</b> {label}"]
    if score:
        lines.append(f"Счет: {match['home']} {score} {match['away']}")
    else:
        lines.append("Счет: пока нет")
    if roi is not None:
        lines.append(f"ROI по сигналу: {roi:+}")
    return "\n".join(lines)


def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()


def build_messages(data):
    results = data.get("results", [])
    if not results:
        return [
            (
                f"Betting Analyzer: аномалий нет.\n"
                f"Обновлено: {data.get('generated_at', '-')}"
            )
        ]

    messages = [
        f"Betting Analyzer: найдено {len(results)} аномалий\n"
        f"Обновлено: {data.get('generated_at', '-')}"
    ]
    for item in results:
        messages.append(fmt_anomaly(item))
        messages.append(fmt_result(item))
    return messages


def main():
    chat_ids = get_chat_ids()
    if not BOT_TOKEN or not chat_ids:
        print("Telegram secrets are not set; skipping notification.")
        return

    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    messages = build_messages(data)

    for chat_id in chat_ids:
        for message in messages:
            send_message(chat_id, message)
        print(f"Sent Telegram notification to chat_id={chat_id}")


if __name__ == "__main__":
    main()
