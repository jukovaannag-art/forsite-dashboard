"""Блоки дашборда, общие для внутренней и клиентской версии.

Разница между версиями - только в подписях: во внутренней есть прямые указания на дефекты
таблицы и ссылки на файлы репозитория, в клиентской - нейтральные пояснения. Логика и цифры
одинаковые, чтобы версии не разъехались.

Флаг `internal` прокидывается из приложения: True - для Анны, False - для клиента.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import loader

CACHE_TTL = 30 * 60

COLOR = {
    "plan": "#94a3b8",
    "fakt": "#0f766e",
    "alert": "#dc2626",
    "Яндекс.Директ": "#dc2626",
    "Яндекс.Карты": "#f59e0b",
    "2ГИС": "#0f766e",
    "Google": "#6366f1",
}

# С этого периода в таблице сменилась методика учёта договоров по каналам.
METHOD_CHANGE = "2026-03"

YOY_METRICS = {
    "Договоры": ("fakt", 0),
    "Звонки": ("zvonki", 0),
    "Звонки с места ДТП": ("zvonki_dtp", 0),
    "Заявки": ("zayavki", 0),
    "Доля звонков с места ДТП, %": ("dolya_dtp", 1),
}

WEEK_METRICS = {
    "Договоры": "dogovory",
    "Звонки": "zvonki",
    "Заявки": "zayavki",
    "Показы": "pokazy",
    "Клики": "kliki",
}


@st.cache_data(ttl=CACHE_TTL, show_spinner="Читаем таблицу...")
def get_dannye() -> pd.DataFrame:
    return loader.load_dannye()


@st.cache_data(ttl=CACHE_TTL, show_spinner="Читаем стоимость договора...")
def get_stoimost() -> pd.DataFrame:
    return loader.load_stoimost()


@st.cache_data(ttl=CACHE_TTL, show_spinner="Читаем понедельные данные...")
def get_weeks(year: int) -> pd.DataFrame:
    return loader.load_svodnaya_weeks(year)


@st.cache_data(ttl=CACHE_TTL, show_spinner="Читаем данные по каналам...")
def get_channels(year: int) -> pd.DataFrame:
    return loader.load_svodnaya_channels(year)


def channels_or_none(year: int) -> pd.DataFrame | None:
    try:
        return get_channels(year)
    except loader.SheetUnavailable:
        return None


def weeks_or_none(year: int) -> pd.DataFrame | None:
    """Недели - дополнение, а не основа: их отсутствие не должно ронять весь дашборд."""
    try:
        return get_weeks(year)
    except loader.SheetUnavailable:
        return None


def closed_months(df: pd.DataFrame, today: date | None = None) -> pd.DataFrame:
    """Только завершённые месяцы с данными.

    Исключаем и незаполненные будущие месяцы, и текущий - он ещё идёт. Иначе KPI
    сравнивает неполный месяц с полным месяцем прошлого года и показывает провал,
    которого нет. Плюс данные за идущий месяц вносятся вразнобой: в августе 2026
    договоров внесено 316 при 278 заявках, то есть «конверсия 114%».
    """
    today = today or date.today()
    filled = df[(df["fakt"].fillna(0) > 0) & (df["zvonki"].fillna(0) > 0)]
    return filled[
        (filled["god"] < today.year)
        | ((filled["god"] == today.year) & (filled["mes_num"] < today.month))
    ]


def current_month(df: pd.DataFrame, today: date | None = None) -> pd.Series | None:
    """Строка за идущий месяц, если данные по нему уже вносят."""
    today = today or date.today()
    rows = df[
        (df["god"] == today.year)
        & (df["mes_num"] == today.month)
        & (df["fakt"].fillna(0) > 0)
    ]
    return rows.iloc[0] if not rows.empty else None


def ru(value: float, digits: int = 0) -> str:
    """Русское форматирование: пробел-разделитель тысяч, запятая - дробная часть."""
    text = f"{value:,.{digits}f}"
    return text.replace(",", " ").replace(".", ",")


def delta_text(current: float | None, previous: float | None, suffix: str = "") -> str | None:
    if current is None or previous is None or pd.isna(current) or pd.isna(previous):
        return None
    diff = current - previous
    return f"{'+' if diff >= 0 else '-'}{ru(abs(diff), 1 if suffix else 0)}{suffix}"


def metrics_row(items: list[tuple[str, float, float | None, int, str]]) -> None:
    """Одна строка метрик: (подпись, значение, база, знаков после запятой, суффикс)."""
    columns = st.columns(len(items))
    for column, (label, value, previous, digits, suffix) in zip(columns, items, strict=True):
        shown = f"{ru(value, digits)}{suffix}" if pd.notna(value) else "-"
        column.metric(label, shown, delta_text(value, previous, " п.п." if suffix == "%" else ""))


def _get(row: pd.Series | None, field: str):
    return None if row is None else row[field]


def kpi_block(closed: pd.DataFrame, weeks: pd.DataFrame | None, internal: bool = True) -> None:
    """KPI с выбором базы сравнения: год назад, месяц назад или неделя назад."""
    base = st.radio(
        "Сравнивать с",
        ["Тем же месяцем год назад", "Предыдущим месяцем", "Предыдущей неделей"],
        horizontal=True,
    )

    if base == "Предыдущей неделей":
        _kpi_weekly(weeks, internal)
        return

    last = closed.iloc[-1]
    if base == "Предыдущим месяцем":
        prev = closed.iloc[-2] if len(closed) >= 2 else None
        podpis = f"{last['mes']} {last['god']} против предыдущего месяца"
    else:
        year_ago = closed[
            (closed["god"] == last["god"] - 1) & (closed["mes_num"] == last["mes_num"])
        ]
        prev = year_ago.iloc[0] if not year_ago.empty else None
        podpis = f"{last['mes']} {last['god']} против {last['mes']} {last['god'] - 1}"

    st.caption(podpis)
    metrics_row(
        [
            ("Договоры", last["fakt"], _get(prev, "fakt"), 0, ""),
            ("Звонки", last["zvonki"], _get(prev, "zvonki"), 0, ""),
            ("Заявки", last["zayavki"], _get(prev, "zayavki"), 0, ""),
            ("Доля звонков с места ДТП", last["dolya_dtp"], _get(prev, "dolya_dtp"), 1, "%"),
        ]
    )
    if prev is None:
        st.caption("Не с чем сравнивать: за прошлый период данных в таблице нет.")


def _kpi_weekly(weeks: pd.DataFrame | None, internal: bool) -> None:
    """KPI последней заполненной недели против предыдущей."""
    if weeks is None or weeks.empty:
        st.warning("Понедельные данные не загрузились - сравнение по неделям недоступно.")
        return

    filled = weeks[weeks["dogovory"].fillna(0) > 0]
    if len(filled) < 2:
        st.warning("В таблице пока меньше двух заполненных недель.")
        return

    last, prev = filled.iloc[-1], filled.iloc[-2]
    st.caption(f"Неделя «{last['week_label']}» против «{prev['week_label']}»")
    metrics_row(
        [
            ("Договоры", last["dogovory"], prev["dogovory"], 0, ""),
            ("Звонки", last["zvonki"], prev["zvonki"], 0, ""),
            ("Заявки", last["zayavki"], prev["zayavki"], 0, ""),
            ("Доля звонков с места ДТП", last["dolya_dtp"], prev["dolya_dtp"], 1, "%"),
        ]
    )
    if not last["zvonki"] or pd.isna(last["dolya_dtp"]):
        st.caption(
            "Звонки за эту неделю в таблице стоят нулём - строка «ИТОГО» их не суммирует "
            "(дефект таблицы, см. reklama-tablica-oshibki.md)."
            if internal
            else "За эту неделю данные по звонкам ещё не внесены полностью."
        )


def year_over_year(df: pd.DataFrame) -> None:
    """Текущий год против прошлых: один и тот же месяц на одной оси."""
    st.subheader("Год к году")

    label = st.radio("Показатель", list(YOY_METRICS), horizontal=True, key="yoy_metric")
    field, digits = YOY_METRICS[label]

    data = df[df[field].notna() & (df[field] != 0)]
    years = sorted(data["god"].unique())

    fig = go.Figure()
    for year in years:
        part = data[data["god"] == year].sort_values("mes_num")
        fig.add_scatter(
            x=part["mes_num"], y=part[field], name=str(year), mode="lines+markers",
            line=dict(width=3 if year == max(years) else 2,
                      dash="solid" if year == max(years) else "dot"),
        )
    fig.update_layout(
        height=400, hovermode="x unified", margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        xaxis=dict(tickmode="array", tickvals=list(range(1, 13)),
                   ticktext=[m[:3] for m in loader.MONTHS]),
    )
    st.plotly_chart(fig, width="stretch")

    table = data.pivot_table(index="mes_num", columns="god", values=field).round(digits)
    table.index = [loader.MONTHS[i - 1] for i in table.index]
    table.index.name = "Месяц"
    table.columns = [str(c) for c in table.columns]

    current, *rest = sorted(table.columns, reverse=True)
    for other in rest:
        if not table[[current, other]].dropna().empty:
            table[f"{current} к {other}, %"] = (
                (table[current] / table[other] - 1) * 100
            ).round(1)

    st.dataframe(table, width="stretch")
    st.caption(
        "Сравниваются одинаковые месяцы разных лет - бизнес сезонный, месяц к месяцу "
        "внутри года сопоставлять некорректно. Пустые месяцы не показаны."
    )


def weekly(weeks: pd.DataFrame | None, year: int, internal: bool = True) -> None:
    """Динамика по неделям текущего года."""
    st.subheader(f"Недели {year}")

    if weeks is None or weeks.empty:
        st.warning(
            "Понедельные данные не загрузились. На остальные графики это не влияет."
        )
        return

    filled = weeks[weeks["dogovory"].fillna(0) > 0]
    if filled.empty:
        st.warning("За этот год заполненных недель пока нет.")
        return

    label = st.radio(
        "Показатель", list(WEEK_METRICS), horizontal=True, key="week_metric",
    )

    fig = go.Figure()
    fig.add_bar(
        x=filled["week_label"], y=filled[WEEK_METRICS[label]], marker_color=COLOR["fakt"],
    )
    fig.update_layout(
        height=360, margin=dict(t=10, b=10, l=10, r=10), hovermode="x unified",
        xaxis=dict(tickangle=-45),
    )
    st.plotly_chart(fig, width="stretch")

    tail = filled.tail(8)[
        ["week_label", "pokazy", "kliki", "zvonki", "zvonki_dtp", "zayavki", "dogovory"]
    ].copy()
    tail["k_pred"] = (
        (filled["dogovory"] / filled["dogovory"].shift(1) - 1) * 100
    ).tail(8).round(1)
    tail.columns = [
        "Неделя", "Показы", "Клики", "Звонки", "Звонки с ДТП", "Заявки", "Договоры",
        "Договоры к пред. неделе, %",
    ]
    st.dataframe(tail.set_index("Неделя"), width="stretch")

    if internal:
        if not weeks["iz_itogo"].all():
            st.caption(
                "Часть недель посчитана суммированием строк-каналов: в этих месяцах в таблице "
                "нет строки «ИТОГО»."
            )
        st.caption(
            "Недели берутся с листа «Сводная» - там же, где живут дефекты вроде пропущенной "
            "недели 4-10 августа 2025. Сверяй с месячными цифрами."
        )
    else:
        st.caption("Недели считаются по датам из таблицы, последняя неделя месяца - неполная.")


def plan_fakt(closed: pd.DataFrame) -> None:
    st.subheader("План и факт по договорам")

    fig = go.Figure()
    fig.add_bar(
        x=closed["period"], y=closed["plan"], name="План",
        marker_color=COLOR["plan"], opacity=0.55,
    )
    fig.add_bar(x=closed["period"], y=closed["fakt"], name="Факт", marker_color=COLOR["fakt"])
    fig.update_layout(
        barmode="overlay", height=380, hovermode="x unified",
        margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, width="stretch")

    by_year = closed.groupby("god")[["plan", "fakt"]].sum().assign(
        vypolnenie=lambda d: (d["fakt"] / d["plan"] * 100).round(1)
    )
    by_year.columns = ["План", "Факт", "Выполнение, %"]
    by_year.index.name = "Год"
    st.dataframe(by_year, width="stretch")
    st.caption("Текущий год неполный - сравнивать итоги по годам напрямую нельзя.")


def funnel(closed: pd.DataFrame, internal: bool = True) -> None:
    st.subheader("Воронка")

    left, right = st.columns([3, 2])

    with left:
        fig = go.Figure()
        for col, name in [
            ("zvonki", "Звонки"),
            ("zvonki_dtp", "Звонки с места ДТП"),
            ("zayavki", "Заявки"),
            ("fakt", "Договоры"),
        ]:
            fig.add_scatter(x=closed["period"], y=closed[col], name=name, mode="lines+markers")
        fig.update_layout(
            height=380, hovermode="x unified", margin=dict(t=10, b=10, l=10, r=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, width="stretch")

    with right:
        fig = go.Figure()
        fig.add_scatter(
            x=closed["period"], y=closed["dolya_dtp"],
            name="Доля звонков с места ДТП, %", mode="lines+markers",
            line=dict(color=COLOR["alert"], width=3),
        )
        fig.add_scatter(
            x=closed["period"], y=closed["conv_zayavka_dogovor"],
            name="Заявка → договор, %", mode="lines+markers",
            line=dict(color=COLOR["fakt"], width=2, dash="dot"),
        )
        fig.update_layout(
            height=380, hovermode="x unified", margin=dict(t=10, b=10, l=10, r=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            yaxis=dict(ticksuffix="%"),
        )
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "Красная линия - качество трафика, пунктир - работа отдела продаж. "
            "Расходятся: продажи улучшились, трафик испортился."
            if internal
            else "Красная линия - какая доля звонящих обращается прямо с места ДТП. "
            "Пунктир - какая доля заявок доходит до договора."
        )


def channels(closed: pd.DataFrame, internal: bool = True) -> None:
    st.subheader("Каналы")

    note = (
        f"С {METHOD_CHANGE} в таблице сменилась методика учёта договоров по каналам. "
        "Сравнивать каналы 2026 против 2025 после февраля нельзя - сначала надо починить учёт."
        if internal
        else f"С {METHOD_CHANGE} изменился способ учёта договоров по каналам, поэтому "
        "сравнивать каналы с прошлым годом после февраля некорректно. "
        "Показы, клики и CTR сопоставимы за весь период."
    )
    st.info(note, icon="ℹ️")

    metric = st.radio(
        "Показатель", ["Показы", "Клики", "CTR, %", "Договоры"],
        horizontal=True, label_visibility="collapsed",
    )
    index = {"Показы": 0, "Клики": 1, "CTR, %": 2, "Договоры": 3}[metric]

    fig = go.Figure()
    for channel, cols in loader.CHANNELS.items():
        fig.add_scatter(
            x=closed["period"], y=closed[cols[index]], name=channel,
            mode="lines+markers", line=dict(color=COLOR[channel]),
        )
    if metric == "Договоры":
        fig.add_scatter(
            x=closed["period"], y=closed["google_dogovory"], name="Google",
            mode="lines+markers", line=dict(color=COLOR["Google"], dash="dash"),
        )

    # На категориальной оси Plotly ждёт номер категории, а не её название.
    periods = closed["period"].tolist()
    if METHOD_CHANGE in periods:
        fig.add_vline(
            x=periods.index(METHOD_CHANGE), line_dash="dot", line_color=COLOR["alert"],
        )
    fig.update_layout(
        height=400, hovermode="x unified", margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        # Ось строго категориальная: иначе Plotly принимает номер категории из add_vline
        # за число, переводит ось в числовую и рисует шкалу «1970-2020».
        xaxis=dict(type="category"),
    )
    st.plotly_chart(fig, width="stretch")
    st.caption("Пунктирная вертикаль - момент изменения учёта.")


CHANNEL_METRICS = {
    "Показы": ("pokazy", 0, ""),
    "Клики": ("kliki", 0, ""),
    "CTR, %": ("ctr", 2, "%"),
    "Звонки": ("zvonki", 0, ""),
    "Заявки": ("zayavki", 0, ""),
    "Договоры": ("dogovory", 0, ""),
}

# Цвета закреплены за каналами, чтобы они не прыгали при смене набора.
CHANNEL_COLORS = {
    "Яндекс.Директ (поиск)": "#dc2626",
    "Яндекс.РСЯ": "#f97316",
    "Яндекс.Карты": "#f59e0b",
    "2ГИС": "#0f766e",
    "Google": "#6366f1",
    "Прямые заходы": "#0ea5e9",
    "Медийная реклама": "#a855f7",
    "Юристы": "#64748b",
    "Неопределённые": "#94a3b8",
    "Входящий звонок": "#78716c",
    "Тестовый нейро": "#10b981",
    "MAX": "#ec4899",
}

# По умолчанию показываем рекламные каналы: остальные - это не реклама, а поток обращений.
DEFAULT_CHANNELS = [
    "Яндекс.Директ (поиск)", "Яндекс.РСЯ", "Яндекс.Карты", "2ГИС", "Google",
]


@st.cache_data(ttl=CACHE_TTL)
def data_loaded_at() -> datetime:
    """Момент загрузки данных.

    Живёт в том же кэше с тем же сроком, что и сами данные: истекает вместе с ними
    и сбрасывается той же кнопкой. Поэтому показывает именно время последнего чтения
    таблицы, а не время открытия страницы.
    """
    return datetime.now()


def refresh_button() -> None:
    """Кнопка «Обновить данные»: сбросить кэш и перечитать таблицу прямо сейчас."""
    left, right = st.columns([5, 1])
    with left:
        st.caption(
            f"Данные прочитаны из таблицы в {data_loaded_at():%H:%M}. "
            "Обновляются автоматически раз в полчаса - или сразу по кнопке."
        )
    with right:
        if st.button("Обновить данные", width="stretch"):
            st.cache_data.clear()
            # Список листов живёт отдельно от кэша данных - его тоже сбрасываем,
            # иначе только что созданный лист «Сводная_2027» не найдётся.
            loader.reset_sheets_cache()
            st.rerun()


def running_month_note(row: pd.Series | None) -> None:
    """Отдельная строка про идущий месяц - он не участвует в сравнениях."""
    if row is None:
        return
    st.caption(
        f"Идёт {row['mes']} {int(row['god'])}: уже {ru(row['fakt'])} договоров, "
        f"{ru(row['zvonki'])} звонков. Месяц не закончен, поэтому в сравнениях "
        "и на графиках выше он не участвует."
    )


def _ctr(frame: pd.DataFrame) -> pd.Series:
    """Клики / показы в процентах. Ноль показов -> пусто, а не деление на ноль.

    to_numeric обязателен: если показов нет ни у одного канала, колонка получается
    целиком из pd.NA с типом object, и .round() на ней падает.

    CTR больше 100% скрываем: это не показатель, а дефект данных. У Google в «Сводной»
    клики есть, а показов почти нет - иначе получалось бы «CTR 832%».
    """
    value = pd.to_numeric(
        frame["kliki"] / frame["pokazy"].replace(0, pd.NA) * 100, errors="coerce"
    )
    return value.where(value <= 100)


def channels_detail(data: pd.DataFrame | None, year: int, internal: bool = True) -> None:
    """Показы, клики, CTR и результат в разрезе всех каналов - с листа «Сводная»."""
    st.subheader(f"Каналы подробно, {year}")

    if data is None or data.empty:
        st.warning(
            "Данные по каналам не загрузились. На остальные графики это не влияет."
        )
        return

    left, right = st.columns([2, 3])
    with left:
        label = st.selectbox("Показатель", list(CHANNEL_METRICS), key="chan_metric")
    field, digits, suffix = CHANNEL_METRICS[label]

    available = [c for c in CHANNEL_COLORS if c in set(data["kanal"])]
    available += [c for c in sorted(set(data["kanal"])) if c not in CHANNEL_COLORS]

    with right:
        chosen = st.multiselect(
            "Каналы",
            available,
            default=[c for c in DEFAULT_CHANNELS if c in available] or available[:5],
            key="chan_list",
        )

    if not chosen:
        st.info("Выберите хотя бы один канал.")
        return

    period = st.radio(
        "Разрез", ["По месяцам", "По неделям"], horizontal=True, key="chan_period",
    )

    part = data[data["kanal"].isin(chosen)]
    if period == "По месяцам":
        grouped = part.groupby(["mes_num", "mes", "kanal"], as_index=False).sum(numeric_only=True)
        grouped = grouped.sort_values("mes_num")
        axis, ticks = "mes", None
    else:
        grouped = part.sort_values("order")
        axis, ticks = "week_label", -45

    # CTR - это отношение, суммировать его нельзя: пересчитываем после группировки.
    grouped["ctr"] = _ctr(grouped)

    shown = grouped[grouped[field].notna()]
    if shown.empty or (shown[field] == 0).all():
        st.info(f"У выбранных каналов нет данных по показателю «{label}».")
        return

    fig = go.Figure()
    for channel in chosen:
        line = shown[shown["kanal"] == channel]
        if line.empty:
            continue
        fig.add_scatter(
            x=line[axis], y=line[field], name=channel, mode="lines+markers",
            line=dict(color=CHANNEL_COLORS.get(channel)),
        )
    fig.update_layout(
        height=420, hovermode="x unified", margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        xaxis=dict(tickangle=ticks) if ticks else {},
        yaxis=dict(ticksuffix=suffix),
    )
    st.plotly_chart(fig, width="stretch")

    table = (
        part.groupby("kanal", as_index=False)
        .sum(numeric_only=True)[["kanal", "pokazy", "kliki", "zvonki", "zayavki", "dogovory"]]
    )
    table["ctr"] = _ctr(table).round(2)
    table = table[["kanal", "pokazy", "kliki", "ctr", "zvonki", "zayavki", "dogovory"]]
    table.columns = ["Канал", "Показы", "Клики", "CTR, %", "Звонки", "Заявки", "Договоры"]
    st.dataframe(
        table.sort_values("Договоры", ascending=False).set_index("Канал"), width="stretch",
    )
    st.caption(
        f"Итог за {year} год по выбранным каналам. Пустой CTR - у канала нет показов "
        "(прямые заходы, звонки, юристы): это не реклама, а поток обращений. "
        "У Google в этом листе есть клики, но нет показов, поэтому CTR по нему не считается."
        + (
            " Данные с листа «Сводная», названия каналов сведены к общим: в таблице один "
            "и тот же канал записан по-разному в разные месяцы."
            if internal
            else ""
        )
    )
    if internal:
        st.warning(
            "Клики по 2ГИС на этом листе и на листе «Данные» расходятся в 3-4,5 раза "
            "(показы при этом совпадают точно). Похоже, под словом «клики» на двух листах "
            "имеются в виду разные события. Цифры «Сводной» сходятся с медиапланом "
            "(открытие карточки ~10%), цифры «Данных» - нет. Подробности - "
            "reklama-tablica-oshibki.md, пункт 10.",
            icon="⚠️",
        )


def prices(data: pd.DataFrame, internal: bool = True) -> None:
    st.subheader("Стоимость договора по каналам, ₽")

    if data.empty:
        st.warning("Данные о стоимости договора не загрузились.")
        return

    fig = go.Figure()
    for channel in data["kanal"].unique():
        part = data[data["kanal"] == channel]
        fig.add_scatter(x=part["period"], y=part["stoimost"], name=channel, mode="lines+markers")
    fig.update_layout(
        height=360, hovermode="x unified", margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis=dict(ticksuffix=" ₽"),
    )
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Директ дороже 2ГИС примерно в 8-10 раз. За 2026 год лист заполнен частично: "
        "по Директу и Картам - только январь и февраль."
        if internal
        else "За текущий год данные заполнены частично."
    )
