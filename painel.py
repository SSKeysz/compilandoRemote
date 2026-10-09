"""
PILOTO - controle do PC pelo celular via Wi-Fi (LAN) ou Cloudflare Tunnel.
Uso pessoal, Windows.
"""
import io
import os
import re
import sys
import json
import time
import base64
import socket
import ctypes
import secrets
import logging
import tempfile
import threading
import subprocess
import webbrowser
import urllib.request

try:
    import winreg
except Exception:
    winreg = None

from flask import Flask, Response, jsonify, request, session, send_file

try:
    import mss as _mss
    from PIL import Image as _PILImage
    TEM_MSS = True
except Exception:
    TEM_MSS = False
    _mss = None
    _PILImage = None

try:
    from PIL import ImageGrab
except Exception:
    ImageGrab = None

try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from comtypes import CLSCTX_ALL
    PYCAW_OK = True
except Exception:
    PYCAW_OK = False

ABRIR_NAVEGADOR_NO_PC = False
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
logging.getLogger("werkzeug").setLevel(logging.ERROR)


def esconder_console():
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def executar(args, **kw):
    kw.setdefault("stdin", subprocess.DEVNULL)
    kw.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.run(args, **kw)


def rodar_oculto(args, **kw):
    kw.setdefault("stdin", subprocess.DEVNULL)
    kw.setdefault("stdout", subprocess.DEVNULL)
    kw.setdefault("stderr", subprocess.DEVNULL)
    kw.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.Popen(args, **kw)


def pasta_base():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


ARQ_CONFIG = os.path.join(pasta_base(), "piloto_config.json")

ACOES_PADRAO = [
    {"nome": "Explorer",     "tipo": "abrir", "valor": "explorer.exe"},
    {"nome": "Downloads",    "tipo": "pasta", "valor": r"%USERPROFILE%\Downloads"},
    {"nome": "Documentos",   "tipo": "pasta", "valor": r"%USERPROFILE%\Documents"},
    {"nome": "Notepad",      "tipo": "abrir", "valor": "notepad.exe"},
    {"nome": "Calculadora",  "tipo": "abrir", "valor": "calc.exe"},
    {"nome": "Gerenciador",  "tipo": "abrir", "valor": "taskmgr.exe"},
    {"nome": "YouTube",      "tipo": "url",   "valor": "https://youtube.com"},
    {"nome": "WhatsApp Web", "tipo": "url",   "valor": "https://web.whatsapp.com"},
]

CONFIG_PADRAO = {
    "pin": None,
    "modo": "lan",
    "pasta_arquivos": r"%USERPROFILE%\Desktop",
    "acoes": ACOES_PADRAO,
}


def carregar_config():
    cfg = {k: (v.copy() if isinstance(v, list) else v) for k, v in CONFIG_PADRAO.items()}
    try:
        with open(ARQ_CONFIG, "r", encoding="utf-8") as f:
            dados = json.load(f)
            if isinstance(dados, dict):
                for k in CONFIG_PADRAO:
                    if k in dados:
                        cfg[k] = dados[k]
    except Exception:
        pass
    if cfg.get("modo") not in ("lan", "wan"):
        cfg["modo"] = "lan"
    return cfg


def salvar_config():
    try:
        with open(ARQ_CONFIG, "w", encoding="utf-8") as f:
            json.dump(ESTADO, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


ESTADO = carregar_config()


def pasta_arquivos():
    p = os.path.expandvars(ESTADO.get("pasta_arquivos") or "")
    if not p or not os.path.isdir(p):
        p = os.path.expanduser("~")
    return p


app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024


def autenticado():
    return not ESTADO.get("pin") or session.get("ok") is True


def exigir_auth():
    if not autenticado():
        return jsonify(erro="nao autenticado"), 401
    return None


def ip_local():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def log_seguro(*a):
    try:
        print(*a)
    except Exception:
        pass


# ---------- autostart ----------
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_NOME = "Piloto"


def autostart_ativo():
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, REG_NOME)
            return True
    except Exception:
        return False


