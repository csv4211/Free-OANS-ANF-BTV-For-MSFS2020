"""UI strings: English default, Russian optional. Session-only (not persisted)."""

from __future__ import annotations

LANGS = ("en", "ru")
DEFAULT_LANG = "en"

_current = DEFAULT_LANG

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app_title": "AMDB OANS",
        "checking_server": "Checking server…",
        "checking_update": "Checking for updates…",
        "updating": "Updating…",
        "update_restart": "Update installed. Restarting…",
        "update_failed": "Update failed",
        "update_missing": "Update not published on server (no EXE in updates/)",
        "update_required_title": "Update required",
        "update_required_body": (
            "This app version is outdated and cannot be used.\n\n"
            "Update to {version} now?"
        ),
        "update_declined": "Update declined — app cannot be used until updated",
        "update_launching": "Starting updater…",
        "activating": "Activating…",
        "ready": "Ready",
        "ready_relaunch": "Ready. Close the app and open it again.",
        "server_ok": "Server online",
        "server_down": "No connection to server",
        "server_temp": "Server temporarily unavailable",
        "server_refuse": "Server unavailable or refused",
        "banned": "Access denied (banned)",
        "need_update": "A newer app version is required",
        "device_mismatch": "Device does not match registration",
        "not_registered": "Device is not registered",
        "deny_all": "Server is closed for everyone",
        "auth_error": "Device verification failed",
        "need_activation": "Activation required",
        "wait_activation": "Please wait — device setup in progress.",
        "enabled": "Enabled: {parts}",
        "part_web": "web",
        "part_oans": "OANS",
        "oans_title": "OANS in the aircraft",
        "oans_hint": "MITM for FlyByWire · administrator rights required",
        "web_title": "Web map",
        "web_hint": "Airport map in the browser",
        "open_web": "Open web map",
        "quit": "Exit",
        "admin_needed_title": "Administrator rights required",
        "admin_needed_body": (
            "OANS in the aircraft needs administrator rights "
            "(hosts file and port 443).\n\nRestart the app as administrator?"
        ),
        "admin_fail": (
            "Could not elevate privileges. Right-click the EXE → "
            "Run as administrator."
        ),
        "web_server_warn": "Web map started, but the server is unavailable.",
        "server": "Server",
        "err_need_new_version": "a newer app version is required",
        "err_build_rejected": "this client build was rejected by the server",
        "err_device_check": "device verification failed",
        "err_session_expired": "verification session expired, try again",
        "err_access_denied": "access denied",
        "err_need_stock": "a stock client build is required",
        "err_bind_failed": "could not bind the device",
        "err_enroll_failed": "registration failed",
        "err_no_server": "no connection to server",
        "err_prepare_failed": "could not prepare the device",
        "err_write_activation": "could not save activation — close the app and open it again",
        "err_banned": "access denied (banned)",
        "err_forbidden": "access denied",
        "err_unauthorized": "unauthorized",
        "err_not_found": "not found",
        "unregister": "Unregister this PC",
        "unreg_title": "Unregister this PC",
        "unreg_confirm_title": "Unregister this PC?",
        "unreg_confirm_body": (
            "This removes the device secret from this computer only.\n"
            "The device stays registered on the server.\n\n"
            "The app will close and open the unregister tool."
        ),
        "unreg_confirm_hint": (
            "Remove the device secret from this PC?\n"
            "The server registration is not deleted."
        ),
        "unreg_working": "Removing local registration…",
        "unreg_done": "Local registration removed. You can close this window.",
        "unreg_failed": "Could not clear local registration.",
        "unreg_yes": "Unregister",
        "unreg_no": "Cancel",
        "unreg_tool_missing": "Unregister tool not found (AmdbOansUnregister.exe).",
        "unreg_launching": "Starting unregister…",
    },
    "ru": {
        "app_title": "AMDB OANS",
        "checking_server": "Проверка сервера…",
        "checking_update": "Проверка обновлений…",
        "updating": "Обновление…",
        "update_restart": "Обновление установлено. Перезапуск…",
        "update_failed": "Не удалось обновить",
        "update_missing": "Обновление не выложено на сервер (нет EXE в updates/)",
        "update_required_title": "Нужно обновление",
        "update_required_body": (
            "Эта версия устарела и ей нельзя пользоваться.\n\n"
            "Обновить до {version} сейчас?"
        ),
        "update_declined": "Обновление отклонено — без новой версии работать нельзя",
        "update_launching": "Запуск обновлятора…",
        "activating": "Активация…",
        "ready": "Готово",
        "ready_relaunch": "Готово. Закройте программу и откройте снова.",
        "server_ok": "Сервер на связи",
        "server_down": "Нет связи с сервером",
        "server_temp": "Сервер временно недоступен",
        "server_refuse": "Сервер недоступен или отказ",
        "banned": "Доступ запрещён (бан)",
        "need_update": "Нужна новая версия программы",
        "device_mismatch": "Устройство не совпадает с регистрацией",
        "not_registered": "Устройство не зарегистрировано",
        "deny_all": "Сервер закрыт для всех",
        "auth_error": "Ошибка проверки устройства",
        "need_activation": "Нужна активация",
        "wait_activation": "Подождите, идёт подготовка устройства.",
        "enabled": "Включено: {parts}",
        "part_web": "веб",
        "part_oans": "OANS",
        "oans_title": "OANS в самолёте",
        "oans_hint": "MITM для FlyByWire · нужны права администратора",
        "web_title": "Веб-карта",
        "web_hint": "Карта аэродрома в браузере",
        "open_web": "Открыть веб-карту",
        "quit": "Выход",
        "admin_needed_title": "Нужны права администратора",
        "admin_needed_body": (
            "Для OANS в самолёте нужны права администратора "
            "(правка hosts и порт 443).\n\nПерезапустить программу от имени администратора?"
        ),
        "admin_fail": (
            "Не удалось запросить права. Запустите EXE правым кликом → "
            "«Запуск от имени администратора»."
        ),
        "web_server_warn": "Веб-карта запущена, но сервер недоступен.",
        "server": "Сервер",
        "err_need_new_version": "нужна новая версия программы",
        "err_build_rejected": "сборка клиента не принята сервером",
        "err_device_check": "проверка устройства не прошла",
        "err_session_expired": "сессия проверки устарела, попробуйте снова",
        "err_access_denied": "доступ запрещён",
        "err_need_stock": "нужна стоковая сборка клиента",
        "err_bind_failed": "не удалось закрепить устройство",
        "err_enroll_failed": "регистрация не удалась",
        "err_no_server": "нет связи с сервером",
        "err_prepare_failed": "не удалось подготовить устройство",
        "err_write_activation": "не удалось записать активацию — закройте программу и запустите снова",
        "err_banned": "доступ запрещён (бан)",
        "err_forbidden": "доступ запрещён",
        "err_unauthorized": "нет доступа",
        "err_not_found": "не найдено",
        "unregister": "Снять регистрацию с ПК",
        "unreg_title": "Снятие регистрации",
        "unreg_confirm_title": "Снять регистрацию с этого ПК?",
        "unreg_confirm_body": (
            "Секрет устройства будет удалён только с этого компьютера.\n"
            "Запись на сервере останется.\n\n"
            "Программа закроется и откроет инструмент снятия регистрации."
        ),
        "unreg_confirm_hint": (
            "Удалить секрет устройства с этого ПК?\n"
            "Регистрация на сервере не удаляется."
        ),
        "unreg_working": "Удаление локальной регистрации…",
        "unreg_done": "Локальная регистрация снята. Можно закрыть окно.",
        "unreg_failed": "Не удалось очистить локальную регистрацию.",
        "unreg_yes": "Снять",
        "unreg_no": "Отмена",
        "unreg_tool_missing": "Не найден инструмент снятия (AmdbOansUnregister.exe).",
        "unreg_launching": "Запуск снятия регистрации…",
    },
}


def detect_lang() -> str:
    try:
        import embedded

        raw = str(getattr(embedded, "UI_LANG", "") or "").strip().lower()
        if raw in LANGS:
            return raw
    except Exception:
        pass
    return DEFAULT_LANG


def get_lang() -> str:
    return _current


def set_lang(code: str) -> str:
    global _current
    code = (code or DEFAULT_LANG).strip().lower()
    if code not in LANGS:
        code = DEFAULT_LANG
    _current = code
    return _current


def t(key: str, **kwargs) -> str:
    table = _STRINGS.get(_current) or _STRINGS[DEFAULT_LANG]
    text = table.get(key) or _STRINGS[DEFAULT_LANG].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


set_lang(detect_lang())
