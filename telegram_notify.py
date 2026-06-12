import json
import os
import re
from pathlib import Path

import requests


RESULTS_JSON = Path(os.getenv("RESULTS_JSON", "docs/results.json"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
MAX_RECIPIENTS = 4


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
        for chat_id in re.split(r"[\s,;]+", raw.strip()):
            if chat_id and chat_id not in seen:
                chat_ids.append(chat_id)
                seen.add(chat_id)
            if len(chat_ids) >= MAX_RECIPIENTS:
                return chat_ids
    return chat_ids


def fmt_match(item):
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
            f"Betting Analyzer: аномалий нет.\n"
            f"Обновлено: {data.get('generated_at', '-')}"
        ]

    header = (
        f"Betting Analyzer: найдено {len(results)} аномалий\n"
        f"Обновлено: {data.get('generated_at', '-')}\n\n"
    )
    chunks = []
    current = header
    for item in results:
        block = fmt_match(item) + "\n\n"
        if len(current) + len(block) > 3500:
            chunks.append(current.strip())
            current = ""
        current += block
    if current.strip():
        chunks.append(current.strip())
    return chunks


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
