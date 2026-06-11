import json
import os
from pathlib import Path

import requests


RESULTS_JSON = Path(os.getenv("RESULTS_JSON", "docs/results.json"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


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


def send_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()


def main():
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets are not set; skipping notification.")
        return

    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    results = data.get("results", [])

    if not results:
        send_message(
            f"Betting Analyzer: аномалий нет.\n"
            f"Обновлено: {data.get('generated_at', '-')}"
        )
        return

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

    for chunk in chunks:
        send_message(chunk)


if __name__ == "__main__":
    main()
