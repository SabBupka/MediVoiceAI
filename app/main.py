import re
from datetime import datetime

from fastapi import FastAPI, HTTPException

from .config import get_settings
from .dialogue import DialogueEngine
from .mock_registry import MockRegistry
from .registry_client import RegistryClient
from .schemas import (
    EscalateCreate,
    IncomingSessionCreate,
    MessageCreate,
    ScheduleImport,
    SessionResponse,
    SlotResponse,
    ClientCreate,
    ClientUpdate,
    FeedbackCreate,
    ReminderCreate,
    ReminderResult,
    VisitCreate,
    VisitUpdate,
    VoiceTextCreate,
)
from .slot_manager import SlotManager
from .telephony import LocalTelephony
from .knowledge import LocalKnowledgeBase
from .reminders import ReminderManager
from .voice import LocalVoicePipeline, LocalSpeechAdapter

settings = get_settings()
mock = MockRegistry()
if settings.registry_mode == "mock":
    mock.load_doctors_from_schedule(settings.schedule_path)
registry = RegistryClient(settings, mock)
slots = SlotManager(settings.app_db_path)
telephony = LocalTelephony()
dialogue = DialogueEngine()
knowledge = LocalKnowledgeBase(
    settings.regulation_path,
    [
        "docs_tz/tz_kratkoe.txt",
        "docs_tz/tz_voice_assistant.txt",
        "docs_tz/openapi.json",
    ],
)
reminders = ReminderManager(settings.app_db_path)
voice = LocalVoicePipeline(settings, dialogue)
speech = LocalSpeechAdapter(settings)

app = FastAPI(title="Локальная регистратура", version="0.1.0")



def _available_doctors(specialty: str | None) -> list[dict]:
    return [
        doctor for doctor in registry.list_doctors(specialty)
        if doctor.get("is_active", True)
    ]


def _reset_stage_retries(context: dict, stage: str) -> None:
    retry_key = {
        "specialty": "specialty_attempts",
        "identity": "identity_attempts",
        "identity_confirm": "identity_confirm_attempts",
        "doctor_choice": "doctor_choice_attempts",
        "date_doctor_choice": "date_doctor_choice_attempts",
        "date_choice": "date_choice_attempts",
        "time_choice": "time_choice_attempts",
        "appointment_confirm": "appointment_confirm_attempts",
        "visit_choice": "visit_choice_attempts",
        "reschedule_slots": "reschedule_time_attempts",
    }.get(stage)
    if retry_key:
        context.pop(retry_key, None)


def _doctors_for_slots(slot_list: list[dict], doctor_list: list[dict]) -> list[dict]:
    available_names = {slot["doctor_name"] for slot in slot_list}
    return [doctor for doctor in doctor_list if doctor["full_name"] in available_names]


def _spoken_doctor_names(doctor_list: list[dict]) -> str:
    return "; ".join(f"{d['full_name']} ({d['specialty']})" for d in doctor_list)


def _match_doctor(text: str, doctor_list: list[dict]) -> dict | None:
    normalized = text.lower().replace("ё", "е")
    matches = []
    for doctor in doctor_list:
        parts = [part.lower().replace("ё", "е") for part in doctor["full_name"].split()]
        if doctor["full_name"].lower().replace("ё", "е") in normalized:
            return doctor
        if parts and parts[0] in normalized:
            matches.append(doctor)
    return matches[0] if len(matches) == 1 else None


def _spoken_times(option_list: list[dict]) -> str:
    hours = {
        0: "полночь", 1: "час", 2: "два", 3: "три", 4: "четыре",
        5: "пять", 6: "шесть", 7: "семь", 8: "восемь", 9: "девять",
        10: "десять", 11: "одиннадцать", 12: "двенадцать",
        13: "тринадцать", 14: "четырнадцать", 15: "пятнадцать",
        16: "шестнадцать", 17: "семнадцать", 18: "восемнадцать",
        19: "девятнадцать", 20: "двадцать", 21: "двадцать один",
        22: "двадцать два", 23: "двадцать три",
    }
    minute_words = {
        0: "ровно", 5: "пять", 10: "десять", 15: "пятнадцать",
        20: "двадцать", 25: "двадцать пять", 30: "тридцать",
        35: "тридцать пять", 40: "сорок", 45: "сорок пять",
        50: "пятьдесят", 55: "пятьдесят пять",
    }
    spoken = []
    for slot in option_list:
        hour, minute = map(int, slot["scheduled_at"].split(" ")[1].split(":"))
        if minute in minute_words:
            spoken.append(f"в {hours[hour]} {minute_words[minute]}")
        else:
            spoken.append(f"в {slot['scheduled_at'].split(' ')[1]}")
    return "; ".join(spoken)


