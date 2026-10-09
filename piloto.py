"""
PILOTO - controle do PC pelo celular via Wi-Fi (LAN). Windows.
Uso pessoal.

Compilar:
    build.bat (faz tudo)
ou:
    pip install flask pycaw comtypes pyinstaller
    pyinstaller --noconsole --onefile --name piloto --hidden-import=pycaw --hidden-import=pycaw.pycaw --hidden-import=comtypes --hidden-import=comtypes.client piloto.py
"""
import os
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

from flask import Flask, Response, jsonify, request, session, send_file

# volume real (opcional, mas recomendado)
try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from comtypes import CLSCTX_ALL
    PYCAW_OK = True
except ImportError:
    PYCAW_OK = False

ABRIR_NAVEGADOR_NO_PC = True
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
    {"nome": "Explorer",       "tipo": "abrir",  "valor": "explorer.exe"},
    {"nome": "Downloads",      "tipo": "pasta",  "valor": r"%USERPROFILE%\Downloads"},
    {"nome": "Documentos",     "tipo": "pasta",  "valor": r"%USERPROFILE%\Documents"},
    {"nome": "Bloco de Notas", "tipo": "abrir",  "valor": "notepad.exe"},
    {"nome": "Calculadora",    "tipo": "abrir",  "valor": "calc.exe"},
    {"nome": "Gerenciador",    "tipo": "abrir",  "valor": "taskmgr.exe"},
    {"nome": "YouTube",        "tipo": "url",    "valor": "https://youtube.com"},
    {"nome": "WhatsApp Web",   "tipo": "url",    "valor": "https://web.whatsapp.com"},
]

CFG_PADRAO = {
    "pin": None,
    "pasta_arquivos": r"%USERPROFILE%\Desktop",
    "acoes": ACOES_PADRAO,
}


def carregar_cfg():
    try:
        with open(ARQ_CONFIG, "r", encoding="utf-8") as f:
            dados = json.load(f)
        base = dict(CFG_PADRAO)
        base.update(dados)
        return base
    except Exception:
        cfg = dict(CFG_PADRAO)
        salvar_cfg(cfg)
        return cfg


