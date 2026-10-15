import pytest

from app.mock_registry import MockRegistry


def test_client_registration_is_idempotent():
    registry = MockRegistry()
    a = registry.find_or_create_client("Иванов", "Пётр", "12.09.1980")
    b = registry.find_or_create_client("Иванов", "Пётр", "12.09.1980")
    assert a["id"] == b["id"]


def test_cancelled_visit_cannot_be_changed():
    registry = MockRegistry()
    client = registry.find_or_create_client("Иванов", "Пётр", "12.09.1980")
    visit = registry.create_visit(client["id"], 1, "20.10.2026 10:00")
    registry.update_visit(visit["id"], status="Отменена")
    with pytest.raises(ValueError):
        registry.update_visit(visit["id"], scheduled_at="21.10.2026 10:00")


def test_slots_deduplicate_alias_doctor_ids_and_block_all_aliases(tmp_path):
    from app.slot_manager import SlotManager

    manager = SlotManager(str(tmp_path / "slots.sqlite3"))
    scheduled = "20.10.2026 09:40"
    manager.db.executemany(
        "INSERT INTO slots VALUES (?, ?, ?, ?, 0)",
        [
            ("D060", "Доктор Тест", "терапевт", scheduled),
            ("60", "Доктор Тест", "терапевт", scheduled),
        ],
    )
    manager.db.commit()
    assert len(manager.list_slots("терапевт", 10)) == 1
    manager.reserve("60", scheduled, 123)
    assert manager.list_slots("терапевт", 10) == []
    manager.release(123)
    assert len(manager.list_slots("терапевт", 10)) == 1
