"""Загрузка и нормализация данных рекламной таблицы Форсайт.

Источник - Google Sheets клиента, доступ «всем, у кого есть ссылка» (только чтение).
GID вкладок собраны здесь в одном месте: меняется таблица - меняется только этот файл.

ID самой таблицы берётся из секретов (`sheet_id`), с запасным значением в коде для
локального запуска. Смысл: код уезжает в GitHub, а ссылка на данные клиента - нет.
"""

from __future__ import annotations

import io
import re

import pandas as pd
import requests

DEFAULT_SHEET_ID = "1T_PjrLQt5XeNIkD95zzRAWYWo4T5zOq_sIdFzQp2r5U"


def sheet_id() -> str:
    """ID таблицы: из секретов, иначе запасной из кода."""
    try:
        import streamlit as st

        if "sheet_id" in st.secrets:
            return str(st.secrets["sheet_id"])
    except Exception:
        pass
    return DEFAULT_SHEET_ID

GID = {
    "dannye": 1588060700,
    "stoimost_dogovora": 1408424911,
    "grafiki": 2143800596,
}

# Понедельные «Сводные» - по одному листу на год.
GID_SVODNAYA = {
    2024: 0,
    2025: 1570880931,
    2026: 603543607,
}

EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

MONTHS = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]

# Родительный падеж - так месяц записан в подписи недели («1-4 января»).
# Отдельная таблица, а не MONTHS[:4] - у «май/мая» общий префикс всего 2 буквы.
MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

WEEK_LABEL_RE = re.compile(r"\d+\s*[-–]\s*\d+")

# Заголовки листа «Данные» -> короткие имена колонок.
# Ищем по тексту заголовка, а не по индексу: в таблице колонки двигают.
COLUMNS = {
    "Просмотры Я": "direct_pokazy",
    "Клики Я": "direct_kliki",
    "Я_контекст_CTR": "direct_ctr",
    "Договоры Яндекс": "direct_dogovory",
    "Просмотры_Карты Я": "karty_pokazy",
    "Клики_Карты Я": "karty_kliki",
    "CTR_Карты Я": "karty_ctr",
    "Договоры_Карты Я": "karty_dogovory",
    "Просмотры 2Гис": "gis_pokazy",
    "Клики 2Гис": "gis_kliki",
    "CTR_2Гис": "gis_ctr",
    "Договоры 2Гис": "gis_dogovory",
    "Договоры Гугл": "google_dogovory",
    "Количество договоров (План)": "plan",
    "Количество договоров (Факт)": "fakt",
    # Воронка на листе записана в единственном числе - «Звонок», «Заявка».
    "Звонок": "zvonki",
    "Звонок с места ДТП": "zvonki_dtp",
    "Заявка": "zayavki",
}

CHANNELS = {
    "Яндекс.Директ": ("direct_pokazy", "direct_kliki", "direct_ctr", "direct_dogovory"),
    "Яндекс.Карты": ("karty_pokazy", "karty_kliki", "karty_ctr", "karty_dogovory"),
    "2ГИС": ("gis_pokazy", "gis_kliki", "gis_ctr", "gis_dogovory"),
}


class SheetUnavailable(RuntimeError):
    """Таблица недоступна: нет сети, закрыли доступ или сменился ID."""


def fetch_csv(gid: int, timeout: int = 30) -> str:
    """Скачать вкладку как CSV. Бросает SheetUnavailable с понятным текстом."""
    url = EXPORT_URL.format(sheet_id=sheet_id(), gid=gid)
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise SheetUnavailable(f"Не смогли достучаться до таблицы: {exc}") from exc

    # Google не всегда присылает charset, а requests тогда угадывает latin-1 и ломает кириллицу.
    resp.encoding = "utf-8"

    if resp.status_code != 200:
        raise SheetUnavailable(
            f"Google вернул {resp.status_code} для вкладки gid={gid}. "
            "Скорее всего закрыт доступ по ссылке или вкладка удалена."
        )
    if resp.text.lstrip().startswith("<!DOCTYPE html"):
        raise SheetUnavailable(
            f"Вместо данных пришла HTML-страница (gid={gid}). "
            "Такое бывает у листов-диаграмм - у них нет CSV-выгрузки."
        )
    return resp.text


