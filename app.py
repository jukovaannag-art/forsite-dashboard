"""Клиентская версия дашборда рекламы Форсайт.

Отличия от внутренней (`app.py`):
- вход по паролю;
- нейтральные формулировки: без указаний на дефекты таблицы и ссылок на файлы репозитория;
- в начале - краткая сводка «что происходит» человеческим языком;
- пояснения «что означает показатель» рядом с блоками.

Запуск: streamlit run dashboard/app_client.py
"""

from __future__ import annotations

import streamlit as st

import auth
import charts
import loader

st.set_page_config(page_title="Реклама Форсайт", page_icon="📊", layout="wide")


def main() -> None:
    if not auth.check_password():
        return

    st.title("Реклама Форсайт")

    try:
        df = charts.get_dannye()
        prices = charts.get_stoimost()
    except loader.SheetUnavailable:
        st.error(
            "Не получилось загрузить данные. Проверьте, что таблица доступна по ссылке, "
            "и обновите страницу."
        )
        st.stop()
        return

    closed = charts.closed_months(df)
    if closed.empty:
        st.warning("В таблице пока нет ни одного закрытого месяца с данными.")
        st.stop()
        return

    last = closed.iloc[-1]
    weeks = charts.weeks_or_none(int(last["god"]))

    st.caption(f"Данные за последний закрытый месяц: **{last['mes']} {last['god']}**.")
    charts.running_month_note(charts.current_month(df))
    charts.refresh_button()

    _summary(closed)
    st.divider()

    charts.kpi_block(closed, weeks, internal=False)
    st.divider()
    charts.year_over_year(closed)
    st.divider()
    charts.weekly(weeks, int(last["god"]), internal=False)
    st.divider()
    charts.plan_fakt(closed)
    st.divider()
    charts.funnel(closed, internal=False)
    st.divider()
    charts.channels(closed, internal=False)
    st.divider()
    charts.channels_detail(
        charts.channels_or_none(int(last["god"])), int(last["god"]), internal=False,
    )
    st.divider()
    charts.prices(prices, internal=False)

    with st.expander("Как читать этот дашборд"):
        st.markdown(
            """
**Откуда цифры.** Дашборд читает вашу рабочую Google-таблицу напрямую: месячные показатели -
с листа «Данные», понедельные - с листов «Сводная», стоимость договора - с соответствующего
листа. Ничего не пересчитывается и не досчитывается: что внесено в таблицу, то и показано.

**Что означают показатели.**

- **Звонки** - уникальные обращения за период.
- **Звонки с места ДТП** - те, кто звонит непосредственно из ситуации ДТП. Их доля показывает,
  насколько точно реклама попадает в нужный момент: чем выше доля, тем целевее трафик.
- **Заявки** - обращения, дошедшие до оформления сделки.
- **Договоры** - успешные сделки за вычетом километражей.

**С чем сравнивать.** По умолчанию показатель сравнивается с тем же месяцем прошлого года:
бизнес сезонный, и сравнение с предыдущим месяцем вводит в заблуждение. Переключатель
«Сравнивать с» позволяет посмотреть также к предыдущему месяцу и к предыдущей неделе.

**Что учесть.** Данные в таблице отражают все обращения компании, а не только рекламные,
и поклиентной привязки к источнику нет - поэтому окупаемость каждого канала по этим цифрам
рассчитать нельзя, они показывают динамику и соотношения. Незаполненные будущие месяцы
из графиков исключены.
            """
        )


def _summary(closed) -> None:
    """Короткая сводка в начале: что происходит, человеческим языком."""
    last = closed.iloc[-1]
    year_ago = closed[
        (closed["god"] == last["god"] - 1) & (closed["mes_num"] == last["mes_num"])
    ]

    lines = [
        f"**{last['mes'].capitalize()} {last['god']}:** "
        f"{charts.ru(last['fakt'])} {_plural(last['fakt'], 'договор', 'договора', 'договоров')} "
        f"при плане {charts.ru(last['plan'])} ({charts.ru(last['proc_plana'], 1)}% плана)."
    ]

    if not year_ago.empty:
        prev = year_ago.iloc[0]
        diff_dog = last["fakt"] - prev["fakt"]
        diff_zvon = last["zvonki"] - prev["zvonki"]
        lines.append(
            f"К тому же месяцу {last['god'] - 1} года: договоров "
            f"{'больше' if diff_dog >= 0 else 'меньше'} на {charts.ru(abs(diff_dog))}, "
            f"звонков {'больше' if diff_zvon >= 0 else 'меньше'} "
            f"на {charts.ru(abs(diff_zvon))}."
        )
        if prev["dolya_dtp"] and last["dolya_dtp"]:
            lines.append(
                f"Доля звонков с места ДТП: {charts.ru(last['dolya_dtp'], 1)}% против "
                f"{charts.ru(prev['dolya_dtp'], 1)}% год назад - это показатель того, "
                "насколько точно реклама попадает в нужную аудиторию."
            )

    st.info("\n\n".join(lines), icon="📌")


def _plural(count: float, one: str, few: str, many: str) -> str:
    """1 договор, 2 договора, 5 договоров."""
    number = abs(int(count))
    if number % 100 in range(11, 15):
        return many
    last_digit = number % 10
    if last_digit == 1:
        return one
    if last_digit in (2, 3, 4):
        return few
    return many


if __name__ == "__main__":
    main()
