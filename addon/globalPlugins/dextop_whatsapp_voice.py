import globalPluginHandler
import globalVars
import os
import logging
import threading
import time
import urllib.request
import urllib.parse
import json
import socket
import struct
import base64
import random
import winreg
import addonHandler

# Initialize translation support
addonHandler.initTranslation()

log = logging.getLogger("nvda.dextop_whatsapp_voice")

# Module level flag to prevent duplicate dialogs in a single session
_registry_warning_shown = False


class MinWSClient:
    """Minimal pure-Python WebSocket client for Chrome DevTools Protocol."""
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.sock = None

    def connect(self):
        parsed = urllib.parse.urlparse(self.ws_url)
        host = parsed.hostname
        port = parsed.port or 80
        path = parsed.path
        if parsed.query:
            path += "?" + parsed.query

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(2.0)
        self.sock.connect((host, port))

        # Perform handshake
        sec_key = base64.b64encode(bytes(random.randint(0, 255) for _ in range(16))).decode('utf-8')
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {sec_key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode('utf-8'))
        
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(1024)
            if not chunk:
                break
            response += chunk
            if len(response) > 8192:
                raise Exception("Handshake response too long")

        if b" 101 " not in response:
            raise Exception("WebSocket handshake failed")

    def send_text(self, text):
        data = text.encode('utf-8')
        length = len(data)
        frame = bytearray([0x81]) # FIN=1, Opcode=1 (Text)
        
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
        
        masked_data = bytearray(b ^ mask[i % 4] for i, b in enumerate(data))
        frame.extend(masked_data)
        self.sock.sendall(frame)

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


class DextopWhatsAppVoiceThread(threading.Thread):
    """Background thread to monitor WhatsApp Desktop WebView2 and inject the script."""
    def __init__(self, js_code):
        super().__init__()
        self.daemon = True
        self.js_code = js_code
        self.running = True
        self.connected_url = None

    def run(self):
        self.setup_registry_policy()

        while self.running:
            if not self.connected_url:
                try:
                    ws_url = self.find_whatsapp_ws_url()
                    if ws_url:
                        log.info(f"Dextop WhatsApp Voice: WhatsApp debugging port detected. Connecting to {ws_url}...")
                        self.inject_and_hold(ws_url)
                except Exception as e:
                    log.error(f"Dextop WhatsApp Voice: Error in the injection loop: {e}")
            time.sleep(5)

    def setup_registry_policy(self):
        paths_to_write = [
            (winreg.HKEY_CURRENT_USER, r"Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Edge\WebView2\AdditionalBrowserArguments")
        ]
        for hkey, key_path in paths_to_write:
            try:
                key = winreg.CreateKey(hkey, key_path)
                winreg.SetValueEx(key, "WhatsApp.Root.exe", 0, winreg.REG_SZ, "--remote-debugging-port=59222")
                winreg.SetValueEx(key, "WhatsApp.exe", 0, winreg.REG_SZ, "--remote-debugging-port=59222")
                winreg.CloseKey(key)
                log.info(f"Dextop WhatsApp Voice: Registry configured at {key_path}")
                
                # Verification read
                verify_key = winreg.OpenKey(hkey, key_path, 0, winreg.KEY_READ)
                val_root, _ = winreg.QueryValueEx(verify_key, "WhatsApp.Root.exe")
                val_exe, _ = winreg.QueryValueEx(verify_key, "WhatsApp.exe")
                winreg.CloseKey(verify_key)
                log.info(f"Dextop WhatsApp Voice: Registry verified successfully: Root={val_root}, Exe={val_exe}")
            except PermissionError as pe:
                log.error(f"Dextop WhatsApp Voice: Permission Denied writing registry at {key_path}. Policies might be locked by GPO or Antivirus: {pe}")
                self.trigger_registry_warning()
            except Exception as e:
                log.error(f"Dextop WhatsApp Voice: Failed to write/verify registry at {key_path}: {e}")

    def trigger_registry_warning(self):
        global _registry_warning_shown
        if not _registry_warning_shown:
            _registry_warning_shown = True
            import wx
            import gui
            
            def show_warn():
                gui.messageBox(
                    message=_("Dextop WhatsApp Voice: Access denied to the Windows Registry. Audio quality improvements might not work. Please try running NVDA as Administrator once or check your antivirus settings."),
                    title=_("Registry Access Denied"),
                    style=wx.OK | wx.ICON_WARNING
                )
            wx.CallAfter(show_warn)

    def find_whatsapp_ws_url(self):
        try:
            url = "http://127.0.0.1:59222/json"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2.0) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            for target in data:
                t_type = target.get('type', '')
                t_url = target.get('url', '')
                ws_url = target.get('webSocketDebuggerUrl', '')
                
                if t_type == 'page' and ws_url:
                    if 'web.whatsapp.com' in t_url or 'whatsapp' in t_url or 'about:blank' in t_url:
                        return ws_url
        except Exception:
            pass
        return None

    def inject_and_hold(self, ws_url):
        client = None
        try:
            client = MinWSClient(ws_url)
            client.connect()
            self.connected_url = ws_url

            # Enable Page API
            client.send_text(json.dumps({
                "id": 1,
                "method": "Page.enable"
            }))
            time.sleep(0.1)

            # Auto-inject script on page reloads/navigations
            client.send_text(json.dumps({
                "id": 2,
                "method": "Page.addScriptToEvaluateOnNewDocument",
                "params": {
                    "source": self.js_code
                }
            }))
            time.sleep(0.1)

            # Inject script immediately into current session
            client.send_text(json.dumps({
                "id": 3,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": self.js_code
                }
            }))
            log.info("Dextop WhatsApp Voice: Script successfully injected into the WhatsApp Desktop window!")

            # Hold WebSocket connection open to check if target is alive
            client.sock.settimeout(1.0)
            while self.running:
                try:
                    data = client.sock.recv(1024)
                    if not data:
                        log.info("Dextop WhatsApp Voice: WebSocket connection closed by WhatsApp.")
                        break
                except socket.timeout:
                    # Ping target to validate connection channel
                    try:
                        client.send_text(json.dumps({
                            "id": 999,
                            "method": "Runtime.evaluate",
                            "params": {"expression": "1+1"}
                        }))
                    except Exception:
                        log.info("Dextop WhatsApp Voice: WebSocket channel lost.")
                        break
                time.sleep(5)
        except Exception as e:
            log.error(f"Dextop WhatsApp Voice: Error during the CDP injection session: {e}")
        finally:
            if client:
                client.close()
            self.connected_url = None


