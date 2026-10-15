"""Локальные адаптеры голосового контура.

Сейчас по умолчанию используется безопасный текстовый fallback. После загрузки
моделей режимы переключаются через .env, не меняя сценарии регистратуры.
"""

import json
from dataclasses import dataclass

import httpx

from .config import Settings
from .dialogue import DialogueEngine


@dataclass
class VoiceResult:
    text: str
    intent: str
    source: str
    audio_ready: bool = False


class LocalVoicePipeline:
    SAFE_RESPONSES = {
        "booking": "Помогу с записью. Назовите специальность врача.",
        "status": "Проверю ваши запланированные записи.",
        "cancel": "Проверю активные записи для отмены.",
        "reschedule": "Проверю запись и доступные новые слоты.",
        "info": "Проверю информацию в локальном регламенте клиники.",
        "escalation": "Сейчас передам разговор сотруднику регистратуры.",
        "unknown": (
            "Я помогу с записью, переносом, отменой или справочной информацией. "
            "Что именно вас интересует?"
        ),
    }

    def __init__(self, settings: Settings, dialogue: DialogueEngine) -> None:
        self.settings = settings
        self.dialogue = dialogue

    def process_text(self, text: str) -> VoiceResult:
        """Точка входа для AudioSocket/ASR: принимает уже распознанную реплику."""
        # Безопасное правило: типовые и опасные намерения не отдаём на
        # свободную генерацию. Это защищает запись, отмену и эскалации от
        # нестабильного ответа модели.
        normalized_text = text.lower().replace("ё", "е")
        if self._is_must_escalate(normalized_text):
            reason = (
                "Запрос медицинской консультации"
                if self._looks_like_medical_request(normalized_text)
                else "Возможное неотложное состояние или просьба оператора"
            )
            return VoiceResult(
                self.SAFE_RESPONSES["escalation"], "escalation", "rule-safe",
            )
        deterministic = self.dialogue.handle(text)
        if deterministic["intent"] != "unknown":
            return VoiceResult(
                deterministic["response"], deterministic["intent"], "rule-safe",
            )
        if self.settings.llm_mode == "remote-local":
            try:
                result = self._llm_plan(text)
                intent = result["intent"]
                # Модель классифицирует намерение, но не формирует фактический
                # ответ: факты выдаются только из API/локальной базы знаний.
                return VoiceResult(
                    self.SAFE_RESPONSES[intent], intent, "local-llm-classifier",
                )
            except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
                pass
        result = self.dialogue.handle(text)
        return VoiceResult(result["response"], result["intent"], "rule-fallback")

    @staticmethod
    def _is_must_escalate(text: str) -> bool:
        emergency = (
            "давит в груди", "боль в груди", "сильно болит", "острая боль",
            "не могу дышать", "теряю сознание", "обморок",
        )
        medical = (
            "что выпить", "мне выпить", "какие таблетки", "какое лекарство",
            "какие лекарства", "что принимать", "что принять", "какой диагноз",
            "посоветуйте лекарство", "назначьте препарат",
        )
        operator_request = (
            "соедините с оператором", "соединить с оператором",
            "позовите оператора", "хочу оператора", "соедините с человеком",
        )
        complaint = ("жалоба", "пожаловаться", "недоволен", "недовольна")
        return any(token in text for token in emergency + medical + operator_request + complaint)

    @staticmethod
    def _looks_like_medical_request(text: str) -> bool:
        return any(token in text for token in (
            "что выпить", "мне выпить", "таблет", "лекарств", "препарат",
            "что принимать", "что принять", "диагноз",
        ))

    def _llm_plan(self, text: str) -> dict:
        response = httpx.post(
            f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Content-Type": "application/json"},
            timeout=self.settings.llm_timeout_seconds,
            json={
                "model": self.settings.llm_model,
                "temperature": 0,
                "max_tokens": 128,
                "chat_template_kwargs": {"enable_thinking": False},
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Ты классификатор намерений регистратуры поликлиники. "
                            "Определи только одно намерение пациента. Не отвечай по существу, "
                            "не выдумывай факты и не давай медицинских советов. "
                            "Верни только JSON с одним полем intent. Допустимы: "
                            "booking, status, cancel, reschedule, info, escalation, unknown. "
                            "Примеры: 'запишите к терапевту' -> booking; "
                            "'какая запись у меня' -> status; 'отмените запись' -> cancel; "
                            "'перенесите приём' -> reschedule; 'режим работы' -> info; "
                            "'сильно болит грудь' -> escalation; "
                            "'соедините с оператором' -> escalation."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        content = content.strip().removeprefix("```json").removesuffix("```").strip()
        result = json.loads(content)
        if result["intent"] not in {
            "booking", "status", "cancel", "reschedule", "info", "escalation", "unknown",
        }:
            raise ValueError("LLM вернула недопустимое намерение")
        return result


class LocalSpeechAdapter:
    """Контракт для GigaAM/Silero; не отправляет аудио во внешние сервисы."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def transcribe(self, audio: bytes) -> str:
        if self.settings.asr_mode != "stub":
            raise NotImplementedError("Подключите локальный GigaAM или faster-whisper адаптер")
        raise NotImplementedError("В stub-режиме аудио не декодируется; используйте текстовый endpoint")

    def synthesize(self, text: str) -> dict:
        if self.settings.tts_mode != "stub":
            raise NotImplementedError("Подключите локальный Silero TTS адаптер")
        return {"text": text, "audio_ready": False, "format": "pcm_s16le", "sample_rate": 16000}
