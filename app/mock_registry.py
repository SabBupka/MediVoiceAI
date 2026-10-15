from datetime import datetime
from itertools import count


class MockRegistry:
    """Минимальная модель поведения OpenAPI-стенда для локальной разработки."""

    def __init__(self) -> None:
        self.doctors = [
            {"id": 1, "full_name": "Верещагин Андрей Михайлович", "specialty": "терапевт", "is_active": True},
            {"id": 2, "full_name": "Ковалёва Людмила Петровна", "specialty": "терапевт", "is_active": True},
            {"id": 3, "full_name": "Смирнова Елена Викторовна", "specialty": "педиатр", "is_active": True},
            {"id": 4, "full_name": "Морозова Светлана Петровна", "specialty": "кардиолог", "is_active": True},
        ]
        self.clients: dict[int, dict] = {}
        self.visits: dict[int, dict] = {}
        self.escalations: dict[int, dict] = {}
        self._client_ids = count(1)
        self._visit_ids = count(1)
        self._escalation_ids = count(1)

    def load_doctors_from_schedule(self, path: str) -> None:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[2]  # «Врачи»
        doctors = []
        for index, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=1):
            if not row or not row[1] or not row[3]:
                continue
            doctors.append(
                {
                    "id": index,
                    "full_name": str(row[1]),
                    "specialty": str(row[3]).lower(),
                    "is_active": True,
                }
            )
        if doctors:
            self.doctors = doctors
            self._client_ids = count(max(d["id"] for d in doctors) + 1)

    def list_doctors(self, specialty: str | None = None) -> list[dict]:
        if not specialty:
            return list(self.doctors)
        return [d for d in self.doctors if d["specialty"].lower() == specialty.lower()]

    def list_clients(self, last_name: str | None = None, first_name: str | None = None,
                     birth_date: str | None = None) -> list[dict]:
        result = list(self.clients.values())
        for field, value in (("last_name", last_name), ("first_name", first_name),
                             ("birth_date", birth_date)):
            if value is not None:
                result = [c for c in result if c[field] == value]
        return result

    def get_client(self, client_id: int) -> dict:
        if client_id not in self.clients:
            raise KeyError(client_id)
        return self.clients[client_id]

    def update_client(self, client_id: int, **changes) -> dict:
        client = self.get_client(client_id)
        for key in ("middle_name", "comment"):
            if key in changes:
                client[key] = changes[key]
        return client

    def find_or_create_client(self, last_name: str, first_name: str, birth_date: str, **extra) -> dict:
        for client in self.clients.values():
            if (client["last_name"], client["first_name"], client["birth_date"]) == (
                last_name, first_name, birth_date
            ):
                return client
        client = {
            "id": next(self._client_ids),
            "last_name": last_name,
            "first_name": first_name,
            "middle_name": extra.get("middle_name"),
            "birth_date": birth_date,
            "comment": extra.get("comment"),
            "created_at": datetime.now().isoformat(),
        }
        self.clients[client["id"]] = client
        return client

    def create_visit(self, client_id: int, doctor_id: int, scheduled_at: str) -> dict:
        doctor = next((d for d in self.doctors if d["id"] == doctor_id), None)
        if not doctor:
            raise ValueError("Врач не найден")
        if not doctor["is_active"]:
            raise ValueError("Врач деактивирован")
        now = datetime.now().isoformat()
        visit = {
            "id": next(self._visit_ids),
            "client_id": client_id,
            "doctor": doctor,
            "scheduled_at": scheduled_at,
            "status": "Запланирована",
            "created_at": now,
            "updated_at": now,
        }
        self.visits[visit["id"]] = visit
        return visit

    def list_visits(self, client_id: int) -> list[dict]:
        return [v for v in self.visits.values() if v["client_id"] == client_id]

    def get_visit(self, visit_id: int) -> dict:
        if visit_id not in self.visits:
            raise KeyError(visit_id)
        return self.visits[visit_id]

    def update_visit(self, visit_id: int, **changes) -> dict:
        visit = self.visits[visit_id]
        if visit["status"] != "Запланирована":
            raise ValueError("Запись нельзя изменить в текущем статусе")
        if changes.get("status") not in (None, "Отменена", "Завершена", "Запланирована"):
            raise ValueError("Недопустимый статус")
        doctor_id = changes.pop("doctor_id", None)
        if doctor_id is not None:
            doctor = next((d for d in self.doctors if d["id"] == doctor_id), None)
            if not doctor:
                raise ValueError("Врач не найден")
            if not doctor["is_active"]:
                raise ValueError("Врач деактивирован")
            visit["doctor"] = doctor
        visit.update({k: v for k, v in changes.items() if v is not None})
        visit["updated_at"] = datetime.now().isoformat()
        return visit

    def create_escalation(self, client_id: int, description: str) -> dict:
        item = {
            "id": next(self._escalation_ids),
            "client_id": client_id,
            "description": description,
            "created_at": datetime.now().isoformat(),
        }
        self.escalations[item["id"]] = item
        return item

    def list_escalations(self) -> list[dict]:
        return list(self.escalations.values())

    def get_escalation(self, escalation_id: int) -> dict:
        if escalation_id not in self.escalations:
            raise KeyError(escalation_id)
        return self.escalations[escalation_id]
