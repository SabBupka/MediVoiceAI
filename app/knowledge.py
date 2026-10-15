"""Строгая локальная база знаний: извлекает и цитирует, но не сочиняет факты."""

from dataclasses import dataclass
import html
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
STOP_WORDS = {
    "это", "как", "какой", "какая", "какие", "можно", "нужно", "мне", "моя",
    "мой", "для", "или", "есть", "где", "что", "про", "при", "по", "из", "на",
    "в", "и", "а", "у", "к", "с", "о", "от", "до", "ли", "вы", "он", "она",
}
GENERIC_TERMS = {
    "работ", "график", "стоимос", "цен", "режим", "контакт", "информац",
    "услуг", "вопрос", "ответ", "поликлиник", "кабинет", "отделен",
}
QUERY_SYNONYMS = {
    "готов": {"готов", "результат", "выполн"},
    "анализ": {"анализ", "лаборатор", "исследован"},
    "адрес": {"адрес", "улиц", "местонахожд"},
    "стоимос": {"стоимос", "цен", "плат", "тариф"},
    "режим": {"режим", "график", "работ"},
    "работ": {"режим", "график", "работ"},
}
RU_ENDINGS = (
    "ующими", "ющими", "ировать", "ироваться", "яются", "аются", "яются",
    "ается", "яется", "уются", "ится", "ется", "ются", "ились", "алась",
    "ялся", "ались", "иями", "ями", "ами", "ого", "ему", "ыми", "ими",
    "ает", "яет", "ует", "ить", "ать", "ять", "еть", "ут", "ют", "ит",
    "ет", "ть", "ться", "лся", "лась", "лись", "ет",
    "ее", "ие", "ые",
    "ое", "ей", "ий", "ый", "ой", "ая", "яя", "ою", "ею", "ам", "ям",
    "ов", "ев", "ах", "ях", "ом", "ем", "ы", "и", "а", "я", "у", "ю", "е", "о",
)


@dataclass(frozen=True)
class KnowledgeChunk:
    text: str
    source: str
    section: str | None
    ordinal: int
    source_status: str

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "source": self.source,
            "section": self.section,
            "ordinal": self.ordinal,
            "source_status": self.source_status,
        }


