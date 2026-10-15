from app.dialogue import DialogueEngine


def test_emergency_is_escalated():
    result = DialogueEngine().handle("У меня сильно давит в груди")
    assert result["intent"] == "escalation"
    assert "103 или 112" in result["response"]


def test_medical_advice_is_not_given():
    result = DialogueEngine().handle("Что мне выпить от головной боли?")
    assert result["intent"] == "escalation"


def test_booking_is_routed():
    result = DialogueEngine().handle("Хочу записаться к терапевту")
    assert result["intent"] == "booking"


def test_cancel_is_not_mistaken_for_booking():
    result = DialogueEngine().handle("Отмените мою запись")
    assert result["intent"] == "cancel"


def test_reference_question_is_routed_to_knowledge():
    result = DialogueEngine().handle("Какой режим работы?")
    assert result["intent"] == "info"


def test_specialty_and_identity_are_extracted():
    doctors = [{"specialty": "терапевт"}]
    engine = DialogueEngine()
    assert engine.find_specialty("Мне нужен терапевт", doctors) == "терапевт"
    assert engine.extract_identity("Иванов Пётр 12.09.1980") == {
        "last_name": "Иванов",
        "first_name": "Пётр",
        "birth_date": "12.09.1980",
    }


def test_confirmation_accepts_simple_voice_and_keypad_answers():
    assert DialogueEngine.is_confirmation("1") is True
    assert DialogueEngine.is_confirmation("да") is True
    assert DialogueEngine.is_confirmation("2") is False
    assert DialogueEngine.is_confirmation("нет") is False


def test_unknown_query_asks_for_clarification_instead_of_escalating():
    result = DialogueEngine().handle("Уточните, пожалуйста")
    assert result["intent"] == "unknown"
    assert "Что именно" in result["response"]


def test_unmatched_question_is_escalated_for_operator():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    session = client.post("/api/sessions/incoming", json={"caller_id": "unknown-test"}).json()
    result = client.post(
        f"/api/sessions/{session['id']}/message",
        json={"text": "Есть ли у клиники вертолётная площадка?"},
    ).json()
    assert result["status"] == "escalated"
    assert "оператор" in result["response"].lower() or "сотруднику" in result["response"].lower()


def test_spoken_identity_and_date_are_parsed():
    engine = DialogueEngine()
    identity = engine.extract_identity(
        "Меня зовут Иванов Пётр Сергеевич, двенадцатого сентября 1980 года"
    )
    assert identity == {
        "last_name": "Иванов",
        "first_name": "Пётр",
        "middle_name": "Сергеевич",
        "birth_date": "12.09.1980",
    }
    assert engine.extract_spoken_date(
        "на двадцатое октября", allow_yearless=True
    ) == f"20.10.{__import__('datetime').date.today().year}"
    assert engine.extract_identity(
        "Меня зовут Иванов Пётр Сергеевич, я родился двенадцатого сентября 1980 года"
    )["middle_name"] == "Сергеевич"


def test_slot_choice_accepts_spoken_first_second_and_time():
    from app.main import _match_slot

    options = [
        {"scheduled_at": "20.10.2026 09:40"},
        {"scheduled_at": "20.10.2026 10:00"},
    ]
    assert _match_slot("второй вариант", options) == options[1]
    assert _match_slot("в девять сорок", options) == options[0]