def set_autostart(ativo):
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE) as k:
            if ativo:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    pyw = sys.executable.replace("python.exe", "pythonw.exe")
                    cmd = (f'"{pyw}" "{os.path.abspath(__file__)}"' if os.path.exists(pyw)
                           else f'"{sys.executable}" "{os.path.abspath(__file__)}"')
                winreg.SetValueEx(k, REG_NOME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, REG_NOME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        log_seguro("erro autostart:", e)
        return False


# ---------- tunel ----------
TUNEL = {"proc": None, "url": None, "thread": None, "ativo": False}
CF_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"


def caminho_cloudflared():
    return os.path.join(pasta_base(), "cloudflared.exe")


def baixar_cloudflared():
    d = caminho_cloudflared()
    if os.path.exists(d):
        return d
    try:
        urllib.request.urlretrieve(CF_URL, d)
        return d
    except Exception as e:
        log_seguro("erro cloudflared:", e)
        return None


def _loop_tunel():
    TUNEL["url"] = "baixando cloudflared..."
    TUNEL["ativo"] = True
    cf = baixar_cloudflared()
    if not cf:
        TUNEL["url"] = "ERRO: nao consegui baixar"
        TUNEL["ativo"] = False
        return
    TUNEL["url"] = "iniciando tunel..."
    try:
        proc = subprocess.Popen(
            [cf, "tunnel", "--url", "http://localhost:5000", "--no-autoupdate"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, bufsize=1,
            creationflags=CREATE_NO_WINDOW)
        TUNEL["proc"] = proc
        ur = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
        for l in proc.stdout:
            m = ur.search(l)
            if m:
                TUNEL["url"] = m.group(0)
                TUNEL["ativo"] = True
                log_seguro("Tunel:", TUNEL["url"])
                break
        for _ in proc.stdout:
            pass
    except Exception as e:
        log_seguro("erro tunel:", e)
        TUNEL["url"] = "ERRO: " + str(e)
        TUNEL["ativo"] = False


def parar_tunel():
    p = TUNEL.get("proc")
    TUNEL["proc"] = None
    TUNEL["ativo"] = False
    TUNEL["url"] = None
    if p is not None:
        try:
            executar(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def iniciar_tunel_async():
    if TUNEL["ativo"] or (TUNEL["thread"] and TUNEL["thread"].is_alive()):
        return
    TUNEL["ativo"] = True
    TUNEL["url"] = "iniciando..."
    TUNEL["thread"] = threading.Thread(target=_loop_tunel, daemon=True)
    TUNEL["thread"].start()


# ---------- autodelete (BYPASS) ----------
def agendar_autodelete():
    if not getattr(sys, "frozen", False):
        return False
    exe = sys.executable
    cf = caminho_cloudflared()
    bat = os.path.join(tempfile.gettempdir(), "piloto_cleanup.bat")
    vbs = os.path.join(tempfile.gettempdir(), "piloto_cleanup.vbs")

    linhas_bat = [
        "@echo off",
        ":waitloop",
        "timeout /t 1 /nobreak >nul 2>&1",
        f'del /f /q "{exe}" >nul 2>&1',
        f'if exist "{exe}" goto waitloop',
        f'del /f /q "{cf}" >nul 2>&1',
        f'del /f /q "{ARQ_CONFIG}" >nul 2>&1',
        'del /f /q "%~f0" >nul 2>&1',
    ]
    try:
        with open(bat, "w", encoding="utf-8") as f:
            f.write("\r\n".join(linhas_bat))
    except Exception as e:
        log_seguro("erro criando bat:", e)
        return False

    vbs_content = f'CreateObject("Wscript.Shell").Run "cmd /c ""{bat}""", 0, False'
    try:
        with open(vbs, "w", encoding="utf-8") as f:
            f.write(vbs_content)
    except Exception as e:
        log_seguro("erro criando vbs:", e)
        return False

    try:
        subprocess.Popen(["wscript.exe", vbs],
                         creationflags=CREATE_NO_WINDOW,
                         stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        log_seguro("erro vbs:", e)
        return False
