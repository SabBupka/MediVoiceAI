from datetime import date
import re


class DialogueEngine:
    """Безопасный rule-based слой до подключения локальной LLM."""

    EMERGENCY = ("острая боль", "сильно болит", "давит в груди", "не могу дышать", "теряю сознание")
    MEDICAL = (
        "что выпить",
        "мне выпить",
        "какие таблетки",
        "какое лекарство",
        "что принимать",
        "какой диагноз",
    )

    def handle(self, text: str) -> dict:
        normalized = text.lower().strip()
        if any(x in normalized for x in self.EMERGENCY):
            return self._escalate("Возможное неотложное состояние")
        if any(x in normalized for x in self.MEDICAL):
            return self._escalate("Запрос медицинской консультации")
        if "соедин" in normalized and ("челов" in normalized or "оператор" in normalized):
            return self._escalate("Пациент запросил оператора")
        if any(x in normalized for x in ("пожаловаться", "жалоба")):
            return self._escalate("Жалоба пациента")
        if "отмен" in normalized:
            return {"intent": "cancel", "response": "Проверю ваши активные записи для отмены."}
        if "перенес" in normalized or "перенести" in normalized:
            return {"intent": "reschedule", "response": "Проверю запись и доступные новые слоты."}
        if "когда запис" in normalized or "моя запись" in normalized:
            return {"intent": "status", "response": "Проверю ваши запланированные записи."}
        if any(x in normalized for x in (
            "режим работы", "график работы", "стоимость", "цена",
            "готовы анализы", "готовность анализов", "адрес",
        )):
            return {"intent": "info", "response": "Проверю информацию в регламенте клиники."}
        if any(x in normalized for x in (
            "запис", "приём", "прием", "терапевт", "педиатр",
            "гинеколог", "кардиолог", "лор",
        )):
            return {"intent": "booking", "response": "Помогу с записью. Назовите специальность врача."}
        return {
            "intent": "unknown",
            "response": (
                "Я помогу с записью, переносом, отменой или справочной информацией. "
                "Что именно вас интересует?"
            ),
        }

    @staticmethod
    def find_specialty(text: str, doctors: list[dict]) -> str | None:
        normalized = text.lower().replace("ё", "е")
        aliases = {
            "лор": ("лор", "оториноларинголог"),
            "гинеколог": ("гинеколог", "акушер"),
            "терапевт": ("терапевт",),
            "педиатр": ("педиатр",),
            "кардиолог": ("кардиолог",),
        }
        for specialty in {d["specialty"] for d in doctors}:
            variants = aliases.get(specialty, (specialty,))
            if any(variant in normalized for variant in variants):
                return specialty
        return None

    @staticmethod
    def extract_identity(text: str) -> dict | None:
        parsed = DialogueEngine._parse_date(text, require_year=True)
        if not parsed:
            return None
        birth_date, date_start, _ = parsed
        words = re.findall(r"[А-Яа-яЁё-]{2,}", text[:date_start])
        trailing_fillers = {
            "родился", "родилась", "родился,", "родилась,", "рождения",
            "дата", "числа", "года", "год", "в", "день",
        }
        words = [
            word for word in words
            if word.lower() not in {
                "я", "меня", "зовут", "это", "пациент", "пациентка",
                *trailing_fillers,
            }
        ]
        if len(words) < 2:
            return None
        if len(words) >= 3:
            return {
                "last_name": words[-3],
                "first_name": words[-2],
                "middle_name": words[-1],
                "birth_date": birth_date,
            }
        return {"last_name": words[-2], "first_name": words[-1], "birth_date": birth_date}

    @staticmethod
    def _parse_date(text: str, require_year: bool = False):
        match = re.search(r"\b([0-3]?\d)[./-]([01]?\d)(?:[./-](\d{4}))?\b", text)
        if match and (match.group(3) or not require_year):
            year = int(match.group(3)) if match.group(3) else date.today().year
            try:
                value = date(year, int(match.group(2)), int(match.group(1)))
                if not match.group(3) and value < date.today():
                    value = date(year + 1, value.month, value.day)
                return value.strftime("%d.%m.%Y"), match.start(), match.end()
            except ValueError:
                return None
        months = (
            "января|февраля|марта|апреля|мая|июня|июля|августа|"
            "сентября|октября|ноября|декабря"
        )
        day_words = {
            "первого": 1, "первое": 1, "первый": 1,
            "второго": 2, "второе": 2, "второй": 2,
            "третьего": 3, "третье": 3, "третий": 3,
            "четвертого": 4, "четвертое": 4, "четвертый": 4,
            "четвёртого": 4, "четвёртое": 4, "четвёртый": 4,
            "пятого": 5, "пятое": 5, "шестого": 6, "шестое": 6,
            "седьмого": 7, "седьмое": 7, "восьмого": 8, "восьмое": 8,
            "девятого": 9, "девятое": 9, "десятого": 10, "десятое": 10,
            "одиннадцатого": 11, "одиннадцатое": 11,
            "двенадцатого": 12, "двенадцатое": 12,
            "тринадцатого": 13, "тринадцатое": 13,
            "четырнадцатого": 14, "четырнадцатое": 14,
            "пятнадцатого": 15, "пятнадцатое": 15,
            "шестнадцатого": 16, "шестнадцатое": 16,
            "семнадцатого": 17, "семнадцатое": 17,
            "восемнадцатого": 18, "восемнадцатое": 18,
            "девятнадцатого": 19, "девятнадцатое": 19,
            "двадцатого": 20, "двадцатое": 20,
            "двадцать первого": 21, "двадцать первое": 21,
            "двадцать второго": 22, "двадцать второе": 22,
            "двадцать третьего": 23, "двадцать третье": 23,
            "двадцать четвертого": 24, "двадцать четвертое": 24,
            "двадцать четвёртого": 24, "двадцать четвёртое": 24,
            "двадцать пятого": 25, "двадцать пятое": 25,
            "двадцать шестого": 26, "двадцать шестое": 26,
            "двадцать седьмого": 27, "двадцать седьмое": 27,
            "двадцать восьмого": 28, "двадцать восьмое": 28,
            "двадцать девятого": 29, "двадцать девятое": 29,
            "тридцатого": 30, "тридцатое": 30,
            "тридцать первого": 31, "тридцать первое": 31,
        }
        day_pattern = "|".join(
            re.escape(word) for word in sorted(day_words, key=len, reverse=True)
        )
        spoken_year = (
            r"(?:\d{4}|"
            r"(?:одна\s+)?тысяча\s+девятьсот\s+"
            r"(?:десятого|одиннадцатого|двенадцатого|тринадцатого|"
            r"четырнадцатого|пятнадцатого|шестнадцатого|семнадцатого|"
            r"восемнадцатого|девятнадцатого|двадцатого|тридцатого|"
            r"сорокового|пятидесятого|шестидесятого|семидесятого|"
            r"восьмидесятого|девяностого|"
            r"(?:двадцать|тридцать|сорок|пятьдесят|шестьдесят|семьдесят|"
            r"восемьдесят|девяносто)\s+"
            r"(?:первого|второго|третьего|четвертого|четвёртого|пятого|"
            r"шестого|седьмого|восьмого|девятого))|"
            r"две\s+тысячи\s+"
            r"(?:первого|второго|третьего|четвертого|четвёртого|пятого|"
            r"шестого|седьмого|восьмого|девятого|десятого|одиннадцатого|"
            r"двенадцатого|тринадцатого|четырнадцатого|пятнадцатого|"
            r"шестнадцатого|семнадцатого|восемнадцатого|девятнадцатого|"
            r"двадцатого|двадцать\s+(?:первого|второго|третьего|четвертого|"
            r"четвёртого|пятого|шестого|седьмого|восьмого|девятого)))"
        )
        spoken = re.search(
            rf"\b(\d{{1,2}}|{day_pattern})\s+({months})"
            rf"(?:\s+({spoken_year}))?(?:\s+года?)?\b",
            text.lower(),
        )
        if not spoken or (not spoken.group(3) and require_year):
            return None
        day = int(spoken.group(1)) if spoken.group(1).isdigit() else day_words[spoken.group(1)]
        month = {
            "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
            "мая": 5, "июня": 6, "июля": 7, "августа": 8,
            "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
        }[spoken.group(2)]
        year = (
            DialogueEngine._parse_spoken_year(spoken.group(3))
            if spoken.group(3) else date.today().year
        )
        if year is None:
            return None
        try:
            value = date(year, month, day)
            if not spoken.group(3) and value < date.today():
                value = date(year + 1, month, day)
            return value.strftime("%d.%m.%Y"), spoken.start(), spoken.end()
        except ValueError:
            return None

    @staticmethod
    def _parse_spoken_year(value: str) -> int | None:
        normalized = value.lower().replace("ё", "е").strip()
        if normalized.isdigit():
            return int(normalized)
        unit = {
            "первого": 1, "второго": 2, "третьего": 3, "четвертого": 4,
            "четвёртого": 4, "пятого": 5, "шестого": 6, "седьмого": 7,
            "восьмого": 8, "девятого": 9,
        }
        teens = {
            "десятого": 10, "одиннадцатого": 11, "двенадцатого": 12,
            "тринадцатого": 13, "четырнадцатого": 14, "пятнадцатого": 15,
            "шестнадцатого": 16, "семнадцатого": 17, "восемнадцатого": 18,
            "девятнадцатого": 19,
        }
        tens = {
            "двадцатого": 20, "тридцатого": 30, "сорокового": 40,
            "пятидесятого": 50, "шестидесятого": 60, "семидесятого": 70,
            "восьмидесятого": 80, "девяностого": 90,
            "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
            "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80,
            "девяносто": 90,
        }
        if normalized.startswith(("тысяча девятьсот ", "одна тысяча девятьсот ")):
            base = 1900
            prefix = (
                "одна тысяча девятьсот "
                if normalized.startswith("одна тысяча")
                else "тысяча девятьсот "
            )
            tail = normalized.removeprefix(prefix).split()
        elif normalized.startswith("две тысячи "):
            base, tail = 2000, normalized.removeprefix("две тысячи ").split()
        else:
            return None
        if len(tail) == 1:
            offset = teens.get(tail[0], tens.get(tail[0], unit.get(tail[0])))
            return base + offset if offset is not None else None
        if len(tail) == 2 and tail[0] in tens and tail[1] in unit:
            return base + tens[tail[0]] + unit[tail[1]]
        return None

    @staticmethod
    def extract_spoken_date(text: str, allow_yearless: bool = False) -> str | None:
        parsed = DialogueEngine._parse_date(text, require_year=not allow_yearless)
        return parsed[0] if parsed else None

    @staticmethod
    def confirmation_text(identity: dict) -> str:
        months = (
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря",
        )
        day, month, year = map(int, identity["birth_date"].split("."))
        day_words = {
            1: "первого", 2: "второго", 3: "третьего", 4: "четвёртого",
            5: "пятого", 6: "шестого", 7: "седьмого", 8: "восьмого",
            9: "девятого", 10: "десятого", 11: "одиннадцатого",
            12: "двенадцатого", 13: "тринадцатого", 14: "четырнадцатого",
            15: "пятнадцатого", 16: "шестнадцатого", 17: "семнадцатого",
            18: "восемнадцатого", 19: "девятнадцатого", 20: "двадцатого",
            21: "двадцать первого", 22: "двадцать второго",
            23: "двадцать третьего", 24: "двадцать четвёртого",
            25: "двадцать пятого", 26: "двадцать шестого",
            27: "двадцать седьмого", 28: "двадцать восьмого",
            29: "двадцать девятого", 30: "тридцатого", 31: "тридцать первого",
        }
        name = " ".join(
            part for part in (
                identity.get("last_name"), identity.get("first_name"),
                identity.get("middle_name"),
            ) if part
        )
        return (
            f"Подтвердите, пожалуйста: {name}, дата рождения — "
            f"{day_words.get(day, str(day))} {months[month - 1]} "
            f"{year} года? Скажите «да» или «нет»."
        )

    @staticmethod
    def choice_index(text: str, count: int) -> int | None:
        numeric = DialogueEngine.extract_choice(text, count)
        if numeric:
            return numeric - 1
        normalized = text.lower().replace("ё", "е")
        words = {
            0: (r"\bперв(?:ый|ая|ое|ого|ую|ым|ом)?\b", r"\bодин\b", r"\bодну\b"),
            1: (r"\bвтор(?:ой|ая|ое|ого|ую|ым|ом)?\b", r"\bдва\b", r"\bдве\b"),
            2: (r"\bтрет(?:ий|ья|ье|ьего|ью|ьим)?\b", r"\bтри\b"),
        }
        for index, variants in words.items():
            if index < count and any(re.search(pattern, normalized) for pattern in variants):
                return index
        return None

    @staticmethod
    def is_confirmation(text: str) -> bool | None:
        normalized = text.lower().replace("ё", "е").strip()
        # Speech recognizers and keypad-driven demos may return a digit.
        if normalized in {"1", "1.", "один", "одна"}:
            return True
        if normalized in {"2", "2.", "два", "две"}:
            return False
        if re.search(r"\b(нет|неверно|неправильно|ошибка)\b", normalized):
            return False
        if re.search(r"\b(да|верно|правильно|подтверждаю|ага|угу)\b", normalized):
            return True
        return None

    @staticmethod
    def extract_choice(text: str, count: int) -> int | None:
        match = re.search(r"\b([1-9]\d*)\b", text)
        if not match:
            return None
        choice = int(match.group(1))
        return choice if 1 <= choice <= count else None

    @staticmethod
    def format_scheduled_for_speech(value: str) -> str:
        day, month, year_time = value.split(".")
        year, time_text = year_time.split(" ")
        month_names = (
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря",
        )
        day_number = int(day)
        day_words = {
            1: "первого", 2: "второго", 3: "третьего", 4: "четвёртого",
            5: "пятого", 6: "шестого", 7: "седьмого", 8: "восьмого",
            9: "девятого", 10: "десятого", 11: "одиннадцатого",
            12: "двенадцатого", 13: "тринадцатого", 14: "четырнадцатого",
            15: "пятнадцатого", 16: "шестнадцатого", 17: "семнадцатого",
            18: "восемнадцатого", 19: "девятнадцатого", 20: "двадцатого",
            21: "двадцать первого", 22: "двадцать второго",
            23: "двадцать третьего", 24: "двадцать четвёртого",
            25: "двадцать пятого", 26: "двадцать шестого",
            27: "двадцать седьмого", 28: "двадцать восьмого",
            29: "двадцать девятого", 30: "тридцатого", 31: "тридцать первого",
        }
        return f"{day_words.get(day_number, str(day_number))} {month_names[int(month) - 1]}, в {time_text}"

    @staticmethod
    def _escalate(reason: str) -> dict:
        emergency_phrases = (
            "неотложное состояние",
            "острая боль",
            "давит в груди",
            "не могу дышать",
            "теряю сознание",
        )
        if any(phrase in reason.lower() for phrase in emergency_phrases):
            response = (
                "Если состояние угрожает жизни, позвоните 103 или 112. "
                "Сейчас передам разговор сотруднику регистратуры."
            )
        else:
            response = "Сейчас передам разговор сотруднику регистратуры."
        return {
            "intent": "escalation",
            "response": response,
            "reason": reason,
        }
