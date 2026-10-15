from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IncomingSessionCreate(BaseModel):
    caller_id: str = Field(min_length=1, max_length=100)


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class EscalateCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class ScheduleImport(BaseModel):
    path: str | None = None


class SessionResponse(BaseModel):
    id: str
    caller_id: str
    status: Literal["active", "escalated", "closed"]
    response: str | None = None
    annotation: str | None = None
    created_at: datetime


class SlotResponse(BaseModel):
    doctor_id: str
    doctor_name: str
    specialty: str
    scheduled_at: str


class ClientCreate(BaseModel):
    last_name: str = Field(min_length=1, max_length=100)
    first_name: str = Field(min_length=1, max_length=100)
    birth_date: str
    middle_name: str | None = None
    comment: str | None = None


class ClientUpdate(BaseModel):
    middle_name: str | None = None
    comment: str | None = None


class VisitCreate(BaseModel):
    client_id: int
    doctor_id: int
    scheduled_at: str


class VisitUpdate(BaseModel):
    doctor_id: int | None = None
    scheduled_at: str | None = None
    status: Literal["Запланирована", "Отменена", "Завершена"] | None = None


class ReminderCreate(BaseModel):
    visit_id: int
    caller_id: str = Field(min_length=1, max_length=100)


class ReminderResult(BaseModel):
    result: Literal["confirmed", "reschedule", "cancel", "no_answer"]


class FeedbackCreate(BaseModel):
    session_id: str | None = None
    score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class VoiceTextCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