class LocalKnowledgeBase:
    """Extractive lexical RAG over approved local files.

    Answer is always a verbatim source excerpt. No LLM-generated facts are used.
    """

    def __init__(self, document_path: str, extra_paths: list[str] | None = None) -> None:
        self.document_path = document_path
        paths = list(dict.fromkeys([document_path, *(extra_paths or [])]))
        self.chunks = [chunk for path in paths for chunk in self._load_path(path)]

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip()

    @classmethod
    def _tokens(cls, text: str) -> list[str]:
        result = []
        for token in re.findall(r"[а-яa-z0-9]{3,}", cls._normalize(text)):
            if token in STOP_WORDS:
                continue
            if re.fullmatch(r"[а-я]+", token):
                for ending in RU_ENDINGS:
                    if token.endswith(ending) and len(token) - len(ending) >= 3:
                        token = token[:-len(ending)]
                        break
            result.append(token)
        return result

    @classmethod
    def _load_path(cls, raw_path: str) -> list[KnowledgeChunk]:
        path = Path(raw_path)
        if not path.exists():
            return []
        suffix = path.suffix.lower()
        if suffix == ".docx":
            records = cls._docx_content(path)
        elif suffix in {".txt", ".md"}:
            records = path.read_text(encoding="utf-8").splitlines()
        elif suffix == ".json":
            return cls._openapi_chunks(path)
        else:
            return []

        result = []
        section: str | None = None
        conditional_region = False
        for ordinal, record in enumerate(records):
            normalized = cls._normalize(record)
            if len(normalized) < 20 or "pageref" in normalized or "toc" in normalized:
                continue
            if re.match(r"^(?:\d+(?:\.\d+)*\.?|[ivx]+)[\s.)-]+", normalized, re.I):
                section = record.strip()
                if re.match(r"^2(?:\.|\s)", normalized) and "справоч" in normalized:
                    conditional_region = True
                elif re.match(r"^3(?:\.|\s)", normalized):
                    conditional_region = False
            if path.name.lower().startswith("tz_"):
                status = "requirements"
            elif path.suffix.lower() == ".json":
                status = "api_contract"
            elif conditional_region:
                status = "conditional_example"
            else:
                status = "patient_reference"
            result.append(KnowledgeChunk(
                text=record.strip(), source=path.as_posix(), section=section,
                ordinal=ordinal, source_status=status,
            ))
        return result

    @staticmethod
    def _docx_content(path: Path) -> list[str]:
        ns = {"w": WORD_NS}
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        body = root.find(".//w:body", ns)
        if body is None:
            return []
        records: list[str] = []
        for child in body:
            if child.tag == f"{{{WORD_NS}}}p":
                text = "".join(node.text or "" for node in child.findall(".//w:t", ns))
                text = re.sub(r"\s+", " ", html.unescape(text)).strip()
                if text:
                    records.append(text)
            elif child.tag == f"{{{WORD_NS}}}tbl":
                rows: list[list[str]] = []
                for row in child.findall("./w:tr", ns):
                    cells = []
                    for cell in row.findall("./w:tc", ns):
                        cell_text = " ".join(
                            "".join(node.text or "" for node in p.findall(".//w:t", ns))
                            for p in cell.findall("./w:p", ns)
                        )
                        cells.append(re.sub(r"\s+", " ", html.unescape(cell_text)).strip())
                    if any(cells):
                        rows.append(cells)
                if rows:
                    header = rows[0]
                    if (len(header) == 2 and
                            header[0].lower() in {"параметр", "термин", "код", "полное наименование"}):
                        for row in rows[1:]:
                            if len(row) >= 2 and row[0] and row[1]:
                                records.append(f"{header[0]}: {row[0]} | {header[1]}: {row[1]}")
                    else:
                        for row in rows[1:]:
                            if len(header) == len(row) and all(header):
                                text = " | ".join(
                                    f"{key}: {value}" for key, value in zip(header, row) if value
                                )
                            else:
                                text = " | ".join(value for value in row if value)
                            if text:
                                records.append(text)
        return records

    @staticmethod
    def _openapi_chunks(path: Path) -> list[KnowledgeChunk]:
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        result = []
        for ordinal, (route, operations) in enumerate(spec.get("paths", {}).items()):
            for method, operation in operations.items():
                if method.lower() not in {"get", "post", "patch", "put", "delete"}:
                    continue
                details = [f"{method.upper()} {route}", operation.get("summary", ""),
                           operation.get("description", "")]
                for parameter in operation.get("parameters", []):
                    details.append(f"Параметр {parameter.get('name', '')}: "
                                   f"{parameter.get('description', '')}")
                responses = ", ".join(operation.get("responses", {}))
                details.append(f"HTTP responses: {responses}")
                result.append(KnowledgeChunk(
                    text="; ".join(part for part in details if part),
                    source=path.as_posix(), section=f"{method.upper()} {route}",
                    ordinal=ordinal, source_status="api_contract",
                ))
        return result

    def search(self, question: str, limit: int = 5) -> list[dict]:
        raw_terms = set(self._tokens(question))
        query_terms = set(raw_terms)
        for term in raw_terms:
            query_terms.update(QUERY_SYNONYMS.get(term, ()))
        if not query_terms:
            return []
        docs = [(chunk, self._tokens(chunk.text)) for chunk in self.chunks]
        df: dict[str, int] = {}
        for _, terms in docs:
            for term in set(terms):
                df[term] = df.get(term, 0) + 1
        average_length = sum(len(terms) for _, terms in docs) / max(1, len(docs))
        ranked = []
        for chunk, terms in docs:
            frequencies = {term: terms.count(term) for term in set(terms)}
            overlap = query_terms & frequencies.keys()
            if not overlap:
                continue
            coverage = len(overlap) / len(query_terms)
            norm = 1.2 * (0.25 + 0.75 * len(terms) / max(1, average_length))
            score = 0.0
            for term in overlap:
                idf = math.log(1 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
                tf = frequencies[term]
                score += idf * (tf * 2.2) / (tf + norm)
            lowered = self._normalize(chunk.text)
            if "ответ-скрипт" in lowered:
                score += 2.0
            if "вопрос (варианты)" in lowered:
                score += 1.0
            if "действие:" in lowered:
                score += 0.25
            ranked.append((score, coverage, chunk))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2].ordinal))
        return [
            {**chunk.as_dict(), "score": round(score, 3),
             "coverage": round(coverage, 3),
             "matched_terms": sorted(query_terms & set(self._tokens(chunk.text))),
             "supported": bool(query_terms & set(self._tokens(chunk.text)))}
            for score, coverage, chunk in ranked[:max(1, min(limit, 10))]
        ]

    def answer(self, question: str, limit: int = 3) -> dict:
        matches = [
            hit for hit in self.search(question, max(limit, 10))
            if hit["supported"]
        ]
        query_terms = set(self._tokens(question))
        discriminative = query_terms - GENERIC_TERMS
        if discriminative:
            matches = [
                hit for hit in matches
                if discriminative.intersection(hit["matched_terms"])
            ]
        authoritative = [
            hit for hit in matches
            if hit["source_status"] == "patient_reference"
        ]
        if not authoritative:
            conditional = [
                hit for hit in matches if hit["source_status"] == "conditional_example"
            ]
            if conditional:
                return {
                    "found": False,
                    "answer": (
                        "Найдены только условные справочные значения; подтверждение "
                        "по актуальной МИС требуется от регистратора."
                    ),
                    "sources": conditional,
                    "grounded": False,
                    "requires_verification": True,
                }
            return {
                "found": False,
                "answer": "В локальной базе знаний подтверждённый ответ не найден. Передам вопрос оператору.",
                "sources": [],
                "grounded": False,
            }
        dynamic_topics = {
            "адрес", "режим", "работ", "график", "стоимос", "цен", "анализ",
            "результат", "телефон", "контакт", "кабинет", "расписан", "врач",
            "суббот", "воскрес", "праздник", "сегодня", "сейчас", "завтра",
        }
        normalized_question = self._normalize(question)
        dynamic = bool(query_terms & dynamic_topics) or any(
            phrase in normalized_question
            for phrase in ("сколько стоит", "какая цена", "сегодня", "сейчас", "завтра")
        )
        if dynamic:
            evidence = [
                hit for hit in authoritative
                if hit["section"] and hit["section"].startswith("6.")
            ]
            if not evidence:
                evidence = authoritative
            return {
                "found": False,
                "answer": (
                    "В документах есть справочная информация, но её актуальность "
                    "должна подтверждаться по МИС/справочнику. Передам вопрос регистратору."
                ),
                "sources": evidence[:limit],
                "grounded": False,
                    "requires_verification": True,
                    "retrieval": self._retrieval_diagnostics(question, matches),
                }
        # Для ответа пациенту предпочитаем готовый FAQ-скрипт, а не заголовок,
        # требования к инструментам или пример разговора из другого сценария.
        scripts = [
            hit for hit in authoritative
            if hit["section"] and hit["section"].startswith("6.")
            and "ответ-скрипт:" in self._normalize(hit["text"])
            and not re.search(r"\[[^\]]+\]", hit["text"])
            and not any(marker in hit["text"] for marker in ("…", "..."))
        ]
        if "что взять" in normalized_question or "взять с собой" in normalized_question:
            scripts = [
                hit for hit in scripts
                if "что взять с собой на прием" in self._normalize(hit["text"])
            ]
        if any(term in query_terms for term in {"запис", "записан", "разговор"}):
            # Согласие на запись разговора — отдельная политика, не отмена
            # медицинской записи.
            recording = [
                hit for hit in authoritative
                if hit["section"] and hit["section"].startswith("3.4.")
                and "отключ" in self._normalize(hit["text"])
            ]
            if recording:
                scripts = recording
        # Placeholder price, non-clinic-specific values and incomplete scripts
        # are not answers.
        if any(term in query_terms for term in {"стоимос", "цен"}):
            scripts = [
                hit for hit in scripts
                if not re.search(r"\[цена|прайс|справочник", hit["text"], re.I)
            ]
        if not scripts:
            return {
                "found": False,
                "answer": "Точного подтверждённого скрипта в базе знаний не найдено. Передам вопрос оператору.",
                "sources": authoritative[:limit],
                "grounded": False,
                "retrieval": self._retrieval_diagnostics(question, matches),
            }
        best = scripts[0]
        script_match = re.search(r"ответ-скрипт:\s*«(.*?)»", best["text"], re.I)
        if not script_match:
            script_match = re.search(r"ответ-скрипт:\s*(.*?)(?:\s*\|\s*действие:|$)",
                                     best["text"], re.I)
        answer = script_match.group(1).strip() if script_match else best["text"]
        return {
            "found": True,
            "answer": answer,
            "sources": [best],
            "grounded": True,
            "retrieval": self._retrieval_diagnostics(question, matches),
        }

    def _retrieval_diagnostics(self, question: str, hits: list[dict]) -> dict:
        return {
            "mode": "local_lexical_bm25_extract",
            "query_terms": sorted(set(self._tokens(question))),
            "candidates_considered": len(hits),
            "ranked_candidates": [
                {
                    "source": hit["source"],
                    "section": hit["section"],
                    "score": hit["score"],
                    "coverage": hit["coverage"],
                    "source_status": hit["source_status"],
                }
                for hit in hits[:5]
            ],
        }

    def manifest(self) -> dict:
        statuses = sorted({chunk.source_status for chunk in self.chunks})
        return {
            "documents": sorted({chunk.source for chunk in self.chunks}),
            "chunks": len(self.chunks),
            "mode": "extractive-local-rag",
            "status_counts": {
                status: sum(chunk.source_status == status for chunk in self.chunks)
                for status in statuses
            },
        }