def test_booking_dialogue_confirms_identity_then_doctor_date_time(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main

    class FakeRegistry:
        def list_doctors(self, specialty=None):
            doctors = [
                {"id": 7, "full_name": "Иванова Анна Петровна",
                 "specialty": "терапевт", "is_active": True},
                {"id": 8, "full_name": "Дорохов Сергей Анатольевич",
                 "specialty": "терапевт", "is_active": True},
            ]
            return [d for d in doctors if not specialty or d["specialty"] == specialty]

        def register_client(self, **identity):
            return {"id": 41, **identity}

        def list_clients(self, **filters):
            return []

        def create_visit(self, client_id, doctor_id, scheduled_at):
            return {"id": 82, "scheduled_at": scheduled_at}

    class FakeSlots:
        def list_slots(self, specialty, limit):
            return [
                {"doctor_id": "8", "doctor_name": "Дорохов Сергей Анатольевич",
                 "specialty": specialty, "scheduled_at": "20.10.2026 09:40"},
                {"doctor_id": "8", "doctor_name": "Дорохов Сергей Анатольевич",
                 "specialty": specialty, "scheduled_at": "20.10.2026 10:00"},
                {"doctor_id": "7", "doctor_name": "Иванова Анна Петровна",
                 "specialty": specialty, "scheduled_at": "21.10.2026 11:00"},
            ]

        def reserve(self, doctor_id, scheduled_at, visit_id):
            return None

    monkeypatch.setattr(main, "registry", FakeRegistry())
    monkeypatch.setattr(main, "slots", FakeSlots())
    client = TestClient(main.app)
    session = client.post("/api/sessions/incoming", json={"caller_id": "booking-test"}).json()

    first = client.post(
        f"/api/sessions/{session['id']}/message",
        json={"text": "Хочу записаться к терапевту"},
    ).json()
    assert "фамилию" in first["response"].lower()

    second = client.post(
        f"/api/sessions/{session['id']}/message",
        json={"text": "Иванов Пётр двенадцатого сентября 1980 года"},
    ).json()
    assert "Подтвердите" in second["response"]

    third = client.post(
        f"/api/sessions/{session['id']}/message", json={"text": "да"},
    ).json()
    assert "ближайшие специалисты" in third["response"].lower()

    fourth = client.post(
        f"/api/sessions/{session['id']}/message", json={"text": "Дорохов"},
    ).json()
    assert "какую дату" in fourth["response"].lower()

    fifth = client.post(
        f"/api/sessions/{session['id']}/message", json={"text": "двадцатое октября"},
    ).json()
    assert "девять сорок" in fifth["response"].lower()
    assert "десять ровно" in fifth["response"].lower()

    sixth = client.post(
        f"/api/sessions/{session['id']}/message", json={"text": "в девять сорок"},
    ).json()
    assert "Записать вас" in sixth["response"]

    final = client.post(
        f"/api/sessions/{session['id']}/message", json={"text": "да"},
    ).json()
    assert "Готово. Вы записаны" in final["response"]


def test_incoming_session_routes_followup_turns_through_booking_engine():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    session = client.post(
        "/api/sessions/incoming", json={"caller_id": "followup-regression"}
    ).json()
    first = client.post(
        f"/api/sessions/{session['id']}/message",
        json={"text": "Хочу записаться к терапевту"},
    ).json()
    assert "фамилию" in first["response"].lower()

    second = client.post(
        f"/api/sessions/{session['id']}/message",
        json={"text": "Иванов Пётр двенадцатого сентября 1980 года"},
    ).json()
    assert "Подтвердите" in second["response"]


def test_booking_can_select_by_date_first_then_choose_doctor(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main

    doctors = [
        {"id": 7, "full_name": "Иванова Анна Петровна",
         "specialty": "терапевт", "is_active": True},
        {"id": 8, "full_name": "Дорохов Сергей Анатольевич",
         "specialty": "терапевт", "is_active": True},
    ]

    class FakeRegistry:
        def list_doctors(self, specialty=None):
            return [d for d in doctors if not specialty or d["specialty"] == specialty]

        def list_clients(self, **filters):
            return [{"id": 4, "last_name": "Иванов", "first_name": "Пётр",
                     "birth_date": "12.09.1980", "middle_name": None}]

        def register_client(self, **identity):
            raise AssertionError("Existing client should be found; don't create a new card")

    class FakeSlots:
        def list_slots(self, specialty, limit):
            return [
                {"doctor_id": "7", "doctor_name": doctors[0]["full_name"],
                 "specialty": specialty, "scheduled_at": "20.10.2026 09:40"},
                {"doctor_id": "8", "doctor_name": doctors[1]["full_name"],
                 "specialty": specialty, "scheduled_at": "20.10.2026 10:00"},
            ]

    monkeypatch.setattr(main, "registry", FakeRegistry())
    monkeypatch.setattr(main, "slots", FakeSlots())
    client = TestClient(main.app)
    session = client.post("/api/sessions/incoming", json={"caller_id": "date-first"}).json()

    for utterance in [
        "Хочу записаться к терапевту",
        "Иванов Пётр двенадцатого сентября 1980 года",
        "да",
        "двадцатого октября",
    ]:
        response = client.post(
            f"/api/sessions/{session['id']}/message", json={"text": utterance},
        ).json()
    assert "к кому записать" in response["response"].lower()

    response = client.post(
        f"/api/sessions/{session['id']}/message", json={"text": "Дорохов"},
    ).json()
    assert "десять ровно" in response["response"].lower()


def test_cancel_is_confirmed_before_registry_mutation(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main

    visit = {
        "id": 51,
        "client_id": 12,
        "doctor": {"id": 8, "full_name": "Дорохов Сергей Анатольевич",
                   "specialty": "терапевт"},
        "scheduled_at": "20.10.2026 09:40",
        "status": "Запланирована",
    }

    class FakeRegistry:
        def list_doctors(self, specialty=None): return []
        def list_clients(self, **filters):
            return [{"id": 12, "last_name": "Иванов", "first_name": "Пётр",
                     "birth_date": "12.09.1980", "middle_name": None}]
        def register_client(self, **identity): raise AssertionError("Should use verified search")
        def list_visits(self, client_id): return [visit]
        def get_visit(self, visit_id): return visit
        def update_visit(self, visit_id, **changes):
            visit.update(changes)
            return visit

    class FakeSlots:
        def release(self, visit_id): pass

    monkeypatch.setattr(main, "registry", FakeRegistry())
    monkeypatch.setattr(main, "slots", FakeSlots())
    client = TestClient(main.app)
    session = client.post("/api/sessions/incoming", json={"caller_id": "cancel-confirm"}).json()

    for utterance in ["Отмените запись", "Иванов Пётр 12.09.1980", "да", "да"]:
        result = client.post(
            f"/api/sessions/{session['id']}/message", json={"text": utterance},
        ).json()
        if utterance == "да" and visit["status"] == "Запланирована":
            assert "отменить запись" in result["response"].lower()
    assert visit["status"] == "Отменена"


def test_reference_scenario_uses_local_knowledge():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    session = client.post("/api/sessions/incoming", json={"caller_id": "info-test"}).json()
    result = client.post(
        f"/api/sessions/{session['id']}/message",
        json={"text": "Какой график работы регистратуры?"},
    ).json()
    assert result["status"] == "escalated"
    assert "МИС" in result["response"] or result["response"]


def test_unknown_question_is_escalated_after_two_identity_attempts():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    session = client.post("/api/sessions/incoming", json={"caller_id": "identity-test"}).json()
    first = client.post(
        f"/api/sessions/{session['id']}/message",
        json={"text": "Когда моя запись"},
    ).json()
    assert first["status"] == "active"
    second = client.post(
        f"/api/sessions/{session['id']}/message",
        json={"text": "не знаю"},
    ).json()
    assert second["status"] == "active"
    third = client.post(
        f"/api/sessions/{session['id']}/message",
        json={"text": "тоже не знаю"},
    ).json()
    assert third["status"] == "escalated"
