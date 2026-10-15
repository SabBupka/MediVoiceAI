from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass
class LocalCallSession:
    caller_id: str
    id: str = field(default_factory=lambda: str(uuid4()))
    status: str = "active"
    messages: list[dict] = field(default_factory=list)
    annotation: str | None = None
    context: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


class LocalTelephony:
    def __init__(self) -> None:
        self.sessions: dict[str, LocalCallSession] = {}

    def incoming(self, caller_id: str) -> LocalCallSession:
        session = LocalCallSession(caller_id=caller_id)
        self.sessions[session.id] = session
        return session

    def add_message(self, session: LocalCallSession, text: str, response: str) -> None:
        session.messages.append({"role": "user", "text": text})
        session.messages.append({"role": "assistant", "text": response})

    def escalate(self, session: LocalCallSession, annotation: str) -> None:
        session.status = "escalated"
        session.annotation = annotation
