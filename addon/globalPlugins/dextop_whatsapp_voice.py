# -*- coding: utf-8 -*-
"""Dextop WhatsApp Voice - NVDA global plugin.

Mejora la grabación de audios de WhatsApp Desktop moderno basado en WebView2.
La versión 1.0 (estable) agrega compatibilidad con Chromium/WebView2 recientes mediante
--remote-allow-origins=http://127.0.0.1, herramientas de diagnóstico y comprobación de actualización.
"""

import base64
import ctypes
import globalPluginHandler
import globalVars
import json
import logging
import os
import random
import socket
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import winreg

import addonHandler
import wx

try:
    import ui
except Exception:
    ui = None
try:
    import gui
except Exception:
    gui = None
try:
    from scriptHandler import script
except Exception:
    script = None

addonHandler.initTranslation()

log = logging.getLogger("nvda.dextop_whatsapp_voice")

DEBUG_PORT = 59222
DEBUG_ARG = "--remote-debugging-port=%d --remote-allow-origins=http://127.0.0.1" % DEBUG_PORT
ENV_NAME = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
REG_PATHS = [
    r"Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments",
    r"Software\Microsoft\Edge\WebView2\AdditionalBrowserArguments",
]
ENV_REG_PATH = r"Environment"

# Nombres conocidos para WhatsApp Desktop moderno y variantes usadas por Microsoft Store / WebView2.
BASE_APP_KEYS = [
    "WhatsApp.Root.exe",
    "WhatsApp.exe",
    "WhatsAppDesktop.exe",
    "5319275A.WhatsAppDesktop",
    "5319275A.WhatsAppDesktop_cv1g1gvanyjgm",
    "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
    "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!WhatsApp",
    # Variante cuando WhatsApp se instaló como app/progresiva desde Chrome.
    "Chrome._crx_hnpfjngllnfapefoaidbinmjnm",
]

# Desactivado por seguridad para cumplir las políticas de la tienda de NVDA
# (evita abrir puertos de depuración en otras aplicaciones WebView2)
USE_WILDCARD_AND_USER_ENVIRONMENT = False


class MinWSClient:
    """Cliente WebSocket mínimo para comunicarse con Chrome DevTools Protocol."""

    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.sock = None

    def connect(self):
        parsed = urllib.parse.urlparse(self.ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or DEBUG_PORT
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(4.0)
        self.sock.connect((host, port))

        sec_key = base64.b64encode(bytes(random.randint(0, 255) for _ in range(16))).decode("utf-8")
        handshake = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: http://127.0.0.1\r\n\r\n"
        ) % (path, host, port, sec_key)
        self.sock.sendall(handshake.encode("utf-8"))

        # Recibir respuesta del handshake
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(1024)
            if not chunk:
                break
            response += chunk
            if len(response) > 8192:
                raise Exception("Handshake de WebSocket demasiado largo")
        if b" 101 " not in response:
            raise Exception("Fallo en el handshake de WebSocket: " + response[:300].decode("utf-8", "ignore"))

    def send_text(self, text):
        data = text.encode("utf-8")
        length = len(data)
        frame = bytearray([0x81])
        if length < 126:
            frame.append(0x80 | length)
        elif length <= 0xFFFF:
            frame.append(0x80 | 126)
            frame.extend(struct.pack("!H", length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack("!Q", length))
        mask = [random.randint(0, 255) for _ in range(4)]
        frame.extend(mask)
        frame.extend(bytearray(b ^ mask[i % 4] for i, b in enumerate(data)))
        self.sock.sendall(frame)

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


def discover_whatsapp_app_ids():
    """Intenta descubrir AppUserModelIDs de WhatsApp publicados en el menú inicio."""
    ids = []
    try:
        cmd = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            "Get-StartApps | Where-Object { $_.Name -match 'WhatsApp' } | Select-Object -ExpandProperty AppID"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=6, creationflags=0x08000000)
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if line and "whatsapp" in line.lower():
                ids.append(line)
    except Exception as e:
        log.debug("Dextop WhatsApp Voice: No se pudo descubrir AppID por PowerShell: %s", e)
    return ids


def registry_value_names():
    names = list(dict.fromkeys(BASE_APP_KEYS + discover_whatsapp_app_ids()))
    if USE_WILDCARD_AND_USER_ENVIRONMENT:
        names.append("*")
    return names


