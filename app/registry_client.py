from collections import deque
from time import monotonic
import time

import httpx

from .config import Settings
from .mock_registry import MockRegistry


class RegistryClient:
    def __init__(self, settings: Settings, mock: MockRegistry | None = None) -> None:
        self.settings = settings
        self.mock = mock
        self._doctors_cache: tuple[float, list[dict]] | None = None
        self._requests = deque()

    def _allow(self) -> None:
        now = monotonic()
        while self._requests and now - self._requests[0] > 60:
            self._requests.popleft()
        if len(self._requests) >= 10:
            raise RuntimeError("Локальный лимит API: достигнуто 10 запросов в минуту")
        self._requests.append(now)

    def _request(self, method: str, path: str, **kwargs) -> dict | list:
        self._allow()
        headers = {"Authorization": f"Bearer {self.settings.registry_api_token}"}
        response = httpx.request(method, f"{self.settings.registry_api_base_url}{path}",
                                  headers=headers, timeout=15, **kwargs)
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "1")
            try:
                time.sleep(min(float(retry_after), 5))
            except ValueError:
                time.sleep(1)
            response = httpx.request(method, f"{self.settings.registry_api_base_url}{path}",
                                      headers=headers, timeout=15, **kwargs)
        response.raise_for_status()
        return response.json()

    def list_doctors(self, specialty: str | None = None) -> list[dict]:
        if self.settings.registry_mode == "mock":
            return self.mock.list_doctors(specialty)
        import time

        if not specialty and self._doctors_cache and time.time() - self._doctors_cache[0] < 600:
            return self._doctors_cache[1]
        self._allow()
        headers = {"Authorization": f"Bearer {self.settings.registry_api_token}"}
        response = httpx.get(
            f"{self.settings.registry_api_base_url}/doctors",
            headers=headers,
            params={"specialty": specialty} if specialty else None,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if not specialty:
            self._doctors_cache = (time.time(), data)
        return data

    def register_client(self, last_name: str, first_name: str, birth_date: str, **extra) -> dict:
        if self.settings.registry_mode == "mock":
            return self.mock.find_or_create_client(last_name, first_name, birth_date, **extra)
        payload = {"last_name": last_name, "first_name": first_name, "birth_date": birth_date}
        payload.update({key: value for key, value in extra.items() if value is not None})
        return self._request("POST", "/clients", json=payload)

    def list_clients(self, **filters) -> list[dict]:
        filters = {key: value for key, value in filters.items() if value is not None}
        if self.settings.registry_mode == "mock":
            return self.mock.list_clients(**filters)
        return self._request("GET", "/clients", params=filters)

    def get_client(self, client_id: int) -> dict:
        if self.settings.registry_mode == "mock":
            return self.mock.get_client(client_id)
        return self._request("GET", f"/clients/{client_id}")

    def update_client(self, client_id: int, **changes) -> dict:
        if self.settings.registry_mode == "mock":
            return self.mock.update_client(client_id, **changes)
        return self._request("PATCH", f"/clients/{client_id}", json=changes)

    def create_visit(self, client_id: int, doctor_id: int, scheduled_at: str) -> dict:
        if self.settings.registry_mode == "mock":
            return self.mock.create_visit(client_id, doctor_id, scheduled_at)
        return self._request(
            "POST", "/visits",
            json={"client_id": client_id, "doctor_id": doctor_id, "scheduled_at": scheduled_at},
        )

    def list_visits(self, **filters) -> list[dict]:
        filters = {key: value for key, value in filters.items() if value is not None}
        if self.settings.registry_mode == "mock":
            return self.mock.list_visits(filters["client_id"])
        return self._request("GET", "/visits", params=filters)

    def get_visit(self, visit_id: int) -> dict:
        if self.settings.registry_mode == "mock":
            return self.mock.get_visit(visit_id)
        return self._request("GET", f"/visits/{visit_id}")

    def update_visit(self, visit_id: int, **changes) -> dict:
        changes = {key: value for key, value in changes.items() if value is not None}
        if self.settings.registry_mode == "mock":
            return self.mock.update_visit(visit_id, **changes)
        return self._request("PATCH", f"/visits/{visit_id}", json=changes)

    def create_escalation(self, client_id: int, description: str) -> dict:
        if self.settings.registry_mode == "mock":
            return self.mock.create_escalation(client_id, description)
        return self._request(
            "POST", "/escalations", json={"client_id": client_id, "description": description},
        )

    def list_escalations(self, limit: int = 50, offset: int = 0) -> list[dict]:
        if self.settings.registry_mode == "mock":
            return self.mock.list_escalations()[offset:offset + limit]
        return self._request("GET", "/escalations", params={"limit": limit, "offset": offset})

    def get_escalation(self, escalation_id: int) -> dict:
        if self.settings.registry_mode == "mock":
            return self.mock.get_escalation(escalation_id)
        return self._request("GET", f"/escalations/{escalation_id}")