def parse_version(v_str):
    """Parses version strings like 1.0-dev1 into a comparable tuple (([1, 0], 1))."""
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
    """Compares version strings supporting dev channel suffixes (e.g. 1.0-dev2 > 1.0-dev1)."""
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


class UpdateCheckerThread(threading.Thread):
    """Asynchronously checks GitHub repository for add-on updates on the dev channel."""
    def __init__(self, current_version):
        super().__init__()
        self.daemon = True
        self.current_version = str(current_version)

    def run(self):
        time.sleep(10)
        try:
            url = "https://raw.githubusercontent.com/UlisesMilani/dextop-whatsapp-voice/main/update-dev.json"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5.0) as response:
                data = json.loads(response.read().decode('utf-8'))
                remote_version = data.get("version")
                if remote_version and is_new_version(remote_version, self.current_version):
                    import wx
                    import gui
                    
                    def prompt_update():
                        res = gui.messageBox(
                            message=_("A new version of Dextop WhatsApp Voice is available. Would you like to open the download page?"),
                            title=_("Update Available"),
                            style=wx.YES_NO | wx.ICON_QUESTION
                        )
                        if res == wx.YES:
                            import os
                            os.startfile("https://github.com/UlisesMilani/dextop-whatsapp-voice/releases/latest")
                    
                    wx.CallAfter(prompt_update)
        except Exception:
            pass


def cleanup_registry_policy():
    """Removes remote debugging registry keys for WhatsApp."""
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
                    log.info(f"Dextop WhatsApp Voice: Registry cleaned at {key_path} for {name}")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except FileNotFoundError:
            pass
        except Exception as e:
            log.error(f"Dextop WhatsApp Voice: Error cleaning registry: {e}")


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        # Validate secure screens
        if globalVars.appArgs.secure:
            log.warning("Dextop WhatsApp Voice: Disabled on secure screens for security reasons.")
            raise ValueError(_("This add-on cannot be run on secure screens."))

        log.info("Dextop WhatsApp Voice: Global plugin initializing...")
        
        try:
            current_dir = os.path.dirname(__file__)
            js_path = os.path.join(current_dir, "accessibility_and_audio_bridge.js")
            with open(js_path, "r", encoding="utf-8") as f:
                js_code = f.read()
            
            # Start monitoring thread
            self.thread = DextopWhatsAppVoiceThread(js_code)
            self.thread.start()
            log.info("Dextop WhatsApp Voice: Monitoring thread and injection initialized successfully.")
        except Exception as e:
            log.error(f"Dextop WhatsApp Voice: Failed to load JS file or start the thread: {e}")

        # Start update check
        try:
            addon = addonHandler.getCodeAddon()
            current_version = addon.manifest.version
            self.checker = UpdateCheckerThread(current_version)
            self.checker.start()
        except Exception as e:
            log.error(f"Dextop WhatsApp Voice: Failed to start update checker: {e}")

    def terminate(self):
        log.info("Dextop WhatsApp Voice: Terminating plugin...")
        if hasattr(self, 'thread'):
            self.thread.running = False
            self.thread.join(timeout=2.0)
        
        cleanup_registry_policy()
        super().terminate()