def _broadcast_environment_change():
    """Notifica a Explorer que cambió el entorno de usuario."""
    try:
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            3000,
            None,
        )
    except Exception as e:
        log.debug("Dextop WhatsApp Voice: No se pudo enviar WM_SETTINGCHANGE: %s", e)


def write_user_environment_argument():
    if not USE_WILDCARD_AND_USER_ENVIRONMENT:
        return
    try:
        os.environ[ENV_NAME] = DEBUG_ARG
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, ENV_REG_PATH)
        winreg.SetValueEx(key, ENV_NAME, 0, winreg.REG_SZ, DEBUG_ARG)
        winreg.CloseKey(key)
        _broadcast_environment_change()
        log.info("Dextop WhatsApp Voice: Variable de entorno de usuario configurada.")
    except Exception as e:
        log.error("Dextop WhatsApp Voice: No se pudo configurar variable de entorno: %s", e)


def remove_user_environment_argument():
    try:
        os.environ.pop(ENV_NAME, None)
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, ENV_REG_PATH, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
        try:
            current, _ = winreg.QueryValueEx(key, ENV_NAME)
            if current == DEBUG_ARG or "remote-debugging-port=%d" % DEBUG_PORT in str(current):
                winreg.DeleteValue(key, ENV_NAME)
                log.info("Dextop WhatsApp Voice: Variable de entorno de usuario eliminada.")
        except FileNotFoundError:
            pass
        winreg.CloseKey(key)
        _broadcast_environment_change()
    except FileNotFoundError:
        pass
    except Exception as e:
        log.error("Dextop WhatsApp Voice: Error eliminando variable de entorno: %s", e)


def write_registry_policy():
    names = registry_value_names()
    for key_path in REG_PATHS:
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
            for name in names:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, DEBUG_ARG)
            winreg.CloseKey(key)
            log.info("Dextop WhatsApp Voice: Registro configurado en %s para: %s", key_path, ", ".join(names))
        except Exception as e:
            log.error("Dextop WhatsApp Voice: No se pudo escribir %s: %s", key_path, e)
    write_user_environment_argument()


