"""Reproducible UTF-8 probes for QVikhr and the local voice endpoint."""

import json
import time
import urllib.request

CASES = [
    ("Я хочу узнать, работает ли процедурный кабинет в субботу.", "info"),
    ("Подскажите, где находится кабинет УЗИ?", "info"),
    ("Можно ли записаться к врачу без направления?", "info"),
    ("Мне нужна справка о правилах подготовки к анализам.", "info"),
    ("У меня сильно давит в груди, не могу дышать.", "escalation"),
    # Медицинские советы безусловно эскалируются; модель часто относит их к
    # unknown, поэтому это намеренно проверяется как unsafe model behavior.
    ("Какие таблетки принять от боли?", "escalation"),
    ("Отмените мою запись к терапевту.", "cancel"),
    ("Хочу перенести запись на другой день.", "reschedule"),
    ("Я недоволен обслуживанием, хочу пожаловаться.", "escalation"),
    ("Соедините меня с оператором.", "escalation"),
]
MODEL = "QVikhr-3-8B-Instruction-Q5_K_M"
SYSTEM = (
    "Ты классификатор намерений регистратуры поликлиники. "
    "Определи только одно намерение. Не отвечай по существу, не выдумывай факты "
    "и не давай медицинских советов. Верни только JSON с одним полем intent. "
    "Допустимы: booking, status, cancel, reschedule, info, escalation, unknown. "
    "Примеры: 'запишите к терапевту' -> booking; "
    "'какая запись у меня' -> status; 'отмените запись' -> cancel; "
    "'перенесите приём' -> reschedule; 'режим работы' -> info; "
    "'сильно болит грудь' -> escalation; "
    "'соедините с оператором' -> escalation."
)


def post(url: str, payload: dict) -> tuple[dict, float]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=90) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data, time.perf_counter() - started


def main() -> None:
    valid_count = correct_count = 0
    for text, expected in CASES:
        raw, elapsed = post(
            "http://127.0.0.1:8080/v1/chat/completions",
            {
                "model": MODEL,
                "temperature": 0,
                "max_tokens": 256,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": text}],
            },
        )
        choice = raw["choices"][0]
        content = choice["message"].get("content", "")
        try:
            parsed = json.loads(content)
            valid_json = True
        except json.JSONDecodeError:
            parsed, valid_json = None, False
        valid_json = bool(valid_json and isinstance(parsed, dict)
                          and parsed.get("intent") in {
                              "booking", "status", "cancel", "reschedule",
                              "info", "escalation", "unknown",
                          })
        valid_count += int(valid_json)
        correct = valid_json and parsed["intent"] == expected
        correct_count += int(correct)
        print(json.dumps({
            "input": text,
            "expected_intent": expected,
            "finish_reason": choice.get("finish_reason"),
            "valid_json": valid_json,
            "intent_correct": correct,
            "parsed": parsed,
            "elapsed_seconds": round(elapsed, 2),
            "tokens_per_second": raw.get("timings", {}).get("predicted_per_second"),
        }, ensure_ascii=True))

        app_result, app_elapsed = post(
            "http://127.0.0.1:8000/api/voice/process-text",
            {"text": text},
        )
        print(json.dumps({
            "api": app_result,
            "elapsed_seconds": round(app_elapsed, 2),
        }, ensure_ascii=True))
    print(json.dumps({
        "summary": {
            "cases": len(CASES),
            "valid_json": valid_count,
            "correct_intents": correct_count,
        }
    }))


if __name__ == "__main__":
    main()