def salvar_cfg(cfg):
    try:
        with open(ARQ_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


CFG = carregar_cfg()


def pasta_arquivos():
    p = os.path.expandvars(CFG.get("pasta_arquivos") or "")
    if not p or not os.path.isdir(p):
        p = os.path.expanduser("~")
    return p


app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024


def autenticado():
    return not CFG.get("pin") or session.get("ok") is True


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


# ============================================================
#                     PAGINA HTML
# ============================================================

PAGINA = r"""
<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<title>PILOTO</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0a0a0d">
<style>
:root{
  --bg:#0a0a0d; --panel:#14141a; --line:#242430; --fg:#eaeaf2;
  --mut:#8c8c9c; --acc:#2f7dff; --acc2:#4b8fff; --red:#c82020;
  color-scheme:dark;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;background:var(--bg);color:var(--fg);font:15px/1.4 -apple-system,system-ui,sans-serif}
body{padding:env(safe-area-inset-top) 0 calc(64px + env(safe-area-inset-bottom))}
header{padding:14px 16px 8px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;background:var(--bg);z-index:5}
h1{margin:0;font-size:18px;letter-spacing:1px;display:flex;align-items:center;gap:8px}
h1 .dot{width:8px;height:8px;border-radius:50%;background:#23d160;box-shadow:0 0 8px #23d160;animation:p 2s infinite}
@keyframes p{50%{opacity:.4}}
main{padding:0 12px 12px;display:grid;gap:10px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px}
h2{margin:0 0 10px;font-size:13px;text-transform:uppercase;color:var(--mut);letter-spacing:1px;font-weight:600}
.row{display:flex;gap:8px;align-items:center}
.grid{display:grid;gap:8px}
.g2{grid-template-columns:1fr 1fr}
.g3{grid-template-columns:1fr 1fr 1fr}
.g4{grid-template-columns:1fr 1fr 1fr 1fr}
button,.btn{border:0;background:#1f1f2a;color:var(--fg);padding:13px 12px;border-radius:10px;
  font:inherit;font-weight:600;cursor:pointer;text-align:center;transition:.15s;user-select:none}
button:active,.btn:active{transform:scale(.96)}
.btn.acc{background:var(--acc);color:#fff}
.btn.acc:hover{background:var(--acc2)}
.btn.red{background:var(--red);color:#fff}
.btn.ghost{background:transparent;border:1px solid var(--line)}
.btn.block{width:100%}
.btn.icon{font-size:22px;padding:16px 8px}
input,textarea{background:#0d0d14;color:var(--fg);border:1px solid var(--line);
  border-radius:10px;padding:12px;font:inherit;width:100%;outline:none}
input:focus,textarea:focus{border-color:var(--acc)}
textarea{resize:vertical;min-height:80px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px}
.hint{color:var(--mut);font-size:12px;margin-top:6px}
#tela{width:100%;border-radius:10px;border:1px solid var(--line);display:block;background:#000}
nav{position:fixed;left:0;right:0;bottom:0;background:var(--panel);border-top:1px solid var(--line);
  display:flex;overflow-x:auto;padding:6px 4px calc(6px + env(safe-area-inset-bottom));z-index:10;
  scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav button{flex:1 0 auto;min-width:62px;background:transparent;display:flex;flex-direction:column;gap:3px;
  padding:8px 4px;font-size:10px;font-weight:500;color:var(--mut);border-radius:8px}
nav button .ico{font-size:20px}
nav button.on{color:var(--acc);background:#1a2340}
.hid{display:none!important}
.lock{position:fixed;inset:0;background:var(--bg);display:flex;align-items:center;justify-content:center;z-index:30}
.lockbox{width:260px;text-align:center}
.lockbox input{text-align:center;font-size:20px;letter-spacing:8px;margin:12px 0}
.toast{position:fixed;left:50%;bottom:78px;transform:translateX(-50%);background:#23232f;color:#fff;
  padding:10px 16px;border-radius:22px;font-size:13px;opacity:0;pointer-events:none;transition:.25s;z-index:40;max-width:90%}
.toast.on{opacity:1}
#txtArquivos{display:grid;gap:6px;max-height:340px;overflow:auto}
.arq{display:flex;justify-content:space-between;align-items:center;background:#0d0d14;
  padding:11px 12px;border-radius:8px;font-size:13px;gap:8px}
.arq .nome{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.arq .tam{color:var(--mut);font-size:11px}
.arq button{padding:7px 12px;font-size:12px;background:var(--acc)}
.arq button.del{background:#3a1020}
input[type=range]{-webkit-appearance:none;appearance:none;background:transparent;outline:none;width:100%}
input[type=range]::-webkit-slider-runnable-track{height:8px;background:#242430;border-radius:4px}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:28px;height:28px;border-radius:50%;
  background:var(--acc);margin-top:-10px;box-shadow:0 0 0 4px rgba(47,125,255,.2)}
input[type=range]::-moz-range-track{height:8px;background:#242430;border-radius:4px;border:none}
input[type=range]::-moz-range-thumb{width:28px;height:28px;border-radius:50%;background:var(--acc);border:none}
</style>
</head>
<body>

<header>
  <h1><span class="dot"></span>PILOTO</h1>
  <span class="hint" id="ipTop"></span>
</header>

<main>

  <!-- ACOES -->
  <section id="p-acoes" class="page">
    <div class="panel">
      <h2>Acoes rapidas</h2>
      <div class="grid g2" id="gridAcoes"></div>
      <button class="btn ghost" style="margin-top:10px;width:100%" onclick="abrirNovaAcao()">+ Adicionar acao</button>
      <div class="hint">Toque para executar. Segure para remover.</div>
    </div>
  </section>

  <!-- TEXTO -->
  <section id="p-texto" class="page hid">
    <div class="panel">
      <h2>Enviar texto</h2>
      <textarea id="txtEnv" placeholder="Cole ou digite aqui..."></textarea>
      <div class="grid g2" style="margin-top:8px">
        <button class="btn acc" onclick="enviarTexto('clipboard')">Copiar pro PC</button>
        <button class="btn acc" onclick="enviarTexto('digitar')">Digitar no PC</button>
      </div>
      <div class="hint">"Digitar no PC" envia como teclado no cursor atual.</div>
    </div>
    <div class="panel">
      <h2>Pegar do PC</h2>
      <button class="btn acc btn block" onclick="pegarClipboard()">Ler area de transferencia</button>
      <textarea id="txtRec" style="margin-top:10px" readonly placeholder="(vazio)"></textarea>
      <button class="btn ghost btn block" style="margin-top:6px" onclick="copiarTexto()">Copiar (celular)</button>
    </div>
  </section>

  <!-- MIDIA -->
  <section id="p-midia" class="page hid">
    <div class="panel">
      <h2>Midia</h2>
      <div class="grid g3">
        <button class="btn icon" onclick="media('prev')">&#9198;</button>
        <button class="btn icon acc" onclick="media('play')">&#9199;</button>
        <button class="btn icon" onclick="media('next')">&#9197;</button>
      </div>
    </div>
    <div class="panel">
      <h2>Volume rapido</h2>
      <div class="grid g3">
        <button class="btn icon" onclick="media('vol_down')">&#128265;</button>
        <button class="btn icon" onclick="media('mute')">&#128263;</button>
        <button class="btn icon" onclick="media('vol_up')">&#128266;</button>
      </div>
    </div>
    <div class="panel">
      <h2>Player</h2>
      <button class="btn block" onclick="rodarPlayer()">Abrir player de musica</button>
    </div>
  </section>

  <!-- VOLUME -->
  <section id="p-volume" class="page hid">
    <div class="panel">
      <h2>Volume do PC</h2>
      <div style="display:flex;align-items:center;gap:14px;margin:14px 0">
        <span id="volIcon" style="font-size:30px">&#128266;</span>
        <span id="volNum" style="font-size:34px;font-weight:800;min-width:90px;text-align:right">--</span>
        <span style="color:var(--mut);font-size:20px">%</span>
      </div>
      <input type="range" id="volSlider" min="0" max="100" value="50"
        oninput="onVolSlide(this.value)" onchange="onVolCommit(this.value)">
      <div class="grid g4" style="margin-top:10px">
        <button class="btn ghost" onclick="setVol(0)">0</button>
        <button class="btn ghost" onclick="setVol(25)">25</button>
        <button class="btn ghost" onclick="setVol(50)">50</button>
        <button class="btn ghost" onclick="setVol(100)">100</button>
      </div>
      <button class="btn acc btn block" style="margin-top:12px" onclick="toggleMute()">Mudo (liga/desliga)</button>
      <div class="hint" id="volHint">—</div>
    </div>
  </section>

  <!-- ATALHOS -->
  <section id="p-atalhos" class="page hid">
    <div class="panel">
      <h2>Janelas / Sistema</h2>
      <div class="grid g2">
        <button class="btn" onclick="atalho('alt_tab')">Alt + Tab</button>
        <button class="btn" onclick="atalho('alt_f4')">Alt + F4</button>
        <button class="btn" onclick="atalho('win_d')">Win + D</button>
        <button class="btn" onclick="atalho('win_e')">Win + E</button>
        <button class="btn" onclick="atalho('win_r')">Win + R</button>
        <button class="btn" onclick="atalho('win_s')">Win + S</button>
        <button class="btn" onclick="atalho('win_tab')">Win + Tab</button>
        <button class="btn red" onclick="atalho('win_l')">Win + L</button>
      </div>
    </div>
    <div class="panel">
      <h2>Edicao</h2>
      <div class="grid g4">
        <button class="btn" onclick="atalho('ctrl_c')">Copia</button>
        <button class="btn" onclick="atalho('ctrl_v')">Cola</button>
        <button class="btn" onclick="atalho('ctrl_x')">Recorta</button>
        <button class="btn" onclick="atalho('ctrl_a')">Tudo</button>
        <button class="btn" onclick="atalho('ctrl_z')">Desfaz</button>
        <button class="btn" onclick="atalho('ctrl_y')">Refaz</button>
        <button class="btn" onclick="atalho('ctrl_s')">Salva</button>
        <button class="btn" onclick="atalho('ctrl_f')">Busca</button>
      </div>
    </div>
    <div class="panel">
      <h2>Teclas</h2>
      <div class="grid g4">
        <button class="btn ghost" onclick="atalho('enter')">Enter</button>
        <button class="btn ghost" onclick="atalho('esc')">Esc</button>
        <button class="btn ghost" onclick="atalho('tab')">Tab</button>
        <button class="btn ghost" onclick="atalho('backspace')">&#9003;</button>
        <button class="btn ghost" onclick="atalho('delete')">Del</button>
        <button class="btn ghost" onclick="atalho('space')">Espaco</button>
        <button class="btn ghost" onclick="atalho('up')">&#9650;</button>
        <button class="btn ghost" onclick="atalho('down')">&#9660;</button>
        <button class="btn ghost" onclick="atalho('left')">&#9664;</button>
        <button class="btn ghost" onclick="atalho('right')">&#9654;</button>
        <button class="btn ghost" onclick="atalho('f5')">F5</button>
        <button class="btn ghost" onclick="atalho('printscreen')">PrtSc</button>
      </div>
    </div>
    <div class="panel">
      <h2>Mouse</h2>
      <div class="grid g3">
        <button class="btn" onclick="mouse('scroll_up')">Scroll up</button>
        <button class="btn" onclick="mouse('left_click')">Click E</button>
        <button class="btn" onclick="mouse('scroll_down')">Scroll dn</button>
        <button class="btn ghost" onclick="mouse('double_click')">Duplo</button>
        <button class="btn ghost" onclick="mouse('middle_click')">Meio</button>
        <button class="btn ghost" onclick="mouse('right_click')">Click D</button>
      </div>
    </div>
  </section>

  <!-- TELA -->
  <section id="p-tela" class="page hid">
    <div class="panel">
      <h2>Tela do PC</h2>
      <div class="row" style="justify-content:space-between;margin-bottom:10px">
        <button class="btn ghost" onclick="atualizarTela()">Atualizar</button>
        <button class="btn acc" id="btnAuto" onclick="toggleAuto()">Ao vivo</button>
      </div>
      <img id="tela" alt="Tela do PC">
      <div class="hint" id="telaHora">—</div>
    </div>
  </section>

  <!-- ARQUIVOS -->
  <section id="p-arquivos" class="page hid">
    <div class="panel">
      <h2>Enviar celular para PC</h2>
      <input type="file" id="upFile" multiple>
      <button class="btn acc btn block" style="margin-top:8px" onclick="fazerUpload()">Enviar arquivo(s)</button>
      <div class="hint" id="pastaAtual">—</div>
    </div>
    <div class="panel">
      <h2>Arquivos no PC</h2>
      <div id="txtArquivos"></div>
    </div>
  </section>

  <!-- SISTEMA -->
  <section id="p-sistema" class="page hid">
    <div class="panel">
      <h2>Energia</h2>
      <div class="grid g2">
        <button class="btn" onclick="sistema('bloquear')">Bloquear</button>
        <button class="btn" onclick="sistema('dormir')">Dormir</button>
        <button class="btn red" onclick="sistema('desligar')">Desligar</button>
        <button class="btn red" onclick="sistema('reiniciar')">Reiniciar</button>
      </div>
      <button class="btn ghost btn block" style="margin-top:8px" onclick="sistema('cancelar')">Cancelar desligamento</button>
    </div>
    <div class="panel">
      <h2>Seguranca</h2>
      <input id="pinIn" type="password" placeholder="Novo PIN (4-32) — vazio remove">
      <div class="grid g2" style="margin-top:8px">
        <button class="btn acc" onclick="definirPin()">Definir PIN</button>
        <button class="btn ghost" onclick="removerPin()">Remover PIN</button>
      </div>
      <div class="hint" id="pinHint">—</div>
    </div>
    <div class="panel">
      <h2>Pasta de arquivos</h2>
      <input id="pastaIn" type="text" placeholder="C:\Users\Voce\Desktop">
      <button class="btn acc btn block" style="margin-top:8px" onclick="salvarPasta()">Salvar pasta</button>
    </div>
  </section>

</main>

<nav>
  <button data-t="acoes" class="on"><span class="ico">&#9889;</span>Acoes</button>
  <button data-t="texto"><span class="ico">&#9000;</span>Texto</button>
  <button data-t="midia"><span class="ico">&#127925;</span>Midia</button>
  <button data-t="volume"><span class="ico">&#128266;</span>Volume</button>
  <button data-t="atalhos"><span class="ico">&#127919;</span>Atalhos</button>
  <button data-t="tela"><span class="ico">&#128421;</span>Tela</button>
  <button data-t="arquivos"><span class="ico">&#128193;</span>Arquivos</button>
  <button data-t="sistema"><span class="ico">&#9881;</span>Sistema</button>
</nav>

<div class="lock hid" id="lockScreen">
  <div class="lockbox">
    <h1 style="justify-content:center"><span class="dot"></span>PILOTO</h1>
    <p class="hint">Digite o PIN</p>
    <input type="password" id="lockPin" maxlength="32">
    <button class="btn acc btn block" onclick="entrarPin()">Entrar</button>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

function toast(msg){
  const t = $("#toast"); t.textContent = msg; t.classList.add("on");
  clearTimeout(t._h); t._h = setTimeout(()=>t.classList.remove("on"), 1800);
}

function show(nome){
  $$(".page").forEach(p => p.classList.toggle("hid", p.id !== "p-" + nome));
  $$("nav button").forEach(b => b.classList.toggle("on", b.dataset.t === nome));
  if (nome === "arquivos") listarArquivos();
  if (nome === "tela") atualizarTela();
  if (nome === "sistema") carregarSistema();
  if (nome === "volume") carregarVolume();
}
$$("nav button").forEach(b => b.onclick = () => show(b.dataset.t));

async function post(url, dados){
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(dados||{})});
  if (r.status === 401){ mostrarLock(); return {erro:"auth"}; }
  return r.json().catch(() => ({}));
}
async function get(url){
  const r = await fetch(url, {cache: "no-store"});
  if (r.status === 401){ mostrarLock(); return {erro:"auth"}; }
  return r.json().catch(() => ({}));
}

// ACOES
async function carregarAcoes(){
  const j = await get("/api/acoes");
  const g = $("#gridAcoes"); g.innerHTML = "";
  (j.acoes || []).forEach((a, i) => {
    const b = document.createElement("button");
    b.className = "btn"; b.textContent = a.nome;
    b.onclick = () => executarAcao(i);
    b.oncontextmenu = e => { e.preventDefault(); if (confirm(`Remover "${a.nome}"?`)) removerAcao(i); };
    g.appendChild(b);
  });
}
async function executarAcao(i){ const j = await post("/api/acao", {idx:i}); toast(j.saida||j.erro||"ok"); }
async function removerAcao(i){ await post("/api/acao_remover", {idx:i}); carregarAcoes(); }
function abrirNovaAcao(){
  const nome = prompt("Nome do botao:"); if (!nome) return;
  const tipo = (prompt("Tipo: abrir / pasta / url / comando", "abrir")||"").toLowerCase();
  if (!["abrir","pasta","url","comando"].includes(tipo)){ alert("Tipo invalido"); return; }
  const valor = prompt("Valor (ex: notepad.exe, https://..., C:\\Pasta)"); if (!valor) return;
  post("/api/acao_add", {nome, tipo, valor}).then(carregarAcoes);
}

// TEXTO
async function enviarTexto(modo){
  const txt = $("#txtEnv").value; if (!txt){ toast("Digite algo"); return; }
  const j = await post("/api/texto", {texto:txt, modo}); toast(j.saida||j.erro||"ok");
}
async function pegarClipboard(){
  const j = await get("/api/clipboard");
  if (j.erro){ toast(j.erro); return; }
  $("#txtRec").value = j.texto || ""; toast("Lido");
}
function copiarTexto(){ const t = $("#txtRec"); t.select(); document.execCommand("copy"); toast("Copiado"); }

// MIDIA
async function media(a){ await post("/api/midia", {acao:a}); }
async function rodarPlayer(){ const j = await post("/api/abrir_player", {}); toast(j.saida||j.erro||"ok"); }

// VOLUME
let volTimer = null;
async function carregarVolume(){
  const j = await get("/api/volume");
  if (!j.suportado){
    $("#volHint").textContent = "pycaw nao instalado — recompile com as dependencias.";
    $("#volSlider").disabled = true; return;
  }
  if (j.erro){ $("#volHint").textContent = "Erro: " + j.erro; return; }
  $("#volSlider").value = j.volume;
  $("#volNum").textContent = j.volume;
  $("#volIcon").textContent = j.mute ? "\uD83D\uDD07" : (j.volume===0 ? "\uD83D\uDD08" : (j.volume<50 ? "\uD83D\uDD09" : "\uD83D\uDD0A"));
  $("#volHint").textContent = j.mute ? "Mudo" : "Volume normal";
}
function onVolSlide(v){
  $("#volNum").textContent = v;
  $("#volIcon").textContent = v==0 ? "\uD83D\uDD08" : (v<50 ? "\uD83D\uDD09" : "\uD83D\uDD0A");
  clearTimeout(volTimer); volTimer = setTimeout(()=>onVolCommit(v), 100);
}
async function onVolCommit(v){ const r = await post("/api/volume", {volume: parseInt(v)}); if (r.volume!==undefined) $("#volNum").textContent = r.volume; }
async function setVol(v){ await post("/api/volume", {volume:v}); carregarVolume(); }
async function toggleMute(){ await post("/api/volume", {toggle_mute:true}); carregarVolume(); }

// ATALHOS
async function atalho(nome){ await post("/api/atalho", {nome}); toast(nome); }
async function mouse(acao){ await post("/api/mouse", {acao}); }

// TELA
let telaTimer = null;
async function atualizarTela(){
  $("#tela").src = "/api/screen?t=" + Date.now();
  $("#telaHora").textContent = "Atualizado " + new Date().toLocaleTimeString();
}
function toggleAuto(){
  if (telaTimer){ clearInterval(telaTimer); telaTimer = null; $("#btnAuto").textContent = "Ao vivo"; }
  else { atualizarTela(); telaTimer = setInterval(atualizarTela, 2500); $("#btnAuto").textContent = "Parar"; }
}

// ARQUIVOS
function formatarTam(b){
  if (b < 1024) return b + " B";
  if (b < 1024*1024) return (b/1024).toFixed(1) + " KB";
  if (b < 1024*1024*1024) return (b/1024/1024).toFixed(1) + " MB";
  return (b/1024/1024/1024).toFixed(2) + " GB";
}
async function listarArquivos(){
  const j = await get("/api/arquivos");
  const box = $("#txtArquivos"); box.innerHTML = "";
  $("#pastaAtual").textContent = "Pasta: " + (j.pasta || "?");
  (j.itens||[]).forEach(a => {
    const d = document.createElement("div"); d.className = "arq";
    d.innerHTML = `<span class="nome">${a.nome}</span><span class="tam">${formatarTam(a.tam)}</span>
      <button onclick="baixar('${encodeURIComponent(a.nome)}')">Baixar</button>
      <button class="del" onclick="apagar('${encodeURIComponent(a.nome)}')">x</button>`;
    box.appendChild(d);
  });
  if (!(j.itens||[]).length) box.innerHTML = '<div class="hint">(vazio)</div>';
}
function baixar(nomeEnc){ window.open("/api/download?nome=" + nomeEnc, "_blank"); }
async function apagar(nomeEnc){
  if (!confirm("Apagar esse arquivo?")) return;
  await post("/api/apagar", {nome: decodeURIComponent(nomeEnc)}); listarArquivos();
}
async function fazerUpload(){
  const inp = $("#upFile");
  if (!inp.files.length){ toast("Escolha arquivo(s)"); return; }
  const fd = new FormData();
  for (const f of inp.files) fd.append("arquivos", f, f.name);
  toast("Enviando...");
  const r = await fetch("/api/upload", {method:"POST", body: fd});
  if (r.status === 401){ mostrarLock(); return; }
  const j = await r.json().catch(()=>({}));
  toast(j.saida||j.erro||"enviado"); inp.value = ""; listarArquivos();
}

// SISTEMA
async function sistema(acao){
  if (["desligar","reiniciar","dormir"].includes(acao)){ if (!confirm(`Confirma ${acao}?`)) return; }
  const j = await post("/api/sistema", {acao}); toast(j.saida||j.erro||"ok");
}
async function carregarSistema(){
  const j = await get("/api/state");
  $("#pastaIn").value = j.pasta_arquivos || "";
  $("#pinHint").textContent = j.pin_set ? "PIN ativo" : "Sem PIN (qualquer um na rede controla)";
}
async function salvarPasta(){ await post("/api/pasta", {pasta: $("#pastaIn").value.trim()}); toast("Salvo"); }
async function definirPin(){
  const pin = $("#pinIn").value.trim(); if (pin.length < 4){ alert("Minimo 4"); return; }
  await post("/api/pin", {pin}); $("#pinIn").value = ""; toast("PIN definido"); carregarSistema();
}
async function removerPin(){
  if (!confirm("Remover PIN?")) return;
  await post("/api/pin", {pin:""}); toast("PIN removido"); carregarSistema();
}

// LOCK
function mostrarLock(){ $("#lockScreen").classList.remove("hid"); }
async function entrarPin(){
  const pin = $("#lockPin").value;
  const r = await fetch("/api/login", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({pin})});
  if (r.ok){ $("#lockScreen").classList.add("hid"); $("#lockPin").value = ""; iniciar(); }
  else toast("PIN incorreto");
}

// INIT
async function iniciar(){
  const j = await get("/api/state");
  $("#ipTop").textContent = "http://" + j.ip + ":" + j.porta;
  if (j.pin_set && !j.autenticado){ mostrarLock(); return; }
  $("#lockScreen").classList.add("hid");
  carregarAcoes(); carregarSistema(); carregarVolume();
}
iniciar();
</script>
</body>
</html>
"""


# ============================================================
#                     ROTAS
# ============================================================

@app.route("/")
def home():
    return PAGINA


@app.route("/api/state")
def api_state():
    return jsonify(ip=ip_local(), porta=5000, pin_set=bool(CFG.get("pin")),
                   autenticado=autenticado(), pasta_arquivos=pasta_arquivos())


@app.route("/api/login", methods=["POST"])
def api_login():
    pin = (request.get_json(force=True).get("pin") or "").strip()
    if not CFG.get("pin") or pin == CFG["pin"]:
        session["ok"] = True
        return jsonify(ok=True)
    return jsonify(erro="pin incorreto"), 401


@app.route("/api/pin", methods=["POST"])
def api_pin():
    b = exigir_auth()
    if b: return b
    pin = (request.get_json(force=True).get("pin") or "").strip()
    CFG["pin"] = pin or None
    salvar_cfg(CFG)
    return jsonify(ok=True)


@app.route("/api/pasta", methods=["POST"])
def api_pasta():
    b = exigir_auth()
    if b: return b
    p = (request.get_json(force=True).get("pasta") or "").strip()
    CFG["pasta_arquivos"] = p
    salvar_cfg(CFG)
    return jsonify(ok=True, pasta=pasta_arquivos())


# ---------- ACOES ----------

@app.route("/api/acoes")
def api_acoes():
    b = exigir_auth()
    if b: return b
    return jsonify(acoes=CFG.get("acoes", []))


@app.route("/api/acao", methods=["POST"])
def api_acao():
    b = exigir_auth()
    if b: return b
    idx = int(request.get_json(force=True).get("idx", -1))
    acoes = CFG.get("acoes", [])
    if idx < 0 or idx >= len(acoes): return jsonify(erro="acao invalida")
    try:
        executar_acao(acoes[idx])
        return jsonify(saida=f"OK: {acoes[idx]['nome']}")
    except Exception as e:
        return jsonify(erro=str(e))


@app.route("/api/acao_add", methods=["POST"])
def api_acao_add():
    b = exigir_auth()
    if b: return b
    d = request.get_json(force=True)
    CFG.setdefault("acoes", []).append({
        "nome": (d.get("nome") or "?")[:40],
        "tipo": d.get("tipo") or "abrir",
        "valor": d.get("valor") or "",
    })
    salvar_cfg(CFG)
    return jsonify(ok=True)


@app.route("/api/acao_remover", methods=["POST"])
def api_acao_remover():
    b = exigir_auth()
    if b: return b
    idx = int(request.get_json(force=True).get("idx", -1))
    acoes = CFG.get("acoes", [])
    if 0 <= idx < len(acoes):
        acoes.pop(idx); salvar_cfg(CFG)
    return jsonify(ok=True)


def executar_acao(a):
    tipo = a.get("tipo")
    valor = os.path.expandvars(a.get("valor") or "")
    if tipo == "abrir":
        rodar_oculto(["cmd", "/c", "start", "", valor], shell=False)
    elif tipo == "pasta":
        if os.path.isdir(valor): os.startfile(valor)
        else: raise Exception("Pasta nao existe: " + valor)
    elif tipo == "url":
        webbrowser.open_new_tab(valor)
    elif tipo == "comando":
        rodar_oculto(["cmd", "/c", valor], shell=False)
    else:
        raise Exception("Tipo desconhecido: " + tipo)


# ---------- TEXTO ----------

def copiar_pc(texto):
    texto = texto.replace("'", "''")
    script = f"Set-Clipboard -Value '{texto}'"
    cod = base64.b64encode(script.encode("utf-16-le")).decode()
    executar(["powershell", "-NoProfile", "-EncodedCommand", cod])


def ler_pc():
    script = "Get-Clipboard -Raw"
    cod = base64.b64encode(script.encode("utf-16-le")).decode()
    r = executar(["powershell", "-NoProfile", "-EncodedCommand", cod],
                 capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (r.stdout or "").rstrip("\n")


ESPECIAIS_SENDKEYS = {
    "+": "{+}", "^": "{^}", "%": "{%}", "~": "{~}",
    "(": "{(}", ")": "{)}", "{": "{{}", "}": "{}}",
    "[": "{[}", "]": "{]}", "\n": "{ENTER}", "\r": "",
}


def digitar_pc(texto):
    linhas = ["Add-Type -AssemblyName System.Windows.Forms", "Start-Sleep -Milliseconds 200"]
    for ch in texto:
        s = ESPECIAIS_SENDKEYS.get(ch, ch).replace("'", "''")
        if s:
            linhas.append(f"[System.Windows.Forms.SendKeys]::SendWait('{s}')")
            linhas.append("Start-Sleep -Milliseconds 12")
    script = "\n".join(linhas)
    cod = base64.b64encode(script.encode("utf-16-le")).decode()
    rodar_oculto(["powershell", "-NoProfile", "-EncodedCommand", cod])


@app.route("/api/texto", methods=["POST"])
def api_texto():
    b = exigir_auth()
    if b: return b
    d = request.get_json(force=True)
    texto = (d.get("texto") or "")[:8000]
    modo = d.get("modo", "clipboard")
    if modo == "digitar":
        digitar_pc(texto)
        return jsonify(saida="Digitando no PC...")
    copiar_pc(texto)
    return jsonify(saida="Copiado pra area de transferencia do PC.")


@app.route("/api/clipboard")
def api_clipboard():
    b = exigir_auth()
    if b: return b
    try:
        return jsonify(texto=ler_pc())
    except Exception as e:
        return jsonify(erro=str(e))


# ---------- MIDIA ----------

VK = {"play":0xB3,"next":0xB0,"prev":0xB1,"vol_up":0xAF,"vol_down":0xAE,"mute":0xAD}


@app.route("/api/midia", methods=["POST"])
def api_midia():
    b = exigir_auth()
    if b: return b
    acao = request.get_json(force=True).get("acao", "")
    if acao not in VK: return jsonify(erro="acao desconhecida")
    user32 = ctypes.windll.user32
    user32.keybd_event(VK[acao], 0, 0, 0)
    user32.keybd_event(VK[acao], 0, 2, 0)
    return jsonify(ok=True)


# ---------- VOLUME ----------

def _audio():
    if not PYCAW_OK: return None
    try:
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return interface.QueryInterface(IAudioEndpointVolume)
    except Exception:
        return None


@app.route("/api/volume")
def api_volume_get():
    b = exigir_auth()
    if b: return b
    vol = _audio()
    if not vol: return jsonify(ok=False, suportado=False)
    try:
        return jsonify(ok=True, suportado=True,
                       volume=int(round(vol.GetMasterVolumeLevelScalar()*100)),
                       mute=bool(vol.GetMute()))
    except Exception as e:
        return jsonify(ok=False, erro=str(e))


@app.route("/api/volume", methods=["POST"])
def api_volume_set():
    b = exigir_auth()
    if b: return b
    d = request.get_json(force=True)
    vol = _audio()
    if not vol: return jsonify(erro="pycaw nao disponivel"), 400
    try:
        if "volume" in d:
            pct = max(0, min(100, int(d["volume"])))
            vol.SetMasterVolumeLevelScalar(pct/100.0, None)
        if "mute" in d: vol.SetMute(bool(d["mute"]), None)
        if "toggle_mute" in d: vol.SetMute(not bool(vol.GetMute()), None)
        return jsonify(ok=True,
                       volume=int(round(vol.GetMasterVolumeLevelScalar()*100)),
                       mute=bool(vol.GetMute()))
    except Exception as e:
        return jsonify(erro=str(e))


# ---------- ATALHOS ----------

VK_ATALHOS = {
    "enter":0x0D,"esc":0x1B,"tab":0x09,"backspace":0x08,"delete":0x2E,"space":0x20,
    "up":0x26,"down":0x28,"left":0x25,"right":0x27,"home":0x24,"end":0x23,
    "pageup":0x21,"pagedown":0x22,"f5":0x74,"f11":0x7A,"printscreen":0x2C,"win":0x5B,
}
VK_MODS = {
    "alt_tab":(0x12,0x09),"alt_f4":(0x12,0x73),
    "ctrl_c":(0x11,0x43),"ctrl_v":(0x11,0x56),"ctrl_x":(0x11,0x58),
    "ctrl_z":(0x11,0x5A),"ctrl_y":(0x11,0x59),"ctrl_a":(0x11,0x41),
    "ctrl_s":(0x11,0x53),"ctrl_f":(0x11,0x46),
    "win_d":(0x5B,0x44),"win_e":(0x5B,0x45),"win_l":(0x5B,0x4C),
    "win_r":(0x5B,0x52),"win_s":(0x5B,0x53),"win_tab":(0x5B,0x09),
}
KEYEVENTF_KEYUP = 0x0002


def _tecla(vk, up=False):
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP if up else 0, 0)


def _combo(mod, t):
    _tecla(mod); time.sleep(0.02)
    _tecla(t); time.sleep(0.03)
    _tecla(t, True); time.sleep(0.02)
    _tecla(mod, True)


def enviar_atalho(nome):
    user32 = ctypes.windll.user32
    if nome in VK_ATALHOS:
        vk = VK_ATALHOS[nome]
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        return True
    if nome in VK_MODS:
        _combo(*VK_MODS[nome]); return True
    return False


@app.route("/api/atalho", methods=["POST"])
def api_atalho():
    b = exigir_auth()
    if b: return b
    nome = (request.get_json(force=True).get("nome") or "").lower()
    try:
        ok = enviar_atalho(nome)
        return jsonify(ok=ok, saida="enviado" if ok else "desconhecido")
    except Exception as e:
        return jsonify(erro=str(e))


# ---------- MOUSE ----------

MOUSEEVENTF = {"left_down":0x0002,"left_up":0x0004,"right_down":0x0008,"right_up":0x0010,
               "middle_down":0x0020,"middle_up":0x0040,"wheel":0x0800}


def mouse_event(flag, dx=0, dy=0, dados=0):
    ctypes.windll.user32.mouse_event(flag, dx, dy, dados, 0)


@app.route("/api/mouse", methods=["POST"])
def api_mouse():
    b = exigir_auth()
    if b: return b
    acao = request.get_json(force=True).get("acao", "")
    try:
        if acao == "scroll_up": mouse_event(MOUSEEVENTF["wheel"], 0, 0, 120)
        elif acao == "scroll_down": mouse_event(MOUSEEVENTF["wheel"], 0, 0, -120)
        elif acao == "left_click":
            mouse_event(MOUSEEVENTF["left_down"]); mouse_event(MOUSEEVENTF["left_up"])
        elif acao == "right_click":
            mouse_event(MOUSEEVENTF["right_down"]); mouse_event(MOUSEEVENTF["right_up"])
        elif acao == "middle_click":
            mouse_event(MOUSEEVENTF["middle_down"]); mouse_event(MOUSEEVENTF["middle_up"])
        elif acao == "double_click":
            for _ in range(2):
                mouse_event(MOUSEEVENTF["left_down"]); mouse_event(MOUSEEVENTF["left_up"])
                time.sleep(0.05)
        else: return jsonify(erro="acao desconhecida")
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(erro=str(e))


# ---------- PLAYER ----------

@app.route("/api/abrir_player", methods=["POST"])
def api_abrir_player():
    b = exigir_auth()
    if b: return b
    try:
        os.startfile("mswindowsmusic:")
    except Exception:
        try:
            executar(["cmd", "/c", "start", "", "wmplayer"], shell=False)
        except Exception:
            return jsonify(erro="nao consegui abrir o player")
    return jsonify(saida="Player aberto.")


# ---------- TELA ----------

CAPTURE_PS = """
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save('__OUT__', [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"""

CAPTURE_LOCK = threading.Lock()


@app.route("/api/screen")
def api_screen():
    b = exigir_auth()
    if b: return b
    with CAPTURE_LOCK:
        out = os.path.join(tempfile.gettempdir(), "piloto_screen.png")
        out_ps = out.replace("\\", "/")
        script = CAPTURE_PS.replace("__OUT__", out_ps)
        cod = base64.b64encode(script.encode("utf-16-le")).decode()
        executar(["powershell", "-NoProfile", "-EncodedCommand", cod],
                 capture_output=True, timeout=20)
        try:
            with open(out, "rb") as f:
                png = f.read()
        except Exception:
            return jsonify(erro="sem screenshot"), 500
    return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})