def cleanup_registry_policy():
    names = list(dict.fromkeys(BASE_APP_KEYS + discover_whatsapp_app_ids() + ["*"]))
    for key_path in REG_PATHS:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
            for name in names:
                try:
                    current, _ = winreg.QueryValueEx(key, name)
                    if current == DEBUG_ARG or "remote-debugging-port=%d" % DEBUG_PORT in str(current):
                        winreg.DeleteValue(key, name)
                        log.info("Dextop WhatsApp Voice: Registro limpiado en %s para %s", key_path, name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except FileNotFoundError:
            pass
        except Exception as e:
            log.error("Dextop WhatsApp Voice: Error limpiando registro: %s", e)
    remove_user_environment_argument()


def is_debug_port_open():
    try:
        with socket.create_connection(("127.0.0.1", DEBUG_PORT), timeout=1.0):
            return True
    except Exception:
        return False

def parse_version(v_str):
    """Parsea cadenas de versión como 1.0-dev1 en una tupla comparable (([1, 0], 1))."""
    try:
        parts = v_str.split("-")
        version_part = parts[0]
        dev_num = 0
        if len(parts) > 1:
            dev_str = parts[1]
            digits = "".join([c for c in dev_str if c.isdigit()])
            if digits:
                dev_num = int(digits)
        version_nums = [int(x) for x in version_part.split(".")]
        return version_nums, dev_num
    except Exception:
        return [0], 0


def is_new_version(remote_v_str, local_v_str):
    """Compara cadenas de versión soportando sufijos del canal de desarrollo (ej. 1.0-dev2 > 1.0-dev1)."""
    r_nums, r_dev = parse_version(remote_v_str)
    l_nums, l_dev = parse_version(local_v_str)

    max_len = max(len(r_nums), len(l_nums))
    r_nums += [0] * (max_len - len(r_nums))
    l_nums += [0] * (max_len - len(l_nums))

    if r_nums > l_nums:
        return True
    elif r_nums == l_nums:
        return r_dev > l_dev
    return False


def notify_message(msg):
    """Habla un mensaje y lo muestra en braille a través del módulo ui de NVDA."""
    try:
        import ui
        import wx
        wx.CallAfter(lambda: ui.message(msg))
    except Exception:
        pass


class UpdateDownloaderThread(threading.Thread):
    """Descarga el paquete .nvda-addon en segundo plano y lo ejecuta para su instalación."""

    def __init__(self, download_url):
        super().__init__()
        self.daemon = True
        self.download_url = download_url

    def run(self):
        notify_message(_("Downloading update..."))
        try:
            req = urllib.request.Request(self.download_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30.0) as response:
                import tempfile
                temp_dir = tempfile.gettempdir()
                temp_path = os.path.join(temp_dir, "dextop_whatsapp_voice_update.nvda-addon")

                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

                with open(temp_path, "wb") as f:
                    while True:
                        chunk = response.read(1024 * 16)
                        if not chunk:
                            break
                        f.write(chunk)

                notify_message(_("Download complete. Starting installation..."))
                os.startfile(temp_path)
        except Exception as e:
            log.error(f"Dextop WhatsApp Voice: Direct download failed: {e}", exc_info=True)
            notify_message(_("Automatic download failed. Opening download page in browser..."))
            try:
                os.startfile("https://github.com/UlisesMilani/dextop-whatsapp-voice/releases/latest")
            except Exception:
                pass


class UpdateCheckerThread(threading.Thread):
    """Comprueba de forma asíncrona actualizaciones en GitHub según el canal actual de la versión."""

    def __init__(self, current_version):
        super().__init__()
        self.daemon = True
        self.current_version = str(current_version)

    def run(self):
        time.sleep(10)
        try:
            # Elegir dinámicamente el archivo según el canal
            version_file = "update-dev.json" if "-dev" in self.current_version else "update.json"
            url = f"https://raw.githubusercontent.com/UlisesMilani/dextop-whatsapp-voice/main/{version_file}?t={int(time.time())}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5.0) as response:
                data = json.loads(response.read().decode('utf-8'))
                remote_version = data.get("version")
                if remote_version and is_new_version(remote_version, self.current_version):
                    import wx
                    import gui
                    download_url = data.get("downloadUrl")

                    def prompt_update():
                        res = gui.messageBox(
                            _("A new version of Dextop WhatsApp Voice is available. Would you like to download and install it now?"),
                            _("Update Available"),
                            wx.YES_NO | wx.ICON_QUESTION
                        )
                        if res == wx.YES:
                            if download_url:
                                downloader = UpdateDownloaderThread(download_url)
                                downloader.start()
                            else:
                                os.startfile("https://github.com/UlisesMilani/dextop-whatsapp-voice/releases/latest")

                    wx.CallAfter(prompt_update)
        except Exception as e:
            log.error(f"Dextop WhatsApp Voice: Update checker failed: {e}", exc_info=True)

class DextopWhatsAppVoiceThread(threading.Thread):
    def __init__(self, js_code):
        super().__init__()
        self.daemon = True
        self.js_code = js_code
        self.running = True
        self.connected_url = None
        self.last_status = "Iniciando"
        self.last_error = ""
        self.last_targets = []
        self.inject_count = 0

    def run(self):
        write_registry_policy()
        self.last_status = "Configurado. Abre WhatsApp o ciérralo completamente y vuelve a abrirlo."
        while self.running:
            try:
                if not self.connected_url:
                    ws_url = self.find_whatsapp_ws_url()
                    if ws_url:
                        log.info("Dextop WhatsApp Voice: Puerto detectado. Conectando a %s", ws_url)
                        self.inject_and_hold(ws_url)
                    else:
                        if is_debug_port_open():
                            self.last_status = "Puerto abierto, esperando página de WhatsApp"
                        else:
                            self.last_status = "Esperando WhatsApp con puerto %d. Cierra y abre WhatsApp si ya estaba abierto." % DEBUG_PORT
                time.sleep(3)
            except Exception as e:
                self.last_error = str(e)
                self.last_status = "Error en bucle de inyección"
                log.error("Dextop WhatsApp Voice: Error en bucle de inyección: %s", e)
                time.sleep(3)

    def get_json_targets(self):
        last_exc = None
        for endpoint in ("json/list", "json"):
            try:
                url = "http://127.0.0.1:%d/%s" % (DEBUG_PORT, endpoint)
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=2.0) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as e:
                last_exc = e
        raise last_exc or Exception("No se pudo leer lista CDP")

    def find_whatsapp_ws_url(self):
        try:
            data = self.get_json_targets()
            self.last_targets = data if isinstance(data, list) else []
            # Primero preferir la página real de WhatsApp Web.
            for target in self.last_targets:
                t_type = target.get("type", "")
                t_url = target.get("url", "")
                title = target.get("title", "")
                ws_url = target.get("webSocketDebuggerUrl", "")
                combined = (t_url + " " + title).lower()
                if t_type == "page" and ws_url and ("web.whatsapp.com" in combined or "whatsapp" in combined):
                    return ws_url
            # Si el WebView todavía carga en blanco, usar la página disponible.
            for target in self.last_targets:
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                    return target.get("webSocketDebuggerUrl")
        except Exception as e:
            self.last_error = str(e)
        return None

    def inject_and_hold(self, ws_url):
        client = None
        try:
            client = MinWSClient(ws_url)
            client.connect()
            self.connected_url = ws_url
            self.last_status = "Conectado al WebView de WhatsApp"
            self.last_error = ""

            commands = [
                {"id": 1, "method": "Page.enable"},
                {"id": 2, "method": "Runtime.enable"},
                {"id": 3, "method": "Page.addScriptToEvaluateOnNewDocument", "params": {"source": self.js_code}},
                {"id": 4, "method": "Runtime.evaluate", "params": {"expression": self.js_code, "awaitPromise": False}},
            ]
            for cmd in commands:
                client.send_text(json.dumps(cmd))
                time.sleep(0.15)

            self.inject_count += 1
            log.info("Dextop WhatsApp Voice: Script inyectado en WhatsApp Desktop.")
            self.last_status = "Conectado e inyectado. Prueba grabar un audio nuevo."

            client.sock.settimeout(1.0)
            while self.running:
                try:
                    data = client.sock.recv(1024)
                    if not data:
                        log.info("Dextop WhatsApp Voice: WebSocket cerrado por WhatsApp.")
                        break
                except socket.timeout:
                    try:
                        client.send_text(json.dumps({
                            "id": 9000 + self.inject_count,
                            "method": "Runtime.evaluate",
                            "params": {"expression": "window.__dextopWhatsappVoiceStatus || 'sin estado'"}
                        }))
                    except Exception:
                        log.info("Dextop WhatsApp Voice: Canal WebSocket perdido.")
                        break
                time.sleep(5)
        except Exception as e:
            self.last_error = str(e)
            self.last_status = "Error al inyectar"
            log.error("Dextop WhatsApp Voice: Error durante inyección CDP: %s", e)
        finally:
            if client:
                client.close()
            self.connected_url = None


