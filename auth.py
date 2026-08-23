"""Простая защита паролем для клиентской версии дашборда.

Пароль хранится в `st.secrets` (файл `.streamlit/secrets.toml` локально, раздел Secrets
в настройках Streamlit Cloud при деплое). В репозиторий пароль не коммитится.

Это защита «от посторонних глаз», а не полноценная авторизация: один общий пароль,
без учётных записей и журнала входов. Для показа рекламной статистики клиенту этого
достаточно, для персональных данных - нет.
"""

from __future__ import annotations

import hmac

import streamlit as st

SECRET_KEY = "app_password"


def check_password() -> bool:
    """Показать форму входа и вернуть True, только если пароль верный.

    Если пароль в secrets не задан - пускаем без него и предупреждаем. Иначе при забытой
    настройке дашборд молча оказался бы открыт всему интернету, а так это сразу видно.
    """
    expected = _configured_password()
    if expected is None:
        st.warning(
            "Пароль не настроен: дашборд открыт всем, у кого есть ссылка. "
            f"Задайте `{SECRET_KEY}` в секретах приложения.",
            icon="⚠️",
        )
        return True

    if st.session_state.get("auth_ok"):
        return True

    st.markdown("### Дашборд рекламы Форсайт")
    st.caption("Введите пароль для доступа.")

    with st.form("auth"):
        entered = st.text_input("Пароль", type="password")
        submitted = st.form_submit_button("Войти")

    if submitted:
        # compare_digest вместо == : сравнение за постоянное время.
        # Сравниваем байты, а не строки: со строками он не работает, если пароль
        # содержит кириллицу.
        if hmac.compare_digest(entered.encode("utf-8"), expected.encode("utf-8")):
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Неверный пароль.")

    return False


def _configured_password() -> str | None:
    """Пароль из secrets или None, если он не задан.

    Обращение к st.secrets бросает исключение, когда файла секретов нет вообще -
    для нас это просто «пароль не настроен», а не аварийная ситуация.
    """
    try:
        if SECRET_KEY in st.secrets:
            return str(st.secrets[SECRET_KEY])
    except Exception:
        return None
    return None