# ---------- ARQUIVOS ----------

def _nome_seguro(nome):
    return os.path.basename(nome).replace("..", "_")[:200]


@app.route("/api/arquivos")
def api_arquivos():
    b = exigir_auth()
    if b: return b
    p = pasta_arquivos()
    itens = []
    try:
        for n in sorted(os.listdir(p)):
            full = os.path.join(p, n)
            if os.path.isfile(full):
                itens.append({"nome": n, "tam": os.path.getsize(full)})
    except Exception:
        pass
    return jsonify(pasta=p, itens=itens[:200])


@app.route("/api/download")
def api_download():
    b = exigir_auth()
    if b: return b
    nome = _nome_seguro(request.args.get("nome", ""))
    p = os.path.join(pasta_arquivos(), nome)
    if not os.path.isfile(p): return jsonify(erro="arquivo nao encontrado"), 404
    return send_file(p, as_attachment=True, download_name=nome)


@app.route("/api/upload", methods=["POST"])
def api_upload():
    b = exigir_auth()
    if b: return b
    arquivos = request.files.getlist("arquivos")
    if not arquivos: return jsonify(erro="nenhum arquivo")
    p = pasta_arquivos()
    salvos = 0
    for f in arquivos:
        if not f.filename: continue
        nome = _nome_seguro(f.filename)
        f.save(os.path.join(p, nome))
        salvos += 1
    return jsonify(saida=f"{salvos} arquivo(s) salvos em {p}")


