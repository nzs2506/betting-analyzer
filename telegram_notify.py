import json
import os
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


RESULTS_JSON = Path(os.getenv("RESULTS_JSON", "docs/results.json"))
TELEGRAM_STATE_JSON = Path(os.getenv("TELEGRAM_STATE_JSON", "docs/telegram_state.json"))
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


def load_state():
    try:
        return json.loads(TELEGRAM_STATE_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {"chats": {}}


def save_state(state):
    TELEGRAM_STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    TELEGRAM_STATE_JSON.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


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


def get_schedule_slot():
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    slot_name = "morning" if now.hour < 15 else "evening"
    return f"{now.date().isoformat()}:{slot_name}"


def build_heartbeat_message(data):
    results = data.get("results", [])
    generated_at = data.get("generated_at", "-")
    if results:
        return (
            f"Betting Analyzer: обновление по расписанию.\n"
            f"Новых сигналов или результатов нет. В актуальном отчете: {len(results)} аномалий.\n"
            f"Обновлено: {generated_at}"
        )
    return (
        "Betting Analyzer: обновление по расписанию.\n"
        f"Аномалий сейчас нет.\n"
        f"Обновлено: {generated_at}"
    )


def result_key(item):
    settlement = item["match"].get("settlement") or {}
    return "|".join([
        settlement.get("status") or "pending",
        settlement.get("outcome") or "",
        settlement.get("score") or "",
    ])


def build_messages_for_chat(data, chat_state):
    results = data.get("results", [])
    if not results:
        if chat_state.get("last_empty_report") == data.get("generated_at"):
            return []
        chat_state["last_empty_report"] = data.get("generated_at")
        return build_messages(data)

    is_new_chat = not chat_state.get("initialized") or bool(chat_state.get("send_error"))
    sent_signals = set(chat_state.get("sent_signals", []))
    sent_results = chat_state.get("sent_results", {})

    messages = []
    if is_new_chat:
        messages.append(
            "Подключил тебя к Betting Analyzer.\n"
            "Ниже последний расчет; дальше будут приходить только новые сигналы и обновления результатов."
        )

    for item in results:
        signal_id = item["match"].get("signal_id")
        if not signal_id:
            continue

        if is_new_chat or signal_id not in sent_signals:
            messages.append(fmt_anomaly(item))
            messages.append(fmt_result(item))
            sent_signals.add(signal_id)
            sent_results[signal_id] = result_key(item)
            continue

        current_result_key = result_key(item)
        settlement = item["match"].get("settlement") or {}
        if settlement.get("status") == "completed" and sent_results.get(signal_id) != current_result_key:
            messages.append(fmt_result(item))
            sent_results[signal_id] = current_result_key

    chat_state["initialized"] = True
    chat_state["sent_signals"] = sorted(sent_signals)
    chat_state["sent_results"] = sent_results
    chat_state["last_seen_report"] = data.get("generated_at")
    return messages


def main():
    chat_ids = get_chat_ids()
    if not BOT_TOKEN or not chat_ids:
        print("Telegram secrets are not set; skipping notification.")
        return

    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    state = load_state()
    chats = state.setdefault("chats", {})

    for chat_id in chat_ids:
        chat_state = chats.setdefault(chat_id, {})
        messages = build_messages_for_chat(data, chat_state)
        if not messages:
            schedule_slot = get_schedule_slot()
            if chat_state.get("last_heartbeat_slot") != schedule_slot:
                messages = [build_heartbeat_message(data)]
                chat_state["last_heartbeat_slot"] = schedule_slot
        if not messages:
            print(f"No new Telegram messages for chat_id={chat_id}")
            continue
        sent_count = 0
        for message in messages:
            try:
                send_message(chat_id, message)
                sent_count += 1
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else "unknown"
                print(f"Could not send Telegram message to chat_id={chat_id}: HTTP {status_code}")
                if status_code in {400, 403}:
                    chat_state["send_error"] = str(status_code)
                    break
                raise
        if sent_count:
            chat_state.pop("send_error", None)
            print(f"Sent {sent_count} Telegram messages to chat_id={chat_id}")

    state["last_report"] = data.get("generated_at")
    save_state(state)


if __name__ == "__main__":
    main()