class SecurityWarningDialog(wx.Dialog):
    """Diálogo de advertencia de seguridad inicial y atajos."""
    def __init__(self, parent, title, message, config_file):
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP)
        self.config_file = config_file
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        text = wx.StaticText(self, label=message)
        text.Wrap(450)
        sizer.Add(text, 0, wx.ALL | wx.EXPAND, 15)
        
        self.dont_show_checkbox = wx.CheckBox(self, label=_("Don't show this warning again"))
        sizer.Add(self.dont_show_checkbox, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 15)
        
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        ok_btn = wx.Button(self, wx.ID_OK, label=_("OK"))
        ok_btn.SetDefault()
        btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
        
        info_btn = wx.Button(self, label=_("Read Documentation"))
        info_btn.Bind(wx.EVT_BUTTON, self.on_info)
        btn_sizer.Add(info_btn, 0, wx.ALL, 5)
        
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 15)
        
        self.SetSizer(sizer)
        self.Fit()
        self.CenterOnScreen()

    def on_info(self, event):
        try:
            addon = addonHandler.getCodeAddon()
            doc_path = addon.getDocFilePath("readme.html")
            if doc_path and os.path.exists(doc_path):
                os.startfile(doc_path)
            else:
                os.startfile("https://github.com/UlisesMilani/dextop-whatsapp-voice")
        except Exception:
            pass

    def Destroy(self):
        if self.dont_show_checkbox.GetValue():
            try:
                with open(self.config_file, "w") as f:
                    json.dump({"show_warning": False}, f)
            except Exception:
                pass
        return super().Destroy()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        if globalVars.appArgs.secure:
            log.warning("Dextop WhatsApp Voice: Deshabilitado en pantallas seguras.")
            raise ValueError(_("This add-on cannot be run on secure screens."))

        log.info("Dextop WhatsApp Voice: Iniciando inicialización...")
        
        # Cargar preferencia de aviso de seguridad
        show_warning = True
        config_file = os.path.join(globalVars.appArgs.configPath, "dextop_whatsapp_voice_config.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    cfg = json.load(f)
                    show_warning = cfg.get("show_warning", True)
            except Exception:
                pass

        if show_warning and gui:
            def show_warn():
                msg = _(
                    "Security Warning:\n\n"
                    "This add-on enables a local debugging port on 127.0.0.1:59222 to inject a high-fidelity audio bridge into WhatsApp Desktop. "
                    "No data transmission to external servers was observed, but it is recommended to use it only on trusted personal computers.\n\n"
                    "To begin:\n"
                    "1. Close WhatsApp completely.\n"
                    "2. Open WhatsApp again.\n"
                    "3. Verify the status using NVDA+Shift+W.\n\n"
                    "For more information, please read the add-on documentation."
                )
                parent = gui.mainFrame
                dlg = SecurityWarningDialog(parent, _("Dextop WhatsApp Voice - Security Warning"), msg, config_file)
                dlg.ShowModal()
                dlg.Destroy()
            wx.CallAfter(show_warn)
        self.thread = None
        try:
            current_dir = os.path.dirname(__file__)
            js_path = os.path.join(current_dir, "accessibility_and_audio_bridge.js")
            with open(js_path, "r", encoding="utf-8") as f:
                js_code = f.read()
            self.thread = DextopWhatsAppVoiceThread(js_code)
            self.thread.start()
            log.info("Dextop WhatsApp Voice: Hilo iniciado.")
        except Exception as e:
            log.error("Dextop WhatsApp Voice: No se pudo cargar JS o iniciar hilo: %s", e)

        # Comprobar actualizaciones
        try:
            addon = addonHandler.getCodeAddon()
            current_version = addon.version
            log.info("Dextop WhatsApp Voice: Inicializando complemento %s.", current_version)
            self.checker = UpdateCheckerThread(current_version)
            self.checker.start()
        except Exception as e:
            log.error("Dextop WhatsApp Voice: No se pudo iniciar el comprobador de actualización: %s", e)

    def terminate(self):
        log.info("Dextop WhatsApp Voice: Terminando complemento.")
        if self.thread:
            self.thread.running = False
            self.thread.join(timeout=2.0)
        
        # Limpiar registro al salir de NVDA para cumplir políticas de la tienda
        cleanup_registry_policy()
        super().terminate()

    if script:
        @script(description=_("Check Dextop WhatsApp Voice status"), gesture="kb:NVDA+shift+w")
        def script_checkWhatsAppVoiceStatus(self, gesture):
            msg = "Dextop WhatsApp Voice: "
            if not self.thread:
                msg += "el hilo no inició."
            elif self.thread.connected_url:
                msg += "conectado e inyectado."
            else:
                msg += self.thread.last_status
                if self.thread.last_error:
                    msg += ". Error: " + self.thread.last_error
            if ui:
                ui.message(msg)
            log.info(msg)

        @script(description=_("Rewrite WebView2 registry keys for Dextop WhatsApp Voice"), gesture="kb:NVDA+control+shift+w")
        def script_rewriteWhatsAppVoiceRegistry(self, gesture):
            write_registry_policy()
            msg = "Dextop WhatsApp Voice: configuración reescrita. Cierra WhatsApp completamente y vuelve a abrirlo."
            if self.thread:
                self.thread.last_status = msg
                self.thread.last_error = ""
            if ui:
                ui.message(msg)
            log.info(msg)

        @script(description=_("Disable Dextop WhatsApp Voice WebView2 configuration"), gesture="kb:NVDA+alt+shift+w")
        def script_disableWhatsAppVoiceConfig(self, gesture):
            cleanup_registry_policy()
            msg = "Dextop WhatsApp Voice: configuración desactivada. Cierra y vuelve a abrir WhatsApp para quitar el puerto."
            if self.thread:
                self.thread.last_status = msg
                self.thread.last_error = ""
            if ui:
                ui.message(msg)
            log.info(msg)