@app.route("/api/apagar", methods=["POST"])
def api_apagar():
    b = exigir_auth()
    if b: return b
    nome = _nome_seguro(request.get_json(force=True).get("nome", ""))
    p = os.path.join(pasta_arquivos(), nome)
    try:
        if os.path.isfile(p): os.remove(p)
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(erro=str(e))


# ---------- SISTEMA ----------

@app.route("/api/sistema", methods=["POST"])
def api_sistema():
    b = exigir_auth()
    if b: return b
    acao = request.get_json(force=True).get("acao", "")
    if acao == "bloquear":
        executar(["rundll32.exe", "user32.dll,LockWorkStation"])
        return jsonify(saida="PC bloqueado.")
    if acao == "dormir":
        executar(["powercfg", "-h", "off"])
        executar(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return jsonify(saida="Dormindo...")
    if acao == "desligar":
        executar(["shutdown", "/s", "/t", "3"]); return jsonify(saida="Desligando em 3s.")
    if acao == "reiniciar":
        executar(["shutdown", "/r", "/t", "3"]); return jsonify(saida="Reiniciando em 3s.")
    if acao == "cancelar":
        executar(["shutdown", "/a"]); return jsonify(saida="Cancelado.")
    return jsonify(erro="acao desconhecida")


# ---------- main ----------

def abrir_navegador():
    time.sleep(1)
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    if os.name != "nt":
        log_seguro("Feito para Windows.")
        sys.exit(1)
    esconder_console()
    log_seguro("PILOTO no PC:      http://127.0.0.1:5000")
    log_seguro("PILOTO no celular: http://%s:5000  (mesma Wi-Fi)" % ip_local())
    if ABRIR_NAVEGADOR_NO_PC:
        threading.Thread(target=abrir_navegador, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False)