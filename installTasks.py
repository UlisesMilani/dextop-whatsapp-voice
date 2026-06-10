# -*- coding: utf-8 -*-
import logging
import os
import winreg

log = logging.getLogger("nvda.dextop_whatsapp_voice.installTasks")
DEBUG_PORT = 59222
DEBUG_ARG = "--remote-debugging-port=%d --remote-allow-origins=http://127.0.0.1" % DEBUG_PORT
ENV_NAME = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"

NAMES = [
    "*",
    "WhatsApp.Root.exe",
    "WhatsApp.exe",
    "WhatsAppDesktop.exe",
    "5319275A.WhatsAppDesktop",
    "5319275A.WhatsAppDesktop_cv1g1gvanyjgm",
    "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
    "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!WhatsApp",
    "Chrome._crx_hnpfjngllnfapefoaidbinmjnm",
]
PATHS = [
    r"Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments",
    r"Software\Microsoft\Edge\WebView2\AdditionalBrowserArguments",
]


def _delete_if_ours(key, name):
    try:
        current, _ = winreg.QueryValueEx(key, name)
        if current == DEBUG_ARG or "remote-debugging-port=%d" % DEBUG_PORT in str(current):
            winreg.DeleteValue(key, name)
            log.info("Dextop WhatsApp Voice: se eliminó %s", name)
    except FileNotFoundError:
        pass


def onUninstall():
    """Limpieza automática al desinstalar el complemento."""
    log.info("Dextop WhatsApp Voice: Ejecutando tareas de desinstalación...")
    for key_path in PATHS:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
            for name in NAMES:
                _delete_if_ours(key, name)
            winreg.CloseKey(key)
        except FileNotFoundError:
            pass
        except Exception as e:
            log.error("Dextop WhatsApp Voice: Error al limpiar %s: %s", key_path, e)

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
        _delete_if_ours(key, ENV_NAME)
        winreg.CloseKey(key)
        os.environ.pop(ENV_NAME, None)
    except FileNotFoundError:
        pass
    except Exception as e:
        log.error("Dextop WhatsApp Voice: Error al limpiar variable de entorno: %s", e)
