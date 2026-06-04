import winreg
import logging

log = logging.getLogger("nvda.dextop_whatsapp_voice.installTasks")

def onUninstall():
    """Se ejecuta automáticamente cuando el usuario desinstala el complemento de NVDA."""
    log.info("Dextop WhatsApp Voice: Ejecutando tareas de desinstalación...")
    paths_to_clean = [
        (winreg.HKEY_CURRENT_USER, r"Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Edge\WebView2\AdditionalBrowserArguments")
    ]
    for hkey, key_path in paths_to_clean:
        try:
            key = winreg.OpenKey(hkey, key_path, 0, winreg.KEY_SET_VALUE)
            for name in ["WhatsApp.Root.exe", "WhatsApp.exe"]:
                try:
                    winreg.DeleteValue(key, name)
                    log.info(f"Dextop WhatsApp Voice: Se eliminó {name} de {key_path}")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except FileNotFoundError:
            pass
        except Exception as e:
            log.error(f"Dextop WhatsApp Voice: Error al limpiar {key_path}: {e}")