def to_number(value) -> float | None:
    """'1 234,5' -> 1234.5; '#DIV/0!', '', None -> None."""
    if value is None or isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip().replace("\xa0", "").replace(" ", "")
    text = text.replace("%", "").replace("₽", "").replace(",", ".")
    if text in ("", "-", "#DIV/0!", "#VALUE!", "#REF!", "#N/A"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_month(value: str) -> int | None:
    """'09сентябрь', '01 январь' -> 9, 1. В таблице месяцы записаны неровно."""
    text = str(value).strip().lower()
    for i, name in enumerate(MONTHS, start=1):
        if name in text:
            return i
    return None


def load_dannye() -> pd.DataFrame:
    """Лист «Данные» - помесячная история 2024-2026 по каналам.

    Возвращает длинный аккуратный DataFrame: одна строка = один месяц.
    """
    raw = pd.read_csv(io.StringIO(fetch_csv(GID["dannye"])), header=None, dtype=str)

    header_row = _find_header_row(raw)
    header = [str(x).strip() for x in raw.iloc[header_row].tolist()]

    positions: dict[str, int] = {}
    for title, name in COLUMNS.items():
        for i, cell in enumerate(header):
            if cell == title and name not in positions:
                positions[name] = i
                break

    missing = set(COLUMNS.values()) - set(positions)
    if missing:
        raise SheetUnavailable(
            "На листе «Данные» не нашлись колонки: "
            + ", ".join(sorted(missing))
            + ". Похоже, структуру таблицы поменяли - нужно обновить COLUMNS в loader.py."
        )

    rows = []
    for _, row in raw.iloc[header_row + 1:].iterrows():
        year = str(row.iloc[0]).strip()
        if not year.isdigit():
            continue
        month = parse_month(row.iloc[1])
        if month is None:
            continue
        record = {"god": int(year), "mes_num": month, "mes": MONTHS[month - 1]}
        for name, idx in positions.items():
            record[name] = to_number(row.iloc[idx]) if idx < len(row) else None
        rows.append(record)

    df = pd.DataFrame(rows)
    if df.empty:
        raise SheetUnavailable("Лист «Данные» пустой - проверь таблицу.")

    df["period"] = df["god"].astype(str) + "-" + df["mes_num"].astype(str).str.zfill(2)
    df["dolya_dtp"] = _safe_ratio(df["zvonki_dtp"], df["zvonki"]) * 100
    df["conv_zayavka_dogovor"] = _safe_ratio(df["fakt"], df["zayavki"]) * 100
    df["proc_plana"] = _safe_ratio(df["fakt"], df["plan"]) * 100
    return df.sort_values(["god", "mes_num"]).reset_index(drop=True)


def load_stoimost() -> pd.DataFrame:
    """Лист «Стоимость договора_25/26» - цена договора по каналам, помесячно.

    Структура листа: блок на год, первая ячейка строки-шапки - сам год.
    """
    raw = pd.read_csv(
        io.StringIO(fetch_csv(GID["stoimost_dogovora"])), header=None, dtype=str
    )

    rows = []
    year: int | None = None
    for _, row in raw.iterrows():
        first = str(row.iloc[0]).strip()
        if first.isdigit() and len(first) == 4:
            year = int(first)
            continue
        if first in ("", "nan"):
            # Внизу листа лежит дубль-блок с шапкой без года: там две строки «Дубльгис»
            # (2025 и 2026), различить их можно только по порядку. Не угадываем -
            # сбрасываем год, и всё, что ниже, игнорируется. Расхождение занесено
            # в reklama-tablica-oshibki.md.
            if any("январь" in str(x).strip().lower() for x in row.tolist()):
                year = None
            continue
        if year is None:
            continue
        for i in range(1, min(13, len(row))):
            price = to_number(row.iloc[i])
            if price is not None:
                rows.append(
                    {"god": year, "mes_num": i, "mes": MONTHS[i - 1],
                     "kanal": first, "stoimost": price}
                )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Ниже основного блока лист дублирует «Дубльгис» без указания года - убираем дубли.
    df = df.drop_duplicates(subset=["god", "mes_num", "kanal"], keep="first")
    df["period"] = df["god"].astype(str) + "-" + df["mes_num"].astype(str).str.zfill(2)
    return df.sort_values(["god", "mes_num"]).reset_index(drop=True)


WEEK_FIELDS = {
    # Ищем по подстроке, самые специфичные варианты - выше по списку.
    "звонки с места": "zvonki_dtp",
    "доля звонков": None,  # пересчитываем сами, не берём готовую ячейку
    "конверси": None,  # лишняя колонка, встречается только в марте 2026
    "заявк": "zayavki",
    "договор": "dogovory",
    "показы": "pokazy",
    "клики": "kliki",
    "звонк": "zvonki",  # «Звонок» / «Звонки» - самый общий вариант, проверяем последним
}


def _classify_week_field(header_text: str) -> str | None:
    """Текст ячейки шапки недели -> короткое имя поля, либо None (CTR и т.п. пропускаем)."""
    text = header_text.strip().lower()
    if not text or "ctr" in text:
        return None
    for needle, name in WEEK_FIELDS.items():
        if needle in text:
            return name
    return None


def _parse_week_label(label: str) -> tuple[str, int | None]:
    """'1-4 января' -> ('1-4 января', 1). Месяц не нашёлся -> (label, None)."""
    text = label.strip()
    low = text.lower()
    for i, name in enumerate(MONTHS_GENITIVE, start=1):
        if name in low:
            return text, i
    return text, None


def _iter_week_blocks(raw: pd.DataFrame):
    """Обойти листы «Сводная» блок за блоком.

    Отдаёт кортежи (label, mes_num, fields, totals_row, channel_rows), где fields -
    словарь «короткое имя поля -> номер колонки» для конкретной недели.

    Структура листа плавает (набор колонок и наличие строки «ИТОГО:» меняются от года
    к году и от месяца к месяцу), поэтому не полагаемся на фиксированные индексы: ищем
    блок недели по тексту «Показы» в шапке, поле - по тексту ячейки.
    """
    n_rows = len(raw)
    i = 0
    while i < n_rows - 1:
        date_row = raw.iloc[i].tolist()
        header_row = raw.iloc[i + 1].tolist()
        if not any(cell.strip().lower() == "показы" for cell in header_row):
            i += 1
            continue

        block_starts = [j for j, cell in enumerate(header_row) if cell.strip().lower() == "показы"]

        # Строка «ИТОГО:» - готовые суммы по компании; если её нет (бывает в 2024),
        # считаем сами по строкам-каналам между шапкой и следующим блоком месяца.
        totals_row, channel_rows, k = None, [], i + 2
        while k < n_rows:
            first = raw.iloc[k, 0].strip()
            if first == "ИТОГО:":
                totals_row = raw.iloc[k].tolist()
                k += 1
                break
            if k + 1 < n_rows and any(
                c.strip().lower() == "показы" for c in raw.iloc[k + 1].tolist()
            ) and WEEK_LABEL_RE.search(raw.iloc[k, 1] if len(raw.iloc[k]) > 1 else ""):
                break  # начался следующий месяц без «ИТОГО:»
            channel_rows.append(raw.iloc[k].tolist())
            k += 1

        for bs in block_starts:
            be = min([b for b in block_starts if b > bs], default=len(header_row))
            label = date_row[bs].strip() if bs < len(date_row) else ""
            if not WEEK_LABEL_RE.search(label):
                continue  # последний блок месяца - это колонка «ИТОГО», не неделя

            fields = {}
            for offset, cell in enumerate(header_row[bs:be]):
                name = _classify_week_field(cell)
                if name and name not in fields:
                    fields[name] = bs + offset

            _, mes_num = _parse_week_label(label)
            yield label, mes_num, fields, totals_row, channel_rows

        i = k if totals_row is not None else i + 1


def _read_svodnaya(year: int) -> pd.DataFrame:
    if year not in GID_SVODNAYA:
        raise SheetUnavailable(f"Нет листа «Сводная» за {year} год - только {sorted(GID_SVODNAYA)}.")
    raw = pd.read_csv(io.StringIO(fetch_csv(GID_SVODNAYA[year])), header=None, dtype=str)
    return raw.fillna("")


def load_svodnaya_weeks(year: int) -> pd.DataFrame:
    """Понедельная «Сводная_<год>» - показатели по компании целиком, по неделям."""
    raw = _read_svodnaya(year)

    weeks = []
    for label, mes_num, fields, totals_row, channel_rows in _iter_week_blocks(raw):
        record = {
            "god": year,
            "week_label": label,
            "iz_itogo": totals_row is not None,
            "mes_num": mes_num,
            "mes": MONTHS[mes_num - 1] if mes_num else None,
        }
        for name, col in fields.items():
            if totals_row is not None:
                value = to_number(totals_row[col]) if col < len(totals_row) else None
            else:
                value = sum((to_number(r[col]) or 0) for r in channel_rows if col < len(r))
            record[name] = value
        weeks.append(record)

    df = pd.DataFrame(weeks)
    if df.empty:
        raise SheetUnavailable(f"На листе «Сводная_{year}» не нашлось ни одной недели.")

    for col in ("pokazy", "kliki", "zvonki", "zvonki_dtp", "zayavki", "dogovory"):
        if col not in df.columns:
            df[col] = None

    df["order"] = range(len(df))
    df["dolya_dtp"] = _safe_ratio(df["zvonki_dtp"], df["zvonki"]) * 100
    return df


# Названия каналов в таблице плавают: то с номером телефона, то без, хвосты меняются
# от месяца к месяцу. Сводим к каноническим - иначе один канал разъезжается на несколько.
# Порядок важен: проверяем сверху вниз по подстроке.
CHANNEL_ALIASES = [
    ("я.контекст", "Яндекс.Директ (поиск)"),
    ("я.рся", "Яндекс.РСЯ"),
    ("я.карты", "Яндекс.Карты"),
    ("прямые заходы", "Прямые заходы"),
    ("g.поиск", "Google"),
    ("g.карты", "Google"),
    ("2гис", "2ГИС"),
    ("медиа", "Медийная реклама"),
    ("юристы", "Юристы"),
    ("неопределенные", "Неопределённые"),
    ("самостоятельная", "Неопределённые"),
    ("входящий звонок", "Входящий звонок"),
    ("тестовый нейро", "Тестовый нейро"),
    ("max", "MAX"),
]


def normalize_channel(name: str) -> str | None:
    """'Я.Контекст (796911)' -> 'Яндекс.Директ (поиск)'. Пустая строка -> None."""
    text = name.strip()
    if not text or text == "ИТОГО:":
        return None
    low = text.lower()
    for needle, canonical in CHANNEL_ALIASES:
        if needle in low:
            return canonical
    return text  # незнакомый канал показываем как есть, а не прячем


def load_svodnaya_channels(year: int) -> pd.DataFrame:
    """Понедельные показатели в разрезе каналов: показы, клики, звонки, заявки, договоры.

    Лист «Данные» знает только три канала, а «Сводная» - все тринадцать, включая РСЯ,
    прямые заходы, медийную рекламу, юристов и неопределённые обращения.
    """
    raw = _read_svodnaya(year)

    rows = []
    for label, mes_num, fields, _totals, channel_rows in _iter_week_blocks(raw):
        for channel_row in channel_rows:
            channel = normalize_channel(channel_row[0] if channel_row else "")
            if channel is None:
                continue
            record = {
                "god": year,
                "week_label": label,
                "mes_num": mes_num,
                "mes": MONTHS[mes_num - 1] if mes_num else None,
                "kanal": channel,
            }
            for name, col in fields.items():
                record[name] = to_number(channel_row[col]) if col < len(channel_row) else None
            rows.append(record)

    df = pd.DataFrame(rows)
    if df.empty:
        raise SheetUnavailable(f"На листе «Сводная_{year}» не нашлось строк-каналов.")

    for col in ("pokazy", "kliki", "zvonki", "zvonki_dtp", "zayavki", "dogovory"):
        if col not in df.columns:
            df[col] = None

    # Один канал может встречаться в блоке дважды (разные хвосты названия) - складываем.
    df = (
        df.groupby(["god", "mes_num", "mes", "week_label", "kanal"], as_index=False, sort=False)
        .sum(numeric_only=True)
    )
    df["ctr"] = _safe_ratio(df["kliki"], df["pokazy"]) * 100
    df["order"] = range(len(df))
    return df


def _find_header_row(raw: pd.DataFrame, limit: int = 5) -> int:
    """Шапка - первая строка, где встречается «Количество договоров (Факт)»."""
    for i in range(min(limit, len(raw))):
        cells = [str(x).strip() for x in raw.iloc[i].tolist()]
        if "Количество договоров (Факт)" in cells:
            return i
    raise SheetUnavailable(
        "На листе «Данные» не нашлась строка-шапка с «Количество договоров (Факт)»."
    )


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Деление без предупреждений и без inf: ноль в знаменателе -> NaN."""
    denom = denominator.replace(0, pd.NA)
    return numerator / denom
