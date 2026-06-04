import globalPluginHandler
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

log = logging.getLogger("nvda.metavoice_desktop")

class MinWSClient:
    """Un cliente WebSocket minimalista en Python puro para comunicarse con el protocolo CDP."""
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

        # Realizar el handshake del protocolo WebSocket
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
        
        # Leer la respuesta de la cabecera HTTP
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(1024)
            if not chunk:
                break
            response += chunk
            if len(response) > 8192:
                raise Exception("Handshake de WebSocket demasiado largo")

        if b" 101 " not in response:
            raise Exception("Fallo en el handshake de WebSocket")

    def send_text(self, text):
        data = text.encode('utf-8')
        length = len(data)
        frame = bytearray([0x81]) # FIN = 1, Opcode = 1 (Texto)
        
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
        
        # Enmascarar los datos antes de enviar (requerido para clientes WebSocket)
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


class MetaVoicePluginThread(threading.Thread):
    """Hilo de segundo plano para monitorear WhatsApp Desktop e inyectar el script."""
    def __init__(self, js_code):
        super().__init__()
        self.daemon = True
        self.js_code = js_code
        self.running = True
        self.connected_url = None

    def run(self):
        # 1. Configurar la política de registro de WebView2 para habilitar depuración en WhatsApp.exe
        self.setup_registry_policy()

        # 2. Bucle principal de monitoreo e inyección
        while self.running:
            if not self.connected_url:
                try:
                    ws_url = self.find_whatsapp_ws_url()
                    if ws_url:
                        log.info(f"MetaVoice Desktop: Puerto de depuración de WhatsApp detectado. Conectando a {ws_url}...")
                        self.inject_and_hold(ws_url)
                except Exception as e:
                    log.error(f"MetaVoice Desktop: Error en el bucle de inyección: {e}")
            time.sleep(5)

    def setup_registry_policy(self):
        # WhatsApp Desktop corre bajo el ejecutable WhatsApp.Root.exe.
        # WebView2 busca en dos ubicaciones del registro para los AdditionalBrowserArguments.
        # Las configuramos en ambas rutas para garantizar que se apliquen en entornos paquetizados.
        paths_to_write = [
            (winreg.HKEY_CURRENT_USER, r"Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Edge\WebView2\AdditionalBrowserArguments")
        ]
        for hkey, key_path in paths_to_write:
            try:
                key = winreg.CreateKey(hkey, key_path)
                # Configurar para WhatsApp.Root.exe y WhatsApp.exe por si acaso
                winreg.SetValueEx(key, "WhatsApp.Root.exe", 0, winreg.REG_SZ, "--remote-debugging-port=9222")
                winreg.SetValueEx(key, "WhatsApp.exe", 0, winreg.REG_SZ, "--remote-debugging-port=9222")
                winreg.CloseKey(key)
                log.info(f"MetaVoice Desktop: Registro configurado en {key_path}")
            except Exception as e:
                log.error(f"MetaVoice Desktop: Falló al escribir en {key_path}: {e}")

    def find_whatsapp_ws_url(self):
        try:
            url = "http://127.0.0.1:9222/json"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2.0) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            for target in data:
                t_type = target.get('type', '')
                t_url = target.get('url', '')
                ws_url = target.get('webSocketDebuggerUrl', '')
                
                # Comprobar si corresponde a la interfaz web de WhatsApp Desktop.
                # A veces al inicio la URL figura como 'about:blank' o 'https://web.whatsapp.com/...'
                if t_type == 'page' and ws_url:
                    if 'web.whatsapp.com' in t_url or 'whatsapp' in t_url or 'about:blank' in t_url:
                        return ws_url
        except Exception:
            # WhatsApp cerrado o puerto cerrado, no es error crítico
            pass
        return None

    def inject_and_hold(self, ws_url):
        client = None
        try:
            client = MinWSClient(ws_url)
            client.connect()
            self.connected_url = ws_url

            # 1. Habilitar la API de página (Page) en el CDP
            client.send_text(json.dumps({
                "id": 1,
                "method": "Page.enable"
            }))
            time.sleep(0.1)

            # 2. Registrar el script para inyección automática en futuras recargas o navegaciones
            client.send_text(json.dumps({
                "id": 2,
                "method": "Page.addScriptToEvaluateOnNewDocument",
                "params": {
                    "source": self.js_code
                }
            }))
            time.sleep(0.1)

            # 3. Evaluar el script inmediatamente en la sesión actual
            client.send_text(json.dumps({
                "id": 3,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": self.js_code
                }
            }))
            log.info("MetaVoice Desktop: ¡Script inyectado con éxito en la ventana de WhatsApp Desktop!")

            # 4. Mantener la conexión abierta para verificar que WhatsApp siga activo
            client.sock.settimeout(1.0)
            while self.running:
                try:
                    data = client.sock.recv(1024)
                    if not data:
                        log.info("MetaVoice Desktop: La conexión de WebSocket fue cerrada por WhatsApp.")
                        break
                except socket.timeout:
                    # Enviar un comando de latido (ping) para validar el canal de comunicación
                    try:
                        client.send_text(json.dumps({
                            "id": 999,
                            "method": "Runtime.evaluate",
                            "params": {"expression": "1+1"}
                        }))
                    except Exception:
                        log.info("MetaVoice Desktop: Canal de WebSocket perdido.")
                        break
                time.sleep(5)
        except Exception as e:
            log.error(f"MetaVoice Desktop: Error durante la sesión de inyección CDP: {e}")
        finally:
            if client:
                client.close()
            self.connected_url = None


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        log.info("MetaVoice Desktop: Inicializando plugin global...")
        
        try:
            current_dir = os.path.dirname(__file__)
            js_path = os.path.join(current_dir, "accessibility_and_audio_bridge.js")
            with open(js_path, "r", encoding="utf-8") as f:
                js_code = f.read()
            
            # Iniciar el hilo de monitoreo
            self.thread = MetaVoicePluginThread(js_code)
            self.thread.start()
            log.info("MetaVoice Desktop: Hilo de monitoreo e inyección inicializado con éxito.")
        except Exception as e:
            log.error(f"MetaVoice Desktop: Error al cargar el archivo JS o al arrancar el hilo: {e}")

    def terminate(self):
        log.info("MetaVoice Desktop: Finalizando plugin...")
        if hasattr(self, 'thread'):
            self.thread.running = False
            self.thread.join(timeout=2.0)
        super().terminate()