def _match_slot(text: str, option_list: list[dict]) -> dict | None:
    choice = dialogue.choice_index(text, len(option_list))
    if choice is not None:
        return option_list[choice]
    normalized = text.lower().replace("ё", "е")
    numeric_time = re.search(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", normalized)
    if numeric_time:
        requested = f"{int(numeric_time.group(1)):02d}:{numeric_time.group(2)}"
        return next(
            (slot for slot in option_list if slot["scheduled_at"].endswith(requested)),
            None,
        )
    hour_words = {
        "восемь": 8, "восьми": 8, "девять": 9, "девяти": 9,
        "десять": 10, "десяти": 10, "одиннадцать": 11, "одиннадцати": 11,
        "двенадцать": 12, "двенадцати": 12, "тринадцать": 13, "тринадцати": 13,
        "четырнадцать": 14, "четырнадцати": 14, "пятнадцать": 15, "пятнадцати": 15,
        "шестнадцать": 16, "шестнадцати": 16, "семнадцать": 17, "семнадцати": 17,
        "восемнадцать": 18, "восемнадцати": 18, "девятнадцать": 19, "девятнадцати": 19,
        "двадцать": 20, "двадцати": 20,
    }
    minute_words = {
        "ноль": 0, "ровно": 0, "десять": 10, "пятнадцать": 15, "двадцать": 20,
        "двадцать пять": 25, "тридцать": 30, "тридцать пять": 35,
        "сорок": 40, "сорок пять": 45, "пятьдесят": 50,
        "пять": 5,
    }
    for hour_word, hour in hour_words.items():
        if hour_word not in normalized:
            continue
        tail = normalized.split(hour_word, 1)[1]
        minute = 0
        for phrase, value in sorted(minute_words.items(), key=lambda x: len(x[0]), reverse=True):
            if phrase in tail:
                minute = value
                break
        requested = f"{hour:02d}:{minute:02d}"
        match = next(
            (slot for slot in option_list if slot["scheduled_at"].endswith(requested)),
            None,
        )
        if match:
            return match
    return None


def _offer_times(session, context: dict, candidate_slots: list[dict]) -> dict:
    doctor = context["selected_doctor"]
    requested_date = context["requested_date"]
    options = [
        slot for slot in candidate_slots
        if slot["doctor_name"] == doctor["full_name"]
        and slot["scheduled_at"].startswith(requested_date)
    ][:3]
    if not options:
        context["stage"] = "date_choice"
        return _reply(session, "На эту дату у выбранного врача времени нет. Назовите другую дату.")
    context["options"] = options
    context["stage"] = "time_choice"
    spoken_date = dialogue.format_scheduled_for_speech(
        f"{requested_date} 00:00"
    ).split(", в ")[0]
    return _reply(
        session,
        f"У {doctor['full_name']} {spoken_date} есть свободное время: "
        f"{_spoken_times(options)}. Назовите удобное время.",
    )


def _retry_or_transfer(session, context: dict, key: str, prompt: str, limit: int = 3) -> dict:
    attempts = context.get(key, 0) + 1
    context[key] = attempts
    if attempts >= limit:
        telephony.escalate(session, f"Не удалось распознать ответ на шаге {context.get('stage')}")
        return _reply(
            session,
            "Не хочу ошибиться. Передаю разговор регистратору, он поможет продолжить.",
        )
    return _reply(session, prompt)


@app.middleware("http")
async def utf8_json_responses(request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json") and "charset" not in content_type:
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok", "registry_mode": settings.registry_mode,
        "telephony": "local-text", "asr": settings.asr_mode,
        "tts": settings.tts_mode, "llm": settings.llm_mode,
    }


@app.post("/api/voice/process-text")
def process_voice_text(payload: VoiceTextCreate):
    """Проверка полного маршрута до подключения микрофона/Asterisk."""
    result = voice.process_text(payload.text)
    return {
        "text": result.text, "intent": result.intent, "source": result.source,
        "tts": speech.synthesize(result.text),
    }


@app.get("/api/doctors")
def doctors(specialty: str | None = None) -> list[dict]:
    return registry.list_doctors(specialty)


@app.post("/api/clients")
def register_client(payload: ClientCreate):
    return registry.register_client(**payload.model_dump())


@app.get("/api/clients")
def list_clients(last_name: str | None = None, first_name: str | None = None,
                 birth_date: str | None = None):
    return registry.list_clients(last_name=last_name, first_name=first_name, birth_date=birth_date)


@app.get("/api/clients/{client_id}")
def get_client(client_id: int):
    try:
        return registry.get_client(client_id)
    except KeyError as exc:
        raise HTTPException(404, "Клиент не найден") from exc


@app.patch("/api/clients/{client_id}")
def update_client(client_id: int, payload: ClientUpdate):
    try:
        return registry.update_client(client_id, **payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(404, "Клиент не найден") from exc


@app.post("/api/visits")
def create_visit(payload: VisitCreate):
    if settings.registry_mode == "mock":
        # В mock-режиме идентификаторы врачей соответствуют локальному
        # справочнику; в remote-режиме проверка выполняется стендом.
        pass
    try:
        if settings.registry_mode == "mock" and not slots.is_available(
            str(payload.doctor_id), payload.scheduled_at
        ):
            raise ValueError("Слот отсутствует в расписании или уже занят")
        visit = registry.create_visit(**payload.model_dump())
        if settings.registry_mode == "mock":
            try:
                slots.reserve(str(payload.doctor_id), payload.scheduled_at, visit["id"])
            except ValueError:
                registry.update_visit(visit["id"], status="Отменена")
                raise
        return visit
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/visits")
def list_visits(client_id: int):
    return registry.list_visits(client_id=client_id)


@app.get("/api/visits/{visit_id}")
def get_visit(visit_id: int):
    try:
        return registry.get_visit(visit_id)
    except KeyError as exc:
        raise HTTPException(404, "Запись не найдена") from exc


@app.patch("/api/visits/{visit_id}")
def update_visit(visit_id: int, payload: VisitUpdate):
    try:
        old = registry.get_visit(visit_id)
        if payload.scheduled_at and payload.scheduled_at != old.get("scheduled_at"):
            doctor_id = payload.doctor_id or old["doctor"]["id"]
            if settings.registry_mode == "mock" and not slots.is_available(
                str(doctor_id), payload.scheduled_at
            ):
                raise ValueError("Новый слот отсутствует в расписании или уже занят")
        updated = registry.update_visit(visit_id, **payload.model_dump(exclude_none=True))
        if payload.status == "Отменена":
            slots.release(visit_id)
        elif payload.scheduled_at and old.get("scheduled_at") != payload.scheduled_at:
            slots.release(visit_id)
            if settings.registry_mode == "mock":
                slots.reserve(
                    str(payload.doctor_id or old["doctor"]["id"]),
                    payload.scheduled_at,
                    visit_id,
                )
        return updated
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/escalations")
def create_escalation(client_id: int, description: str):
    try:
        return registry.create_escalation(client_id, description)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/escalations")
def list_escalations(limit: int = 50, offset: int = 0):
    return registry.list_escalations(min(max(limit, 1), 50), max(offset, 0))


@app.get("/api/escalations/{escalation_id}")
def get_escalation(escalation_id: int):
    try:
        return registry.get_escalation(escalation_id)
    except KeyError as exc:
        raise HTTPException(404, "Заявка на соединение не найдена") from exc


@app.get("/api/slots", response_model=list[SlotResponse])
def available_slots(specialty: str | None = None, limit: int = 20):
    return slots.list_slots(specialty, min(max(limit, 1), 50))


@app.get("/api/knowledge/answer")
def knowledge_answer(question: str):
    return knowledge.answer(question)


@app.get("/api/knowledge/manifest")
def knowledge_manifest():
    return knowledge.manifest()


@app.post("/api/reminders")
def create_reminder(payload: ReminderCreate):
    try:
        visit = registry.get_visit(payload.visit_id)
        if visit.get("status") != "Запланирована":
            raise ValueError("Напоминание можно создать только для запланированной записи")
        return reminders.create(visit, payload.caller_id)
    except KeyError as exc:
        raise HTTPException(404, "Запись не найдена") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/reminders/due")
def due_reminders(days: int = 1):
    return reminders.due(min(max(days, 1), 7))


@app.get("/api/reminders/{reminder_id}")
def get_reminder(reminder_id: int):
    try:
        return reminders.get(reminder_id)
    except KeyError as exc:
        raise HTTPException(404, "Напоминание не найдено") from exc


@app.post("/api/reminders/{reminder_id}/result")
def reminder_result(reminder_id: int, payload: ReminderResult):
    try:
        result = reminders.result(reminder_id, payload.result)
        if payload.result == "cancel":
            registry.update_visit(result["visit_id"], status="Отменена")
            slots.release(result["visit_id"])
        return result
    except KeyError as exc:
        raise HTTPException(404, "Напоминание или запись не найдены") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/feedback")
def create_feedback(payload: FeedbackCreate):
    if payload.session_id and payload.session_id not in telephony.sessions:
        raise HTTPException(404, "Сессия не найдена")
    return reminders.feedback(payload.session_id, payload.score, payload.comment)


@app.post("/api/admin/import-schedule")
def import_schedule(payload: ScheduleImport) -> dict:
    path = payload.path or settings.schedule_path
    try:
        doctor_ids = {
            doctor["full_name"]: doctor["id"]
            for doctor in registry.list_doctors()
        }
        return {"inserted": slots.import_excel(path, doctor_ids), "path": path}
    except FileNotFoundError as exc:
        raise HTTPException(400, f"Файл расписания не найден: {path}") from exc


@app.post("/api/sessions/incoming", response_model=SessionResponse)
def incoming(payload: IncomingSessionCreate):
    session = telephony.incoming(payload.caller_id)
    return SessionResponse(
        id=session.id,
        caller_id=session.caller_id,
        status=session.status,
        response=(
            "Здравствуйте. Я виртуальный помощник регистратуры. "
            "В этом текстовом прототипе аудиозапись не ведётся. "
            "Текст обрабатывается для вашего обращения. Чем помочь?"
        ),
        created_at=session.created_at,
    )


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str):
    session = telephony.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Сессия не найдена")
    return SessionResponse(
        id=session.id, caller_id=session.caller_id, status=session.status,
        annotation=session.annotation, created_at=session.created_at,
    )


@app.post("/api/sessions/{session_id}/message", response_model=SessionResponse)
def message(session_id: str, payload: MessageCreate):
    session = telephony.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Сессия не найдена")
    if session.status != "active":
        raise HTTPException(409, "Сессия уже передана оператору или завершена")
    result = dialogue.handle(payload.text)
    telephony.add_message(session, payload.text, result["response"])
    if session.context.get("intent"):
        result = _advance_dialogue(session, payload.text, result)
    elif result["intent"] == "escalation":
        telephony.escalate(
            session,
            f"{result['reason']}; цель: {session.context.get('intent', 'не определена')}",
        )
    elif result["intent"] == "unknown" and not session.context.get("intent"):
        telephony.escalate(session, "Нестандартный вопрос не подтверждён локальной базой знаний")
        result = {
            "response": (
                "Не нашёл подтверждённый ответ в регламенте. "
                "Передаю вопрос сотруднику регистратуры."
            )
        }
    else:
        result = _advance_dialogue(session, payload.text, result)
    return SessionResponse(
        id=session.id, caller_id=session.caller_id, status=session.status,
        response=result["response"], annotation=session.annotation,
        created_at=session.created_at,
    )


def _advance_dialogue(session, text: str, initial: dict) -> dict:
    """Детерминированный MVP-сценарий записи поверх локальных инструментов."""
    context = session.context
    intent = context.get("intent")

    if not intent:
        intent = initial["intent"]
        context["intent"] = intent
        if intent == "info":
            answer = knowledge.answer(text)
            context["stage"] = "completed" if answer["found"] else "operator"
            if not answer["found"]:
                telephony.escalate(session, "Нет точного ответа в локальном регламенте")
            return _reply(session, answer["answer"])
        if intent == "booking":
            specialty = dialogue.find_specialty(text, registry.list_doctors())
            if not specialty:
                context["stage"] = "specialty"
                return _reply(
                    session,
                    "К какому специалисту хотите записаться? Например, к терапевту или педиатру.",
                )
            context["specialty"] = specialty
            context["stage"] = "identity"
            return _reply(
                session,
                "Сначала найду вашу карту. Назовите фамилию, имя и дату рождения. "
                "Можно сказать, например: «Иванов Пётр, двенадцатое сентября 1980 года».",
            )
        if intent in {"status", "cancel", "reschedule"}:
            context["stage"] = "identity"
            return _reply(session, "Назовите фамилию, имя и дату рождения в формате ДД.ММ.ГГГГ.")
        return initial

    if intent == "booking":
        stage = context.get("stage")
        if stage == "specialty":
            specialty = dialogue.find_specialty(text, registry.list_doctors())
            if not specialty:
                return _retry_or_transfer(
                    session, context, "specialty_attempts",
                    "Не расслышал специалиста. Назовите, например, терапевта или педиатра.",
                )
            context["specialty"] = specialty
            context["specialty_attempts"] = 0
            context["stage"] = "identity"
            return _reply(
                session,
                "Хорошо. Теперь назовите фамилию, имя и дату рождения. "
                "Дату можно сказать словами.",
            )
        if stage == "identity":
            _reset_stage_retries(context, stage)
            identity = dialogue.extract_identity(text)
            if not identity:
                context["identity_attempts"] = context.get("identity_attempts", 0) + 1
                if context["identity_attempts"] >= 2:
                    telephony.escalate(session, "ФИО или дата рождения не распознаны дважды")
                    return _reply(session, "Не удалось разобрать данные. Передаю разговор регистратору.")
                return _reply(
                    session,
                    "Не расслышал дату рождения. Скажите её, пожалуйста, словами, например "
                    "«двенадцатое сентября 1980 года».",
                )
            context["identity_attempts"] = 0
            context["pending_identity"] = identity
            context["stage"] = "identity_confirm"
            return _reply(session, dialogue.confirmation_text(identity))

        if stage == "identity_confirm":
            _reset_stage_retries(context, stage)
            confirmation = dialogue.is_confirmation(text)
            if confirmation is None:
                correction = dialogue.extract_identity(text)
                if correction:
                    context["pending_identity"] = correction
                    return _reply(session, dialogue.confirmation_text(correction))
                return _retry_or_transfer(
                    session, context, "identity_confirm_attempts",
                    "Правильно ли я расслышал данные? Скажите «да» или «нет».",
                )
            if confirmation is False:
                context["stage"] = "identity"
                context["identity_attempts"] = 0
                return _reply(session, "Хорошо, исправим. Назовите фамилию, имя и дату рождения.")

            identity = context.pop("pending_identity")
            matches = registry.list_clients(
                last_name=identity["last_name"],
                first_name=identity["first_name"],
                birth_date=identity["birth_date"],
            )
            if identity.get("middle_name"):
                matches = [
                    item for item in matches
                    if (item.get("middle_name") or "").casefold()
                    == identity["middle_name"].casefold()
                ]
            if len(matches) == 1:
                client = matches[0]
            elif len(matches) > 1:
                telephony.escalate(session, "Не удалось однозначно подтвердить карту пациента")
                return _reply(
                    session,
                    "Нашлось несколько карт с такими данными. Передаю вопрос регистратору.",
                )
            else:
                client = registry.register_client(**identity)
            context["client_id"] = client["id"]
            context["stage"] = "doctor_choice"
            all_doctors = _available_doctors(context.get("specialty"))
            available_slots = slots.list_slots(context.get("specialty"), 10000)
            available = _doctors_for_slots(available_slots, all_doctors)
            earliest = {}
            for slot in available_slots:
                earliest.setdefault(slot["doctor_name"], slot["scheduled_at"])
            available.sort(
                key=lambda doctor: earliest.get(doctor["full_name"], "99.99.9999 99:99")
            )
            context["all_doctors"] = available
            if not available:
                telephony.escalate(session, "Нет доступных специалистов со свободными слотами")
                return _reply(session, "Свободных специалистов не нашёл. Передаю вопрос регистратору.")
            if len(available) == 1:
                context["selected_doctor"] = available[0]
                context["stage"] = "date_choice"
                return _reply(
                    session,
                    f"Доступен врач {available[0]['full_name']}. "
                    "На какую дату вам удобно прийти?",
                )
            displayed_doctors = available[:3]
            return _reply(
                session,
                "Данные подтверждены. Ближайшие специалисты со свободным временем: " +
                _spoken_doctor_names(displayed_doctors) +
                ". Назовите врача по фамилии или удобную дату.",
            )

        if stage in {"doctor_choice", "date_doctor_choice"}:
            _reset_stage_retries(context, stage)
            requested_date = dialogue.extract_spoken_date(text, allow_yearless=True)
            if requested_date:
                date_slots = [
                    item for item in slots.list_slots(context.get("specialty"), 10000)
                    if item["scheduled_at"].startswith(requested_date)
                    and item["doctor_name"] in {d["full_name"] for d in context["all_doctors"]}
                ]
                date_doctors = _doctors_for_slots(date_slots, context["all_doctors"])
                if not date_doctors:
                    return _retry_or_transfer(
                        session,
                        context,
                        "date_choice_attempts",
                        "На эту дату свободных приёмов не нашлось. Назовите другого специалиста "
                        "или другую дату.",
                    )
                context["requested_date"] = requested_date
                context["date_doctors"] = date_doctors
                context["stage"] = "date_doctor_choice"
                if len(date_doctors) == 1:
                    context["selected_doctor"] = date_doctors[0]
                    return _offer_times(session, context, date_slots)
                return _reply(
                    session,
                    f"На {requested_date} есть свободное время у: " +
                    _spoken_doctor_names(date_doctors[:3]) +
                    ". К кому записать? Назовите фамилию врача или попросите перечислить ещё.",
                )

            candidates = context.get("date_doctors", context["all_doctors"])
            doctor = _match_doctor(text, candidates)
            if not doctor:
                specialty = dialogue.find_specialty(text, candidates)
                if specialty:
                    narrowed = [d for d in candidates if d["specialty"].casefold() == specialty.casefold()]
                    context["date_doctors"] = narrowed
                    if len(narrowed) == 1:
                        doctor = narrowed[0]
                    else:
                        return _reply(
                            session,
                            "Доступны специалисты: " + _spoken_doctor_names(narrowed[:4]) +
                            ". К кому именно вас записать?",
                        )
            if not doctor:
                return _retry_or_transfer(
                    session,
                    context,
                    "doctor_choice_attempts",
                    "Не нашёл врача по этой фамилии. Назовите фамилию ещё раз "
                    "или выберите удобную дату.",
                )
            context["selected_doctor"] = doctor
            if context.get("requested_date"):
                date_slots = [
                    slot for slot in slots.list_slots(context.get("specialty"), 10000)
                    if slot["doctor_name"] == doctor["full_name"]
                    and slot["scheduled_at"].startswith(context["requested_date"])
                ]
                return _offer_times(session, context, date_slots)
            context["stage"] = "date_choice"
            return _reply(
                session,
                f"У {doctor['full_name']} есть свободные приёмы. На какую дату вас записать?",
            )

        if stage == "date_choice":
            _reset_stage_retries(context, stage)
            requested_date = dialogue.extract_spoken_date(text, allow_yearless=True)
            if not requested_date:
                return _retry_or_transfer(
                    session,
                    context,
                    "date_choice_attempts",
                    "Не расслышал дату. Назовите её, например «пятнадцатого октября».",
                )
            context["requested_date"] = requested_date
            doctor = context["selected_doctor"]
            options = [
                item for item in slots.list_slots(context.get("specialty"), 10000)
                if item["doctor_name"] == doctor["full_name"]
                and item["scheduled_at"].startswith(requested_date)
            ][:3]
            if not options:
                return _retry_or_transfer(
                    session,
                    context,
                    "date_choice_attempts",
                    "На эту дату у выбранного врача времени нет. Назовите другую дату "
                    "или скажите, если подобрать другого специалиста.",
                )
            context["options"] = options
            return _offer_times(session, context, options)

        if stage == "time_choice":
            _reset_stage_retries(context, stage)
            selected = _match_slot(text, context["options"])
            if not selected:
                return _retry_or_transfer(
                    session,
                    context,
                    "time_choice_attempts",
                    "Не расслышал время. Можно назвать часы и минуты или попросить повторить варианты.",
                )
            context["pending_slot"] = selected
            context["stage"] = "appointment_confirm"
            return _reply(
                session,
                f"Записать вас к {context['selected_doctor']['full_name']} "
                f"{dialogue.format_scheduled_for_speech(selected['scheduled_at'])}?",
            )

        if stage == "appointment_confirm":
            confirmation = dialogue.is_confirmation(text)
            if confirmation is None:
                return _retry_or_transfer(
                    session, context, "appointment_confirm_attempts",
                    "Подтверждаете эту запись? Скажите «да» или «нет».",
                )
            if confirmation is False:
                context["stage"] = "date_choice"
                return _reply(session, "Хорошо. Назовите другую удобную дату.")
            selected = context["pending_slot"]
            doctor = context["selected_doctor"]
            try:
                visit = registry.create_visit(
                    context["client_id"], doctor["id"], selected["scheduled_at"]
                )
            except (KeyError, ValueError) as exc:
                return _reply(session, f"Слот уже мог измениться. Проверю ещё раз: {exc}")
            try:
                slots.reserve(selected["doctor_id"], selected["scheduled_at"], visit["id"])
            except ValueError as exc:
                try:
                    registry.update_visit(visit["id"], status="Отменена")
                except (KeyError, ValueError):
                    pass
                return _reply(session, f"Время только что заняли. Давайте подберу другое: {exc}")
            context["visit_id"] = visit["id"]
            context["stage"] = "completed"
            spoken_time = dialogue.format_scheduled_for_speech(selected["scheduled_at"])
            return _reply(
                session,
                f"Готово. Вы записаны к {doctor['full_name']} {spoken_time}.",
            )
    if intent in {"status", "cancel", "reschedule"}:
        if context.get("stage") == "identity":
            identity = dialogue.extract_identity(text)
            if not identity:
                context["identity_attempts"] = context.get("identity_attempts", 0) + 1
                if context["identity_attempts"] >= 2:
                    telephony.escalate(session, "Данные пациента не распознаны дважды")
                    return _reply(session, "Не удалось распознать данные. Передаю разговор оператору.")
                return _reply(session, "Назовите фамилию, имя и дату рождения ещё раз.")
            context["identity_attempts"] = 0
            context["pending_identity"] = identity
            context["stage"] = "patient_action_confirm"
            return _reply(session, dialogue.confirmation_text(identity))

        if context.get("stage") == "patient_action_confirm":
            confirmation = dialogue.is_confirmation(text)
            if confirmation is None:
                correction = dialogue.extract_identity(text)
                if correction:
                    context["pending_identity"] = correction
                    return _reply(session, dialogue.confirmation_text(correction))
                return _reply(session, "Подтвердите данные пациента: скажите «да» или «нет».")
            if confirmation is False:
                context["stage"] = "identity"
                return _reply(session, "Хорошо, исправим. Назовите фамилию, имя и дату рождения.")
            identity = context.pop("pending_identity")
            matches = registry.list_clients(
                last_name=identity["last_name"],
                first_name=identity["first_name"],
                birth_date=identity["birth_date"],
            )
            if identity.get("middle_name"):
                matches = [
                    item for item in matches
                    if (item.get("middle_name") or "").casefold()
                    == identity["middle_name"].casefold()
                ]
            if len(matches) != 1:
                context["stage"] = "completed"
                telephony.escalate(session, "Не удалось однозначно найти карту пациента")
                return _reply(
                    session,
                    "Не удалось однозначно подтвердить карту пациента. "
                    "Передаю вопрос регистратору.",
                )
            client = matches[0]
            context["client_id"] = client["id"]
            visits = [
                visit for visit in registry.list_visits(client_id=client["id"])
                if visit.get("status") == "Запланирована"
            ]
            if not visits:
                context["stage"] = "completed"
                return _reply(session, "Активных записей не найдено.")
            context["visits"] = visits
            if len(visits) > 1:
                context["stage"] = "visit_choice"
                context["visits"] = visits[:3]
                lines = [
                    f"{i}. {v['doctor']['full_name']}, "
                    f"{dialogue.format_scheduled_for_speech(v['scheduled_at'])}"
                    for i, v in enumerate(context["visits"], 1)
                ]
                return _reply(session, "Нашёл несколько записей:\n" + "\n".join(lines) +
                              "\nНазовите фамилию врача или скажите «первая», «вторая», «третья».")
            context["visit_id"] = visits[0]["id"]
            return _continue_visit_action(session, intent, visits[0])

        if context.get("stage") == "visit_choice":
            _reset_stage_retries(context, "visit_choice")
            choice = dialogue.choice_index(text, len(context["visits"]))
            if choice is None:
                matches = [
                    visit for visit in context["visits"]
                    if visit["doctor"]["full_name"].split()[0].lower() in text.lower()
                ]
                if len(matches) != 1:
                    return _reply(
                        session,
                        "Назовите фамилию врача из списка или скажите «первая», «вторая» или «третья».",
                    )
                visit = matches[0]
            else:
                visit = context["visits"][choice]
            context["visit_id"] = visit["id"]
            return _continue_visit_action(session, intent, visit)

        if context.get("stage") == "reschedule_slots":
            _reset_stage_retries(context, "reschedule_slots")
            selected = _match_slot(text, context["options"])
            if not selected:
                return _reply(session, "Назовите время словами или попросите повторить варианты.")
            context["pending_slot"] = selected
            context["stage"] = "reschedule_confirm"
            return _reply(
                session,
                f"Перенести вашу запись на {dialogue.format_scheduled_for_speech(selected['scheduled_at'])}?",
            )

        if context.get("stage") == "cancel_confirm":
            confirmation = dialogue.is_confirmation(text)
            if confirmation is None:
                return _reply(session, "Подтверждаете отмену записи? Скажите «да» или «нет».")
            if confirmation is False:
                context["stage"] = "completed"
                return _reply(session, "Хорошо, запись оставлена без изменений.")
            visit = registry.get_visit(context["visit_id"])
            try:
                registry.update_visit(visit["id"], status="Отменена")
                slots.release(visit["id"])
            except (KeyError, ValueError) as exc:
                return _reply(session, f"Не удалось отменить запись: {exc}")
            context["stage"] = "completed"
            return _reply(session, "Запись отменена.")

        if context.get("stage") == "reschedule_date":
            _reset_stage_retries(context, "reschedule_date")
            requested_date = dialogue.extract_spoken_date(text, allow_yearless=True)
            if not requested_date:
                return _retry_or_transfer(
                    session, context, "reschedule_date_attempts",
                    "Назовите дату словами, например «пятнадцатого октября».",
                )
            visit = registry.get_visit(context["visit_id"])
            doctor = visit["doctor"]
            day_slots = [
                slot for slot in slots.list_slots(doctor["specialty"], 10000)
                if slot["scheduled_at"].startswith(requested_date)
                and slot["scheduled_at"] != visit["scheduled_at"]
            ]
            day_doctors = _doctors_for_slots(
                day_slots,
                _available_doctors(doctor["specialty"]),
            )
            context["requested_date"] = requested_date
            context["reschedule_doctors"] = day_doctors
            same_doctor = any(
                token in text.lower()
                for token in ("тот же", "этот же", "к своему врачу", "к тому же")
            )
            if same_doctor:
                selected_doctor = next(
                    (d for d in day_doctors if d["full_name"] == doctor["full_name"]),
                    None,
                )
            elif len(day_doctors) == 1:
                selected_doctor = day_doctors[0]
            else:
                selected_doctor = None
            if not selected_doctor and len(day_doctors) > 1:
                context["stage"] = "reschedule_doctor_choice"
                return _reply(
                    session,
                    f"На {dialogue.format_scheduled_for_speech(requested_date + ' 00:00').split(', в ')[0]} "
                    "принимают несколько врачей: " + _spoken_doctor_names(day_doctors[:3]) +
                    ". К кому перенести? Назовите фамилию или скажите «к тому же врачу».",
                )
            if selected_doctor:
                context["reschedule_doctor"] = selected_doctor
                options = [
                    slot for slot in day_slots
                    if slot["doctor_name"] == selected_doctor["full_name"]
                ][:3]
            else:
                options = []
            if not options:
                return _reply(
                    session,
                    "На эту дату свободного времени не нашёл. Назовите другую дату.",
                )
            context["options"] = options
            context["stage"] = "reschedule_slots"
            return _reply(
                session,
                "Доступно время: " + _spoken_times(options) +
                ". Назовите удобное время.",
                )

        if context.get("stage") == "reschedule_doctor_choice":
            _reset_stage_retries(context, "reschedule_doctor_choice")
            candidates = context["reschedule_doctors"]
            old_visit = registry.get_visit(context["visit_id"])
            if any(token in text.lower() for token in ("тот же", "этому же", "своему врачу")):
                doctor = next(
                    (d for d in candidates if d["full_name"] == old_visit["doctor"]["full_name"]),
                    None,
                )
            else:
                doctor = _match_doctor(text, candidates)
            if not doctor:
                attempts = context.get("reschedule_doctor_attempts", 0) + 1
                context["reschedule_doctor_attempts"] = attempts
                if attempts >= 2:
                    telephony.escalate(session, "Не удалось определить врача для переноса")
                    return _reply(session, "Не удалось выбрать врача. Передаю вопрос регистратору.")
                return _reply(
                    session,
                    "Не расслышал фамилию. Назовите её ещё раз или скажите «к тому же врачу».",
                )
            context["reschedule_doctor"] = doctor
            context["options"] = [
                slot for slot in slots.list_slots(doctor["specialty"], 10000)
                if slot["doctor_name"] == doctor["full_name"]
                and slot["scheduled_at"].startswith(context["requested_date"])
            ][:3]
            if not context["options"]:
                return _reply(session, "У этого врача на эту дату свободного времени нет.")
            context["stage"] = "reschedule_slots"
            return _reply(
                session,
                f"У {doctor['full_name']} доступно: {_spoken_times(context['options'])}. "
                "Назовите удобное время.",
            )

        if context.get("stage") == "reschedule_confirm":
            confirmation = dialogue.is_confirmation(text)
            if confirmation is None:
                return _retry_or_transfer(
                    session, context, "reschedule_confirm_attempts",
                    "Подтверждаете перенос? Скажите «да» или «нет».",
                )
            if confirmation is False:
                context["stage"] = "reschedule_date"
                return _reply(session, "Хорошо. Назовите другую удобную дату.")
            visit = registry.get_visit(context["visit_id"])
            selected = context["pending_slot"]
            old_scheduled = visit["scheduled_at"]
            selected_doctor = context.get("reschedule_doctor", visit["doctor"])
            doctor_id = selected_doctor["id"]
            temporary_reservation_id = -int(datetime.now().timestamp() * 1000)
            destination_reserved = False
            try:
                slots.reserve(
                    selected["doctor_id"],
                    selected["scheduled_at"],
                    temporary_reservation_id,
                )
                destination_reserved = True
                updated = registry.update_visit(
                    visit["id"],
                    scheduled_at=selected["scheduled_at"],
                    doctor_id=doctor_id,
                )
                slots.finalize_reservation(temporary_reservation_id, visit["id"])
                slots.release_slot(str(visit["doctor"]["id"]), old_scheduled)
            except (KeyError, ValueError) as exc:
                if destination_reserved:
                    slots.release(temporary_reservation_id)
                return _reply(session, f"Перенос не выполнен. Запись не меняла: {exc}")
            context["stage"] = "completed"
            return _reply(
                session,
                f"Запись перенесена на {dialogue.format_scheduled_for_speech(updated['scheduled_at'])}.",
            )
    return initial


def _continue_visit_action(session, intent: str, visit: dict) -> dict:
    if intent == "status":
        session.context["stage"] = "completed"
        return _reply(
            session,
            f"У вас запись к {visit['doctor']['full_name']} на {visit['scheduled_at']}.",
        )
    if intent == "cancel":
        session.context["stage"] = "cancel_confirm"
        return _reply(
            session,
            f"Отменить запись к {visit['doctor']['full_name']} "
            f"{dialogue.format_scheduled_for_speech(visit['scheduled_at'])}?",
        )
    specialty = visit["doctor"]["specialty"]
    options = [
        slot for slot in slots.list_slots(specialty, 10000)
        if slot["doctor_name"] == visit["doctor"]["full_name"]
        and slot["scheduled_at"] != visit["scheduled_at"]
    ][:3]
    if not options:
        return _reply(session, "Других свободных слотов не нашёл. Передаю вопрос регистратору.")
    session.context["options"] = options
    session.context["stage"] = "reschedule_date"
    return _reply(session, "На какую дату хотите перенести запись? Назовите дату словами.")


def _reply(session, response: str) -> dict:
    return {"intent": session.context.get("intent", "dialogue"), "response": response}


@app.post("/api/sessions/{session_id}/escalate", response_model=SessionResponse)
def escalate(session_id: str, payload: EscalateCreate):
    session = telephony.sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Сессия не найдена")
    telephony.escalate(session, payload.reason)
    return SessionResponse(
        id=session.id, caller_id=session.caller_id, status=session.status,
        annotation=session.annotation, created_at=session.created_at,
    )
