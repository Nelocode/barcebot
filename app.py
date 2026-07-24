"""
Panel de Administración — Bot AutoReply Comercial
Flask webapp para gestionar mensajes y audios del bot.
"""
import os
import json
import shutil
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, send_from_directory

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audios"
MESSAGES_FILE = DATA_DIR / "messages.json"

app = Flask(__name__)
APP_SECRET = os.environ.get("FLASK_SECRET", "bot-autoreply-secret-change-me")
app.secret_key = APP_SECRET

# ── Telethon auth state (para flujo interactivo desde el panel) ──────
# Guarda el estado entre send_code_request y sign_in
import asyncio as _asyncio
_pending_auth: dict = {}  # {phone_code_hash, client, phone}
_telethon_client = None

# ── HTML Template (todo en uno para portabilidad) ───────────────────
TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bot AutoReply — Admin</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css">
<style>
body { background: #0f0f1a; color: #e8e8f0; font-family: system-ui, -apple-system, sans-serif; }
.card { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px; margin-bottom: 1.5rem; }
.card-header { background: #16213e; border-bottom: 1px solid #2a2a4a; font-weight: 600; color: #c8d8f0; border-radius: 12px 12px 0 0 !important; }
.form-control, .form-select { background: #12122a; border: 1px solid #3a3a5a; color: #e8e8f0; }
.form-control:focus { background: #1a1a32; border-color: #5a9af0; color: #ffffff; box-shadow: 0 0 0 0.2rem rgba(90,154,240,0.2); }
.form-control::placeholder { color: #6a6a8a; }
.btn-primary { background: #4a90d9; border: none; color: #fff; font-weight: 500; }
.btn-primary:hover { background: #357abd; }
.btn-danger { background: #e74c3c; border: none; color: #fff; }
.btn-success { background: #27ae60; border: none; color: #fff; }
.btn-outline-light { border-color: #3a3a5a; color: #c8c8e0; }
.btn-outline-light:hover { background: #2a2a4a; border-color: #5a5a7a; color: #ffffff; }
.language-tabs { display: flex; gap: 8px; margin-bottom: 1rem; }
.language-tabs .btn { flex: 1; }
.badge-es { background: #e67e22; color: #fff; }
.badge-en { background: #3498db; color: #fff; }
.badge-fr { background: #9b59b6; color: #fff; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 6px; }
.status-online { background: #27ae60; }
.status-offline { background: #e74c3c; }
.step-label { font-size: 0.85rem; color: #8a8aaa; text-transform: uppercase; letter-spacing: 1px; }
textarea { min-height: 60px; resize: vertical; background: #12122a; border: 1px solid #3a3a5a; color: #e8e8f0; }
hr { border-color: #2a2a4a; }
.text-muted { color: #8a8aaa !important; }
#toast-container { position: fixed; top: 20px; right: 20px; z-index: 9999; }
.toast-msg { background: #1a1a2e; color: #e8e8f0; border: 1px solid #2a2a4a; padding: 12px 20px; border-radius: 8px; margin-bottom: 8px; animation: fadeIn 0.3s; }
.toast-msg.success { border-left: 4px solid #27ae60; }
.toast-msg.error { border-left: 4px solid #e74c3c; }
@keyframes fadeIn { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: translateX(0); } }
summary { color: #5a9af0; cursor: pointer; }
code { background: #12122a; color: #e8a0d0; padding: 2px 6px; border-radius: 4px; }
.badge.bg-secondary { background: #2a2a4a !important; color: #b0b0d0 !important; }
label { color: #c8c8e0 !important; font-weight: 500; }
.label-text { color: #c8c8e0; }
.card-body .small, .card-body small { color: #9a9ab0 !important; }
</style>
</head>
<body>
<div class="container py-4">
  <!-- Header -->
  <div class="d-flex justify-content-between align-items-center mb-4">
    <div>
      <h1 class="h3 mb-0">🤖 Bot AutoReply</h1>
      <small class="text-muted">Panel de administración — los cambios se guardan al instante</small>
    </div>
    <div class="d-flex align-items-center gap-3">
      <div class="d-flex flex-column align-items-end" style="gap: 4px;">
        <span id="bot-status" class="badge bg-secondary" style="font-size:0.75rem;">📱 TG User: Verificando...</span>
        <span id="bf-status" class="badge bg-secondary" style="font-size:0.75rem;">🤖 BotFather: Verificando...</span>
        <span id="wa-status" class="badge bg-secondary" style="font-size:0.75rem;">💬 WA: Verificando...</span>
      </div>
      <button class="btn btn-sm btn-outline-light" onclick="showSetup()">⚙️ Configurar</button>
      <button class="btn btn-sm btn-outline-light" onclick="restartBot()">🔄 Reiniciar TG</button>
      <button class="btn btn-sm btn-outline-light" onclick="restartWaBot()">🔄 Reiniciar WA</button>
    </div>
  </div>

  <!-- Setup Modal -->
  <div id="setup-modal" class="card" style="display:none;">
    <div class="card-header d-flex justify-content-between align-items-center">
      <span>⚙️ Configuración — Vinculación de canales</span>
      <button class="btn btn-sm btn-outline-light" onclick="document.getElementById('setup-modal').style.display='none'">✕</button>
    </div>
    <div class="card-body">

      <!-- ── Telegram ── -->
      <h6 class="mb-2">📱 Telegram (User Bot)</h6>
      <details class="mb-2">
        <summary class="text-muted small" style="cursor:pointer;">📖 ¿Cómo obtener las credenciales?</summary>
        <ol class="small mt-2" style="padding-left:1.5rem;">
          <li>Ve a <a href="https://my.telegram.org/apps" target="_blank" style="color:#6ea8fe;">my.telegram.org/apps</a></li>
          <li>Inicia sesión con el número de teléfono de la cuenta</li>
          <li>Crea una aplicación (nombre cualquiera, plataforma "Desktop")</li>
          <li>Copia el <strong>api_id</strong> y <strong>api_hash</strong> de abajo</li>
        </ol>
      </details>
      <div class="row mb-2">
        <div class="col-3">
          <input id="tg-api-id" type="number" class="form-control form-control-sm" placeholder="api_id" style="font-family:monospace;font-size:0.8rem;">
        </div>
        <div class="col-5">
          <input id="tg-api-hash" type="text" class="form-control form-control-sm" placeholder="api_hash" style="font-family:monospace;font-size:0.8rem;">
        </div>
        <div class="col-4">
          <input id="tg-phone" type="text" class="form-control form-control-sm" placeholder="+57 300 123 4567" style="font-family:monospace;font-size:0.8rem;">
        </div>
      </div>
      <div class="d-flex align-items-center gap-2 mb-2">
        <button class="btn btn-sm btn-primary" onclick="linkTelegram()">🔗 Vincular</button>
      </div>
      <div id="tg-link-status" class="small text-muted mb-3"></div>

      <!-- ── Código de verificación TG (oculto hasta que se necesite) ── -->
      <div id="tg-code-section" style="display:none;" class="mb-3 p-2" >
        <h6 class="mb-1">📨 Código de verificación</h6>
        <p class="small text-muted mb-2">Revisa Telegram en el número <strong id="tg-code-phone"></strong>. Te llegó un mensaje con un código de 5 dígitos.</p>
        <div class="d-flex gap-2">
          <input id="tg-code-input" type="text" class="form-control form-control-sm" placeholder="12345" maxlength="10" style="font-family:monospace;font-size:1.1rem;letter-spacing:4px;text-align:center;flex:1;">
          <button class="btn btn-sm btn-success" onclick="verifyTgCode()">✅ Verificar</button>
          <button class="btn btn-sm btn-outline-light" onclick="cancelTgAuth()">✕ Cancelar</button>
        </div>
        <div id="tg-code-status" class="small text-muted mt-2"></div>

        <!-- 2FA password (oculto hasta que se necesite) -->
        <div id="tg-2fa-section" style="display:none;" class="mt-3">
          <p class="small text-muted mb-2">Esta cuenta tiene verificación en dos pasos. Ingresa tu contraseña.</p>
          <div class="d-flex gap-2">
            <input id="tg-password-input" type="password" class="form-control form-control-sm" placeholder="Contraseña de 2FA" style="flex:1;">
            <button class="btn btn-sm btn-success" onclick="verifyTgPassword()">✅ Verificar</button>
          </div>
          <div id="tg-password-status" class="small text-muted mt-1"></div>
        </div>
      </div>

      <!-- ── BotFather (Bot API tradicional) ── -->
      <hr class="my-3">
      <h6 class="mb-2">🤖 BotFather (modo prueba/revisión)</h6>
      <details class="mb-2">
        <summary class="text-muted small" style="cursor:pointer;">📖 ¿Cómo crear un bot en BotFather?</summary>
        <ol class="small mt-2" style="padding-left:1.5rem;">
          <li>Abre Telegram y busca <strong>@BotFather</strong></li>
          <li>Envía <code>/newbot</code> y sigue las instrucciones</li>
          <li>BotFather te dará un <strong>token</strong> (ej: <code>123456789:ABCdefGHIjkl...</code>)</li>
          <li>Pega ese token abajo</li>
        </ol>
      </details>
      <div class="d-flex align-items-center gap-2 mb-2">
        <input id="bf-token-input" type="text" class="form-control form-control-sm" placeholder="Token de BotFather" style="flex:1;font-family:monospace;font-size:0.8rem;">
        <button class="btn btn-sm btn-outline-light" onclick="linkBotFather()">🔗 Vincular</button>
      </div>
      <div id="bf-link-status" class="small text-muted mb-2"></div>

      <!-- ── WhatsApp ── -->
      <h6 class="mb-2">💬 WhatsApp</h6>
      <details class="mb-2">
        <summary class="text-muted small" style="cursor:pointer;">📖 ¿Cómo vincular WhatsApp?</summary>
        <ol class="small mt-2" style="padding-left:1.5rem;">
          <li>Haz click en <strong>"📲 Vincular WhatsApp"</strong></li>
          <li>Espera unos segundos a que aparezca el código QR</li>
          <li>Abre WhatsApp en tu teléfono</li>
          <li>Ve a <strong>3 puntos > Dispositivos vinculados > Vincular dispositivo</strong></li>
          <li>Escanea el QR que aparece en pantalla</li>
          <li>Haz click en <strong>"✅ Ya escaneé"</strong> para confirmar</li>
        </ol>
      </details>
      <div class="d-flex align-items-center gap-2">
        <button class="btn btn-sm btn-primary" onclick="launchWaAndShowQr()">📲 Vincular WhatsApp</button>
        <button class="btn btn-sm btn-outline-light" onclick="loadWaQr()">🔄 Mostrar QR</button>
        <button class="btn btn-sm btn-outline-light" onclick="refreshWaStatus()">✅ Ya escaneé</button>
      </div>
      <div id="wa-link-status" class="small text-muted mt-2"></div>

      <!-- ── Servidor (futuro deploy) ── -->
      <hr class="my-3">
      <details>
        <summary class="text-muted small" style="cursor:pointer;">🌐 ¿Subir a un servidor?</summary>
        <div class="small mt-2 text-muted">
          <p>Este panel funciona en local. Para producción en un VPS:</p>
          <ol style="padding-left:1.5rem;">
            <li>Copia la carpeta <code>bot-autoreply</code> al servidor</li>
            <li>Ejecuta el script <code>deploy.sh</code> incluido</li>
            <li>Los 3 servicios (TG, WA, Panel) arrancan solos con systemd</li>
            <li>Usa Nginx + Certbot para HTTPS y dominio personalizado</li>
          </ol>
        </div>
      </details>

    </div>
  </div>

  <!-- WhatsApp QR (hidden by default) -->
  <div id="wa-qr-card" class="card" style="display:none;">
    <div class="card-header d-flex justify-content-between align-items-center">
      <span>💬 Vincular WhatsApp</span>
      <button class="btn btn-sm btn-outline-light" onclick="document.getElementById('wa-qr-card').style.display='none'">✕</button>
    </div>
    <div class="card-body text-center py-4">
      <p class="mb-3">Escanea este QR con WhatsApp para vincular el bot:</p>
      <img id="wa-qr-img" src="" alt="QR WhatsApp" style="width:300px;height:300px;border-radius:12px;background:#fff;padding:8px;" class="mb-3">
      <p class="text-muted small">WhatsApp > 3 puntos > Dispositivos vinculados</p>
      <div class="mt-2">
        <button class="btn btn-sm btn-outline-light" onclick="loadWaQr()">🔄 Actualizar QR</button>
        <button class="btn btn-sm btn-outline-light" onclick="refreshWaStatus()">✅ Ya escaneé</button>
      </div>
    </div>
  </div>

  <!-- Language Tabs -->
  <div class="language-tabs" id="lang-tabs">
    <button class="btn btn-outline-light active" data-lang="es" onclick="switchLang('es')">
      <span class="badge badge-es">ES</span> Español
    </button>
    <button class="btn btn-outline-light" data-lang="en" onclick="switchLang('en')">
      <span class="badge badge-en">EN</span> English
    </button>
    <button class="btn btn-outline-light" data-lang="fr" onclick="switchLang('fr')">
      <span class="badge badge-fr">FR</span> Français
    </button>
  </div>

  <!-- Steps Container -->
  <div id="steps-container"></div>

  <!-- Info Footer -->
  <div class="mt-4 text-center text-muted" style="font-size:0.85rem;">
    <span>📁 <code>messages.json</code></span>
    <span class="mx-2">·</span>
    <span>🎵 Audios en <code>audios/</code></span>
    <span class="mx-2">·</span>
    <span>🔄 Cambios toman efecto al reiniciar el bot</span>
  </div>
</div>

<!-- Toast Container -->
<div id="toast-container"></div>

<script>
let currentLang = "es";
const LANG_NAMES = {"es":"Español","en":"English","fr":"Français"};
const LANG_CODES = {"es":"ES","en":"EN","fr":"FR"};

function toast(msg, type="success") {
  const c = document.getElementById("toast-container");
  const d = document.createElement("div");
  d.className = "toast-msg " + type;
  d.textContent = msg;
  c.appendChild(d);
  setTimeout(() => d.remove(), 3000);
}

async function loadData() {
  try {
    const r = await fetch("/api/data");
    const data = await r.json();
    renderSteps(data);
    updateBotStatus(data.bot_running);
    updateBfStatus(data.bf_running);
    updateWaStatus(data.wa_running);
  } catch(e) {
    toast("Error cargando datos: " + e.message, "error");
  }
}

function renderSteps(data) {
  const lang = currentLang;
  const langData = data.messages[lang];
  if (!langData) return;

  let html = `<div class="card">
    <div class="card-header d-flex justify-content-between align-items-center">
      <span><span class="badge badge-${lang}">${LANG_CODES[lang]}</span> ${LANG_NAMES[lang]} — 3 pasos</span>
      <div>
        <button class="btn btn-sm btn-outline-secondary" onclick="addStep('${lang}')">+ Añadir Paso</button>
        <button class="btn btn-sm btn-outline-primary" onclick="previewLang('${lang}')">👁 Vista previa</button>
      </div>
    </div>
    <div class="card-body">`;

  langData.steps.forEach((step, i) => {
    const audioPath = `/api/audio/${step.audio}`;
    html += `
    <div class="mb-4 p-3" style="background:#141428; border-radius:8px;" data-step="${i}">
      <div class="d-flex justify-content-between align-items-center mb-2">
        <span class="step-label">Paso ${i+1}</span>
        <button class="btn btn-sm btn-danger" onclick="removeStep('${lang}', ${i})">✕</button>
      </div>
      <div class="row g-3">
        <div class="col-md-8">
          <label class="form-label small">Texto del mensaje</label>
          <textarea class="form-control" onchange="saveStepText('${lang}', ${i}, this.value)">${escapeHtml(step.text)}</textarea>
        </div>
        <div class="col-md-4">
          <label class="form-label small">Audio</label>
          <div class="audio-preview mb-2">
            <audio controls src="${audioPath}"></audio>
            <span class="small text-muted">${step.audio}</span>
          </div>
          <div class="input-group input-group-sm">
            <input type="file" class="form-control form-control-sm" accept="audio/mpeg,audio/mp3" 
                   onchange="uploadAudio('${lang}', ${i}, this.files[0])">
          </div>
        </div>
      </div>
    </div>`;
  });

  html += `</div></div>`;

  // ── Sección de Llamada ──
  const callData = langData.call || { text: '📞 Llamada recibida', audio: '' };
  const callAudioPath = callData.audio ? `/api/audio/${callData.audio}` : '';
  html += `
  <div class="card mt-3">
    <div class="card-header">
      <span>📞 Llamada — mensaje para cuando alguien llama</span>
    </div>
    <div class="card-body">
      <div class="row g-3">
        <div class="col-md-8">
          <label class="form-label small">Texto de llamada</label>
          <textarea class="form-control" onchange="saveCallText('${lang}', this.value)">${escapeHtml(callData.text)}</textarea>
        </div>
        <div class="col-md-4">
          <label class="form-label small">Audio de llamada</label>
          ${callAudioPath ? `
          <div class="audio-preview mb-2">
            <audio controls src="${callAudioPath}"></audio>
            <span class="small text-muted">${callData.audio}</span>
          </div>` : '<div class="mb-2 small text-muted">🎵 Sin audio aún</div>'}
          <div class="input-group input-group-sm">
            <input type="file" class="form-control form-control-sm" accept="audio/mpeg,audio/mp3"
                   onchange="uploadCallAudio('${lang}', this.files[0])">
          </div>
        </div>
      </div>
    </div>
  </div>`;

  document.getElementById("steps-container").innerHTML = html;
}

function escapeHtml(s) {
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function switchLang(lang) {
  currentLang = lang;
  document.querySelectorAll("#lang-tabs .btn").forEach(b => {
    b.classList.toggle("active", b.dataset.lang === lang);
    b.classList.toggle("btn-outline-light", b.dataset.lang !== lang);
    b.classList.toggle("btn-light", b.dataset.lang === lang);
  });
  loadData();
}

async function saveStepText(lang, step, text) {
  try {
    const r = await fetch("/api/messages", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({lang, step, text, action: "edit_text"})
    });
    const resp = await r.json();
    if (resp.ok) toast("✅ Paso "+(step+1)+" guardado");
    else toast("❌ Error: " + resp.error, "error");
  } catch(e) {
    toast("❌ Error: " + e.message, "error");
  }
}

async function uploadAudio(lang, step, file) {
  if (!file) return;
  await uploadFileChunked(file, lang, {step, type: "step"});
}

async function uploadCallAudio(lang, file) {
  if (!file) return;
  await uploadFileChunked(file, lang, {type: "call"});
}

async function uploadFileChunked(file, lang, opts = {}) {
  const CHUNK_SIZE = 500 * 1024; // 500KB per chunk
  const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

  for (let i = 0; i < totalChunks; i++) {
    const chunk = file.slice(i * CHUNK_SIZE, (i + 1) * CHUNK_SIZE);
    const fd = new FormData();
    fd.append("chunk", chunk, file.name);
    fd.append("chunk_index", i);
    fd.append("total_chunks", totalChunks);
    fd.append("lang", lang);
    if (opts.step !== undefined) fd.append("step", opts.step);
    fd.append("type", opts.type || "step");

    try {
      const r = await fetch("/api/upload_chunk", { method: "POST", body: fd });
      const resp = await r.json();
      if (!resp.ok) {
        toast("❌ Chunk " + (i+1) + "/" + totalChunks + ": " + resp.error, "error");
        return;
      }
    } catch(e) {
      toast("❌ Error chunk " + (i+1) + ": " + e.message, "error");
      return;
    }
  }

  // All chunks uploaded — assemble
  const body = JSON.stringify({
    lang, type: opts.type,
    step: opts.step,
    total_chunks: totalChunks,
    original_name: file.name
  });

  try {
    const r = await fetch("/api/upload_assemble", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body
    });
    const resp = await r.json();
    if (resp.ok) {
      toast("🎵 Audio subido: " + resp.filename);
      loadData();
    } else {
      toast("❌ Error: " + resp.error, "error");
    }
  } catch(e) {
    toast("❌ Error: " + e.message, "error");
  }
}

async function addStep(lang) {
  try {
    const r = await fetch("/api/messages", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({lang, action: "add_step"})
    });
    const resp = await r.json();
    if (resp.ok) { toast("➕ Paso añadido"); loadData(); }
    else toast("❌ Error: " + resp.error, "error");
  } catch(e) {
    toast("❌ Error: " + e.message, "error");
  }
}

async function removeStep(lang, step) {
  if (!confirm("¿Eliminar paso " + (step+1) + " de " + LANG_NAMES[lang] + "?")) return;
  try {
    const r = await fetch("/api/messages", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({lang, step, action: "remove_step"})
    });
    const resp = await r.json();
    if (resp.ok) { toast("🗑 Paso eliminado"); loadData(); }
    else toast("❌ Error: " + resp.error, "error");
  } catch(e) {
    toast("❌ Error: " + e.message, "error");
  }
}

function previewLang(lang) {
  // Pequeña simulación de cómo se ve desde Telegram
  window.open("/preview/" + lang, "_blank", "width=400,height=600");
}

async function saveCallText(lang, text) {
  try {
    const r = await fetch("/api/messages", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({lang, text, action: "edit_call_text"})
    });
    const resp = await r.json();
    if (resp.ok) toast("📞 Mensaje de llamada guardado");
    else toast("❌ Error: " + resp.error, "error");
  } catch(e) {
    toast("❌ Error: " + e.message, "error");
  }
}

async function restartBot() {
  if (!confirm("¿Reiniciar el bot de Telegram? (toma efecto inmediato)")) return;
  toast("🔄 Reiniciando bot TG...", "success");
  fetch("/api/restart_bot", { method: "POST" }).catch(() => {});
  let attempts = 0;
  const check = setInterval(async () => {
    attempts++;
    try {
      const r = await fetch("/api/status");
      const d = await r.json();
      if (d.bot_running) {
        clearInterval(check);
        toast("✅ Bot TG reiniciado y online", "success");
        updateBotStatus(true);
      } else if (attempts >= 6) {
        clearInterval(check);
        toast("⚠️ Restart TG lanzado, verifica en el bot", "error");
      }
    } catch { if (attempts >= 6) { clearInterval(check); } }
  }, 2000);
}

async function restartWaBot() {
  if (!confirm("¿Reiniciar el bot de WhatsApp? (toma efecto inmediato)")) return;
  toast("🔄 Reiniciando bot WA...", "success");
  fetch("/api/restart_wa_bot", { method: "POST" }).catch(() => {});
  let attempts = 0;
  const check = setInterval(async () => {
    attempts++;
    try {
      const r = await fetch("/api/status");
      const d = await r.json();
      if (d.wa_running) {
        clearInterval(check);
        toast("✅ Bot WA reiniciado y online", "success");
        updateWaStatus(true);
      } else if (attempts >= 6) {
        clearInterval(check);
        toast("⚠️ Restart WA lanzado, verifica el QR si es primera vez", "error");
      }
    } catch { if (attempts >= 6) { clearInterval(check); } }
  }, 2000);
}

async function updateBotStatus(running) {
  const el = document.getElementById("bot-status");
  if (running === true) {
    el.className = "badge bg-success";
    el.innerHTML = '📱 TG User: <span class="status-dot status-online"></span> Online';
  } else if (running === false) {
    el.className = "badge bg-danger";
    el.innerHTML = '📱 TG User: <span class="status-dot status-offline"></span> Offline';
  } else {
    el.className = "badge bg-secondary";
    el.innerHTML = '📱 TG User: Incierto';
  }
}

async function updateBfStatus(running) {
  const el = document.getElementById("bf-status");
  if (running === true) {
    el.className = "badge bg-success";
    el.innerHTML = '🤖 BotFather: <span class="status-dot status-online"></span> Online';
  } else if (running === false) {
    el.className = "badge bg-secondary";
    el.innerHTML = '🤖 BotFather: No configurado';
  } else {
    el.className = "badge bg-secondary";
    el.innerHTML = '🤖 BotFather: Verificando...';
  }
}

async function updateWaStatus(running) {
  const el = document.getElementById("wa-status");
  const qrCard = document.getElementById("wa-qr-card");
  if (running === true) {
    el.className = "badge bg-success";
    el.innerHTML = '💬 WA: <span class="status-dot status-online"></span> Online';
    qrCard.style.display = 'none';
  } else if (running === false) {
    el.className = "badge bg-danger";
    el.innerHTML = '💬 WA: <span class="status-dot status-offline"></span> Offline';
    qrCard.style.display = 'none';
  } else if (running === null) {
    el.className = "badge bg-warning text-dark";
    el.innerHTML = '💬 WA: <span class="status-dot" style="background:#f39c12;"></span> No vinculado';
    // Mostrar QR si está disponible
    loadWaQr();
  } else {
    el.className = "badge bg-secondary";
    el.innerHTML = '💬 WA: Incierto';
    qrCard.style.display = 'none';
  }
}

async function loadWaQr() {
  const qrCard = document.getElementById("wa-qr-card");
  const qrImg = document.getElementById("wa-qr-img");
  try {
    const r = await fetch("/api/data");
    const d = await r.json();
    if (d.wa_qr) {
      qrImg.src = "/api/wa_qr?" + Date.now(); // timestamp para evitar caché
      qrCard.style.display = 'block';
    } else {
      qrCard.style.display = 'none';
    }
  } catch(e) {
    qrCard.style.display = 'none';
  }
}

async function refreshWaStatus() {
  toast("Verificando estado de WhatsApp...", "success");
  const r = await fetch("/api/status");
  const d = await r.json();
  updateWaStatus(d.wa_running);
  if (d.wa_running === true) {
    toast("✅ WhatsApp vinculado!", "success");
    document.getElementById("wa-qr-card").style.display = 'none';
  } else {
    toast("⏳ Todavía no vinculado, intenta de nuevo", "error");
  }
}

function showSetup() {
  document.getElementById("setup-modal").style.display = 'block';
  document.getElementById("tg-code-section").style.display = 'none';
  fetch("/api/tg_status").then(r => r.json()).then(d => {
    const el = document.getElementById("tg-link-status");
    if (d.linked) {
      el.innerHTML = '✅ <strong>Vinculado</strong> como ' + (d.display_name || 'usuario');
      document.getElementById("tg-api-id").placeholder = 'Ya configurado';
      document.getElementById("tg-api-hash").placeholder = 'Ya configurado';
      document.getElementById("tg-phone").placeholder = d.phone || 'Ya configurado';
    } else {
      el.innerHTML = '⚠️ Sin vincular. Ingresa api_id, api_hash y número de teléfono.';
    }
  }).catch(() => {});
  // BotFather status
  fetch("/api/bf_status").then(r => r.json()).then(d => {
    const el = document.getElementById("bf-link-status");
    if (d.linked) {
      el.innerHTML = '✅ <strong>Vinculado</strong> como @' + (d.bot_name || 'desconocido');
      document.getElementById("bf-token-input").placeholder = 'Token configurado';
    } else {
      el.innerHTML = '⚠️ Sin token. Crea un bot en @BotFather y pega el token.';
    }
  }).catch(() => {});
}

async function linkTelegram() {
  const api_id = document.getElementById("tg-api-id").value.trim();
  const api_hash = document.getElementById("tg-api-hash").value.trim();
  const phone = document.getElementById("tg-phone").value.trim();

  if (!api_id) { toast("❌ Ingresa el api_id", "error"); return; }
  if (!api_hash) { toast("❌ Ingresa el api_hash", "error"); return; }
  if (!phone) { toast("❌ Ingresa el número de teléfono", "error"); return; }

  const btn = event.target;
  btn.disabled = true;
  btn.innerHTML = '⏳ Conectando...';
  document.getElementById("tg-link-status").innerHTML = '🔄 Solicitando código a Telegram...';

  try {
    const r = await fetch("/api/link_telegram", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({api_id: parseInt(api_id), api_hash, phone})
    });
    const d = await r.json();
    if (d.needs_code) {
      // Mostrar campo de código
      document.getElementById("tg-code-phone").textContent = phone;
      document.getElementById("tg-code-section").style.display = 'block';
      document.getElementById("tg-code-input").value = '';
      document.getElementById("tg-code-input").focus();
      document.getElementById("tg-code-status").innerHTML = '';
      document.getElementById("tg-link-status").innerHTML = '📨 Código enviado a Telegram. Revísalo e ingrésalo abajo.';
      btn.disabled = false;
      btn.innerHTML = '🔗 Vincular';
    } else if (d.ok) {
      toast("✅ Vinculado. El bot se conectará como usuario.", "success");
      document.getElementById("tg-link-status").innerHTML = '✅ <strong>Vinculado</strong>';
      setTimeout(() => document.getElementById("setup-modal").style.display = 'none', 1500);
      btn.disabled = false;
      btn.innerHTML = '🔗 Vincular';
    } else {
      toast("❌ " + (d.error || "Error"), "error");
      document.getElementById("tg-link-status").innerHTML = '❌ ' + (d.error || "Error");
      btn.disabled = false;
      btn.innerHTML = '🔗 Vincular';
    }
  } catch(e) {
    toast("❌ Error: " + e.message, "error");
    btn.disabled = false;
    btn.innerHTML = '🔗 Vincular';
  }
}

async function verifyTgCode() {
  const code = document.getElementById("tg-code-input").value.trim();
  if (!code) { toast("❌ Ingresa el código", "error"); return; }

  document.getElementById("tg-code-status").innerHTML = '🔄 Verificando...';
  try {
    const r = await fetch("/api/verify_telegram_code", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({code})
    });
    const d = await r.json();
    if (d.ok) {
      toast("✅ ¡Vinculado correctamente!", "success");
      document.getElementById("tg-link-status").innerHTML = '✅ <strong>Vinculado</strong>';
      document.getElementById("tg-code-section").style.display = 'none';
      setTimeout(() => document.getElementById("setup-modal").style.display = 'none', 1500);
    } else if (d.needs_password) {
      // 2FA requerido
      document.getElementById("tg-2fa-section").style.display = 'block';
      document.getElementById("tg-password-input").focus();
      document.getElementById("tg-code-status").innerHTML = '🔐 Esta cuenta tiene 2FA. Ingresa tu contraseña abajo.';
    } else {
      document.getElementById("tg-code-status").innerHTML = '❌ ' + (d.error || "Código inválido");
    }
  } catch(e) {
    document.getElementById("tg-code-status").innerHTML = '❌ Error: ' + e.message;
  }
}

async function verifyTgPassword() {
  const password = document.getElementById("tg-password-input").value;
  if (!password) { toast("❌ Ingresa la contraseña", "error"); return; }

  document.getElementById("tg-password-status").innerHTML = '🔄 Verificando...';
  try {
    const r = await fetch("/api/verify_telegram_password", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({password})
    });
    const d = await r.json();
    if (d.ok) {
      toast("✅ ¡Vinculado correctamente!", "success");
      document.getElementById("tg-link-status").innerHTML = '✅ <strong>Vinculado</strong>';
      document.getElementById("tg-code-section").style.display = 'none';
      document.getElementById("tg-2fa-section").style.display = 'none';
      setTimeout(() => document.getElementById("setup-modal").style.display = 'none', 1500);
    } else {
      document.getElementById("tg-password-status").innerHTML = '❌ ' + (d.error || "Contraseña incorrecta");
    }
  } catch(e) {
    document.getElementById("tg-password-status").innerHTML = '❌ Error: ' + e.message;
  }
}

async function cancelTgAuth() {
  await fetch("/api/cancel_telegram_auth", {method: "POST"}).catch(() => {});
  document.getElementById("tg-code-section").style.display = 'none';
  document.getElementById("tg-2fa-section").style.display = 'none';
  document.getElementById("tg-link-status").innerHTML = '⚠️ Vinculación cancelada. Intenta de nuevo.';
}

async function linkBotFather() {
  const token = document.getElementById("bf-token-input").value.trim();
  if (!token) { toast("❌ Pega el token primero", "error"); return; }
  if (!token.includes(":")) { toast("❌ Token inválido", "error"); return; }

  const el = document.getElementById("bf-link-status");
  el.innerHTML = '🔄 Validando token...';

  try {
    const r = await fetch("/api/link_botfather", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token})
    });
    const d = await r.json();
    if (d.ok) {
      toast("✅ BotFather vinculado como @" + d.bot_name, "success");
      el.innerHTML = '✅ <strong>Vinculado</strong> como @' + d.bot_name;
    } else {
      toast("❌ " + (d.error || "Error"), "error");
      el.innerHTML = '❌ ' + (d.error || "Error");
    }
  } catch(e) {
    toast("❌ Error: " + e.message, "error");
    el.innerHTML = '❌ Error de conexión';
  }
}

async function launchWaAndShowQr() {
  document.getElementById("wa-link-status").innerHTML = '🔄 Lanzando WhatsApp bot...';
  try {
    const r = await fetch("/api/restart_wa_bot", { method: "POST" });
    const d = await r.json();
    if (d.ok) {
      document.getElementById("wa-link-status").innerHTML = '✅ Bot WhatsApp lanzado. Espera unos segundos y haz click en "Mostrar QR"';
      toast("✅ WA bot lanzado, el QR aparecerá en segundos", "success");
      setTimeout(loadWaQr, 5000);
    } else {
      document.getElementById("wa-link-status").innerHTML = '❌ ' + (d.error || "Error");
    }
  } catch(e) {
    document.getElementById("wa-link-status").innerHTML = '❌ Error: ' + e.message;
  }
}

// Auto-refresh cada 10 segundos
loadData();
setInterval(loadData, 10000);
// Auto-iniciar BotFather si hay token configurado
fetch("/api/start_botfather", {method:"POST"}).catch(()=>{});
</script>
</body>
</html>"""

# ── Preview template ──────────────────────────────────────────────────
PREVIEW_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>Vista previa — {{ lang_name }}</title>
<style>
body { background: #17212b; color: #e0e0e0; font-family: system-ui; margin: 0; padding: 16px; }
.msg { background: #2b5278; padding: 10px 14px; border-radius: 8px; margin-bottom: 12px; max-width: 85%; }
.msg.own { background: #182533; margin-left: auto; }
.audio-msg { background: #232e3c; padding: 8px 12px; border-radius: 8px; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; font-size: 0.9rem; }
.small { font-size: 0.75rem; color: #7f8c8d; margin-bottom: 4px; }
</style>
</head>
<body>
<div class="small">🤖 Bot AutoReply — {{ lang_name }}</div>
{% for step in steps %}
<div class="msg"><strong>Bot:</strong> {{ step.text }}</div>
<div class="audio-msg">🎵 {{ step.audio }}</div>
{% endfor %}
<div class="small" style="margin-top:16px;">* Así se ven los mensajes en Telegram</div>
</body>
</html>"""

# ── API Routes ────────────────────────────────────────────────────────

def load_messages_json():
    with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_messages_json(data):
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _read_env_var(key: str) -> str | None:
    """Lee una variable desde data/.env.local."""
    env_file = DATA_DIR / ".env.local"
    if not env_file.exists():
        return None
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _save_telegram_creds(api_id, api_hash, phone):
    """Guarda credenciales TG en data/.env.local."""
    env_file = DATA_DIR / ".env.local"
    lines = []
    if env_file.exists():
        with open(env_file, "r") as f:
            lines = f.readlines()
    new_lines = []
    replaced = {"TG_API_ID": False, "TG_API_HASH": False, "TG_PHONE": False}
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("TG_API_ID="):
            new_lines.append(f"TG_API_ID={api_id}\n")
            replaced["TG_API_ID"] = True
        elif stripped.startswith("TG_API_HASH="):
            new_lines.append(f"TG_API_HASH={api_hash}\n")
            replaced["TG_API_HASH"] = True
        elif stripped.startswith("TG_PHONE="):
            new_lines.append(f"TG_PHONE={phone}\n")
            replaced["TG_PHONE"] = True
        else:
            new_lines.append(line)
    for key, found in replaced.items():
        if not found:
            val = str(api_id) if key == "TG_API_ID" else (api_hash if key == "TG_API_HASH" else phone)
            new_lines.append(f"{key}={val}\n")
    with open(env_file, "w") as f:
        f.writelines(new_lines)


def bot_is_running():
    """Verifica si el bot está corriendo usando PowerShell (funciona en Windows)."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ['powershell.exe', '-Command',
                 "Get-CimInstance Win32_Process -Filter \"name = 'python.exe'\" | "
                 "Select-Object CommandLine | Format-Table -HideTableHeaders -AutoSize"],
                capture_output=True, text=True, timeout=5
            )
            return "bot.py" in result.stdout.lower() and "restart_bot.py" not in result.stdout.lower()
        else:
            result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=5
            )
            return "bot.py" in result.stdout and "restart_bot.py" not in result.stdout
    except:
        return None  # Incierto

@app.route("/")
def index():
    return render_template_string(TEMPLATE)

@app.route("/preview/<lang>")
def preview(lang):
    data = load_messages_json()
    lang_data = data.get(lang, data.get("en"))
    return render_template_string(
        PREVIEW_TEMPLATE,
        lang_name=lang_data.get("lang_name", lang.upper()),
        steps=lang_data.get("steps", [])
    )

@app.route("/api/data")
def api_data():
    messages = load_messages_json()
    running = bot_is_running()
    wa_running = wa_is_running()
    audios = {}
    for lang, lang_data in messages.items():
        audios[lang] = {}
        for step in lang_data.get("steps", []):
            audio_file = step.get("audio", "")
            audio_path = AUDIO_DIR / audio_file
            audios[lang][audio_file] = audio_path.exists()
    
    # Verificar si hay QR disponible
    qr_available = (BASE_DIR / "wa_qr.png").exists() if wa_running is None else False
    
    return jsonify({
        "ok": True,
        "messages": messages,
        "bot_running": running,
        "bf_running": bf_is_running(),
        "wa_running": wa_running,
        "wa_qr": qr_available,
        "audios": audios
    })

@app.route("/api/wa_qr")
def api_wa_qr():
    """Sirve el QR de WhatsApp como imagen PNG."""
    qr_path = BASE_DIR / "wa_qr.png"
    if qr_path.exists():
        return send_from_directory(str(BASE_DIR), "wa_qr.png")
    return jsonify({"ok": False, "error": "No QR available"}), 404

@app.route("/api/messages", methods=["POST"])
def api_messages():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400

    messages = load_messages_json()
    lang = data.get("lang")
    action = data.get("action")

    if lang not in messages:
        return jsonify({"ok": False, "error": f"Idioma '{lang}' no existe"}), 400

    lang_data = messages[lang]
    steps = lang_data["steps"]

    if action == "edit_text":
        step = data.get("step")
        text = data.get("text", "").strip()
        if step is None or step < 0 or step >= len(steps):
            return jsonify({"ok": False, "error": "Invalid step"}), 400
        steps[step]["text"] = text
        save_messages_json(messages)
        return jsonify({"ok": True})

    elif action == "add_step":
        step_num = len(steps) + 1
        audio_file = f"{lang}_msg{step_num}.mp3"
        steps.append({
            "step": step_num,
            "text": f"Nuevo mensaje {step_num}",
            "audio": audio_file
        })
        save_messages_json(messages)
        return jsonify({"ok": True})

    elif action == "remove_step":
        step = data.get("step")
        if step is None or step < 0 or step >= len(steps):
            return jsonify({"ok": False, "error": "Invalid step"}), 400
        if len(steps) <= 1:
            return jsonify({"ok": False, "error": "Debe haber al menos 1 paso"}), 400
        removed = steps.pop(step)
        save_messages_json(messages)
        return jsonify({"ok": True, "removed": removed})

    elif action == "edit_call_text":
        text = data.get("text", "").strip()
        if "call" not in lang_data:
            lang_data["call"] = {"text": "", "audio": ""}
        lang_data["call"]["text"] = text
        save_messages_json(messages)
        return jsonify({"ok": True})

    return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400

@app.route("/api/upload_call_audio", methods=["POST"])
def api_upload_call_audio():
    """Sube audio para el mensaje de llamada."""
    if "audio" not in request.files:
        return jsonify({"ok": False, "error": "No audio file"}), 400
    
    lang = request.form.get("lang")
    if not lang:
        return jsonify({"ok": False, "error": "lang required"}), 400
    
    file = request.files["audio"]
    if not file.filename.endswith((".mp3", ".ogg", ".wav")):
        return jsonify({"ok": False, "error": "Solo MP3, OGG o WAV"}), 400
    
    messages = load_messages_json()
    if lang not in messages:
        return jsonify({"ok": False, "error": f"Idioma '{lang}' no existe"}), 400
    
    audio_filename = f"{lang}_call.mp3"
    audio_path = AUDIO_DIR / audio_filename
    file.save(str(audio_path))
    
    # Actualizar messages.json con el audio de llamada
    if "call" not in messages[lang]:
        messages[lang]["call"] = {"text": "📞 Llamada recibida", "audio": audio_filename}
    else:
        messages[lang]["call"]["audio"] = audio_filename
    save_messages_json(messages)
    
    return jsonify({"ok": True, "filename": audio_filename, "path": str(audio_path)})

@app.route("/api/upload_audio", methods=["POST"])
def api_upload_audio():
    if "audio" not in request.files:
        return jsonify({"ok": False, "error": "No audio file"}), 400

    lang = request.form.get("lang")
    step = request.form.get("step", type=int)
    if not lang or step is None:
        return jsonify({"ok": False, "error": "lang and step required"}), 400

    messages = load_messages_json()
    if lang not in messages:
        return jsonify({"ok": False, "error": f"Idioma '{lang}' no existe"}), 400

    steps = messages[lang]["steps"]
    if step < 0 or step >= len(steps):
        return jsonify({"ok": False, "error": "Invalid step"}), 400

    file = request.files["audio"]
    if not file.filename.endswith((".mp3", ".ogg", ".wav")):
        return jsonify({"ok": False, "error": "Solo MP3, OGG o WAV"}), 400

    # Usar el nombre esperado del step
    audio_filename = steps[step]["audio"]
    audio_path = AUDIO_DIR / audio_filename
    file.save(str(audio_path))

    return jsonify({"ok": True, "filename": audio_filename, "path": str(audio_path)})

@app.route("/api/audio/<filename>")
def api_audio(filename):
    """Sirve archivos de audio para preview."""
    return send_from_directory(str(AUDIO_DIR), filename)

# ── Chunked upload (bypass proxy size limits) ─────────────────────────

@app.route("/api/upload_chunk", methods=["POST"])
def api_upload_chunk():
    """Recibe un chunk de audio. Cada chunk ≤ 500KB."""
    if "chunk" not in request.files:
        return jsonify({"ok": False, "error": "No chunk"}), 400

    lang = request.form.get("lang", "unknown")
    chunk_index = request.form.get("chunk_index", type=int)
    total_chunks = request.form.get("total_chunks", type=int)
    upload_type = request.form.get("type", "step")
    step = request.form.get("step", type=int)
    original_name = request.form.get("original_name", "audio.mp3")

    if chunk_index is None or total_chunks is None:
        return jsonify({"ok": False, "error": "chunk_index and total_chunks required"}), 400

    # Temp dir: data/temp_chunks/<lang>_<type>_<step>/
    if upload_type == "call":
        temp_key = f"{lang}_call"
    else:
        temp_key = f"{lang}_step{step}"
    temp_dir = DATA_DIR / "temp_chunks" / temp_key
    temp_dir.mkdir(parents=True, exist_ok=True)

    chunk = request.files["chunk"]
    chunk_path = temp_dir / f"chunk_{chunk_index:04d}"
    chunk.save(str(chunk_path))

    # Guardar metadata
    meta = {"total_chunks": total_chunks, "original_name": original_name,
            "type": upload_type, "lang": lang}
    if step is not None:
        meta["step"] = step
    with open(temp_dir / "meta.json", "w") as f:
        json.dump(meta, f)

    return jsonify({"ok": True, "chunk": chunk_index, "total": total_chunks})


@app.route("/api/upload_assemble", methods=["POST"])
def api_upload_assemble():
    """Reensambla los chunks en el archivo final de audio."""
    try:
        return _do_upload_assemble()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"Error interno: {str(e)}"}), 500


def _do_upload_assemble():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "JSON required"}), 400

    lang = data.get("lang")
    step_raw = data.get("step")
    step = int(step_raw) if step_raw is not None else None
    upload_type = data.get("type", "step")
    total_chunks = data.get("total_chunks")
    original_name = data.get("original_name", "")

    if not lang:
        return jsonify({"ok": False, "error": "lang required"}), 400

    # Encontrar temp dir
    if upload_type == "call":
        temp_key = f"{lang}_call"
    else:
        if step is None:
            return jsonify({"ok": False, "error": "step required"}), 400
        temp_key = f"{lang}_step{step}"

    temp_dir = DATA_DIR / "temp_chunks" / temp_key
    if not temp_dir.exists():
        return jsonify({"ok": False, "error": "No chunks found"}), 400

    # Verificar que todos los chunks están
    for i in range(total_chunks):
        if not (temp_dir / f"chunk_{i:04d}").exists():
            return jsonify({"ok": False, "error": f"Missing chunk {i}"}), 400

    # Determinar filename de salida
    if upload_type == "call":
        audio_filename = f"{lang}_call.mp3"
    else:
        messages = load_messages_json()
        if lang not in messages:
            return jsonify({"ok": False, "error": f"Idioma '{lang}' no existe"}), 400
        steps = messages[lang]["steps"]
        if step < 0 or step >= len(steps):
            return jsonify({"ok": False, "error": "Invalid step"}), 400
        audio_filename = steps[step]["audio"]

    # Ensamblar
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    audio_path = AUDIO_DIR / audio_filename
    try:
        with open(audio_path, "wb") as out:
            for i in range(total_chunks):
                chunk_path = temp_dir / f"chunk_{i:04d}"
                with open(chunk_path, "rb") as f_in:
                    out.write(f_in.read())
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error escribiendo audio: {str(e)}"}), 500

    # Si es call, actualizar messages.json
    if upload_type == "call":
        messages = load_messages_json()
        if lang in messages:
            if "call" not in messages[lang]:
                messages[lang]["call"] = {"text": "📞 Llamada recibida", "audio": audio_filename}
            else:
                messages[lang]["call"]["audio"] = audio_filename
            save_messages_json(messages)

    # Limpiar temp
    shutil.rmtree(str(temp_dir), ignore_errors=True)

    return jsonify({"ok": True, "filename": audio_filename})

def is_bot_running():
    """Verifica si el bot responde haciendo un ping a Telegram API (user bot no tiene getMe)."""
    # Con user bot, verificamos que el proceso esté corriendo
    return bot_is_running()

@app.route("/api/tg_status")
def api_tg_status():
    """Estado de la vinculación de Telegram (user bot)."""
    api_id = os.environ.get("TG_API_ID") or _read_env_var("TG_API_ID")
    linked = bool(api_id)
    result = {"linked": linked}
    if linked:
        phone = os.environ.get("TG_PHONE") or _read_env_var("TG_PHONE") or ""
        # Mostrar últimos 4 dígitos del teléfono
        if phone:
            result["display_name"] = "📱 ..." + phone[-4:] if len(phone) > 4 else phone
            result["phone"] = phone
    return jsonify(result)


@app.route("/api/link_telegram", methods=["POST"])
def api_link_telegram():
    """Inicia vinculación: guarda credenciales y pide código a Telegram desde el panel."""
    from telethon import TelegramClient
    from telethon.errors import ApiIdInvalidError

    data = request.get_json()
    api_id = data.get("api_id")
    api_hash = (data.get("api_hash") or "").strip()
    phone = (data.get("phone") or "").strip()

    if not api_id or not api_hash or not phone:
        return jsonify({"ok": False, "error": "api_id, api_hash y phone son requeridos"}), 400

    # Guardar en .env.local
    _save_telegram_creds(api_id, api_hash, phone)

    # Setear en environment
    os.environ["TG_API_ID"] = str(api_id)
    os.environ["TG_API_HASH"] = api_hash
    os.environ["TG_PHONE"] = phone

    # Iniciar cliente Telethon
    global _pending_auth
    session_file = str(DATA_DIR / "tg_session")

    def _do_auth():
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        try:
            client = TelegramClient(session_file, api_id, api_hash)
            loop.run_until_complete(client.connect())
            result = loop.run_until_complete(client.send_code_request(phone))
            _pending_auth = {
                "client": client,
                "phone_code_hash": result.phone_code_hash,
                "phone": phone,
            }
            return {"ok": True, "needs_code": True, "phone_code_hash": result.phone_code_hash}
        except ApiIdInvalidError:
            return {"ok": False, "error": "api_id o api_hash inválidos"}
        except Exception as e:
            return {"ok": False, "error": f"Error de conexión: {str(e)}"}

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(_do_auth)
        result = future.result(timeout=20)
        return jsonify(result)


@app.route("/api/verify_telegram_code", methods=["POST"])
def api_verify_telegram_code():
    """Verifica el código enviado por Telegram."""
    from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

    global _pending_auth

    if not _pending_auth:
        return jsonify({"ok": False, "error": "No hay autenticación pendiente"}), 400

    data = request.get_json()
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "Código requerido"}), 400

    client = _pending_auth["client"]
    phone = _pending_auth["phone"]
    phone_code_hash = _pending_auth["phone_code_hash"]

    def _do_signin():
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash))
            loop.run_until_complete(client.disconnect())
            _pending_auth.clear()
            return {"ok": True, "message": "Vinculado correctamente"}
        except SessionPasswordNeededError:
            return {"ok": False, "needs_password": True, "message": "2FA requerido"}
        except PhoneCodeInvalidError:
            return {"ok": False, "error": "Código inválido. Intenta de nuevo."}
        except Exception as e:
            return {"ok": False, "error": f"Error: {str(e)}"}

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(_do_signin)
        result = future.result(timeout=20)
        return jsonify(result)


@app.route("/api/verify_telegram_password", methods=["POST"])
def api_verify_telegram_password():
    """Verifica la contraseña de 2FA."""
    global _pending_auth

    if not _pending_auth:
        return jsonify({"ok": False, "error": "No hay autenticación pendiente"}), 400

    data = request.get_json()
    password = (data.get("password") or "")
    if not password:
        return jsonify({"ok": False, "error": "Contraseña requerida"}), 400

    client = _pending_auth["client"]

    def _do_password():
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(client.sign_in(password=password))
            loop.run_until_complete(client.disconnect())
            _pending_auth.clear()
            return {"ok": True, "message": "Vinculado correctamente"}
        except Exception as e:
            return {"ok": False, "error": f"Contraseña incorrecta: {str(e)}"}

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(_do_password)
        result = future.result(timeout=20)
        return jsonify(result)


@app.route("/api/cancel_telegram_auth", methods=["POST"])
def api_cancel_telegram_auth():
    """Cancela la autenticación pendiente."""
    global _pending_auth
    if _pending_auth:
        client = _pending_auth.get("client")
        if client:
            def _disconnect():
                loop = _asyncio.new_event_loop()
                _asyncio.set_event_loop(loop)
                loop.run_until_complete(client.disconnect())
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                executor.submit(_disconnect)
        _pending_auth.clear()
    return jsonify({"ok": True})

@app.route("/api/status")
def api_status():
    """Estado de los bots (para polling del frontend)."""
    return jsonify({
        "bot_running": is_bot_running(),
        "bf_running": bf_is_running(),
        "wa_running": wa_is_running()
    })


@app.route("/api/bf_status")
def api_bf_status():
    """Estado del BotFather bot."""
    token = os.environ.get("AUTOREPLY_BOT_TOKEN") or _read_env_var("AUTOREPLY_BOT_TOKEN")
    linked = token is not None
    result = {"linked": linked}
    if linked:
        try:
            import subprocess
            r = subprocess.run(
                ["curl", "-s", "--connect-timeout", "5",
                 f"https://api.telegram.org/bot{token}/getMe"],
                capture_output=True, text=True, timeout=10
            )
            data = json.loads(r.stdout)
            if data.get("ok"):
                result["bot_name"] = data["result"].get("username", "")
        except:
            pass
    return jsonify(result)


@app.route("/api/link_botfather", methods=["POST"])
def api_link_botfather():
    """Valida y guarda el token de BotFather."""
    import subprocess
    data = request.get_json()
    token = (data.get("token") or "").strip()

    if not token or ":" not in token:
        return jsonify({"ok": False, "error": "Token inválido"}), 400

    # Validar con Telegram
    try:
        r = subprocess.run(
            ["curl", "-s", "--connect-timeout", "5",
             f"https://api.telegram.org/bot{token}/getMe"],
            capture_output=True, text=True, timeout=10
        )
        resp = json.loads(r.stdout)
        if not resp.get("ok"):
            return jsonify({"ok": False, "error": "Token inválido o revocado"}), 400
        bot_name = resp["result"].get("username", "desconocido")
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error validando: {str(e)}"}), 500

    # Guardar en .env.local
    env_file = DATA_DIR / ".env.local"
    lines = []
    if env_file.exists():
        with open(env_file, "r") as f:
            lines = f.readlines()
    new_lines = []
    found = False
    for line in lines:
        if line.strip().startswith("AUTOREPLY_BOT_TOKEN="):
            new_lines.append(f"AUTOREPLY_BOT_TOKEN={token}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"AUTOREPLY_BOT_TOKEN={token}\n")
    with open(env_file, "w") as f:
        f.writelines(new_lines)

    os.environ["AUTOREPLY_BOT_TOKEN"] = token
    return jsonify({"ok": True, "bot_name": bot_name})


def bf_is_running():
    """Verifica si el BotFather bot está corriendo (proceso botfather_bot.py)."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ['powershell.exe', '-Command',
                 "Get-CimInstance Win32_Process -Filter \"name = 'python.exe'\" | "
                 "Select-Object CommandLine | Format-Table -HideTableHeaders -AutoSize"],
                capture_output=True, text=True, timeout=5
            )
            return "botfather_bot.py" in result.stdout.lower()
        else:
            # Usar ps aux que está disponible en cualquier Linux
            result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=5
            )
            return "botfather_bot.py" in result.stdout
    except:
        return False

def wa_is_running():
    """Verifica si el bot de WhatsApp (node wa_bot.mjs) está corriendo."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ['powershell.exe', '-Command',
                 "Get-CimInstance Win32_Process -Filter \"name = 'node.exe'\" | "
                 "Select-Object CommandLine | Format-Table -HideTableHeaders -AutoSize"],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.lower()
            if "wa_bot.mjs" in lines:
                return True
            # Si hay carpeta wa_auth/ pero no hay proceso, está desconectado
            if (DATA_DIR / "wa_auth").exists() and any((DATA_DIR / "wa_auth").iterdir()):
                return False  # Auth exists but process dead
            return None  # No vinculado aún
        else:
            result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=5
            )
            return "wa_bot.mjs" in result.stdout
    except:
        return None  # Incierto

def restart_wa_bot():
    """Reinicia el bot de WhatsApp matando el proceso node y relanzándolo."""
    import subprocess, sys, time
    
    # Matar procesos node existentes con wa_bot.mjs
    try:
        if sys.platform == "win32":
            ps_result = subprocess.run(
                ['powershell.exe', '-Command',
                 "Get-CimInstance Win32_Process -Filter \"name = 'node.exe'\" | "
                 "Select-Object ProcessId,CommandLine | ConvertTo-Csv -NoTypeInformation"],
                capture_output=True, text=True, timeout=10
            )
            for line in ps_result.stdout.splitlines():
                if "wa_bot.mjs" in line.lower() and '"' in line:
                    parts = line.replace('"', '').split(',')
                    if parts and parts[0].strip().isdigit():
                        pid = parts[0].strip()
                        subprocess.run(["taskkill", "/F", "/PID", pid], 
                                      capture_output=True, timeout=5)
                        time.sleep(1)
        else:
            subprocess.run(["pkill", "-f", "wa_bot.mjs"], capture_output=True, timeout=5)
            time.sleep(1)
    except:
        pass
    
    # Lanzar nuevo proceso wa_bot.mjs
    node = "node"
    wa_script = str(BASE_DIR / "wa_bot.mjs")
    log_file = str(BASE_DIR / "wa_bot.log")
    
    with open(log_file, "a") as f:
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.Popen(
                [node, wa_script],
                stdout=f, stderr=subprocess.STDOUT,
                cwd=BASE_DIR,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                startupinfo=startupinfo
            )
        else:
            proc = subprocess.Popen(
                [node, wa_script],
                stdout=f, stderr=subprocess.STDOUT,
                cwd=BASE_DIR,
                start_new_session=True
            )
    return proc.pid if proc else None

@app.route("/api/restart_bot", methods=["POST"])
def api_restart_bot():
    """Reinicia el bot usando script independiente que no mata el panel Flask."""
    import subprocess, sys, os, time

    restart_script = str(BASE_DIR / "restart_bot.py")
    python = sys.executable

    try:
        env = os.environ.copy()
        # Pasar credenciales del user bot
        
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            proc = subprocess.Popen(
                [python, restart_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                startupinfo=startupinfo
            )
        else:
            proc = subprocess.Popen(
                [python, restart_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True
            )
        
        # Esperar un poco y leer output
        time.sleep(2)
        try:
            stdout, _ = proc.communicate(timeout=5)
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
        except:
            output = f"Bot restart launched (PID {proc.pid})"
        
        return jsonify({"ok": True, "message": f"Bot reiniciado", "output": output})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/restart_wa_bot", methods=["POST"])
def api_restart_wa_bot():
    """Reinicia el bot de WhatsApp."""
    try:
        pid = restart_wa_bot()
        return jsonify({"ok": True, "message": "WA Bot reiniciado", "pid": pid})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/start_botfather", methods=["POST"])
def api_start_botfather():
    """Arranca el proceso botfather_bot.py si no está corriendo."""
    if bf_is_running():
        return jsonify({"ok": True, "message": "BotFather ya está corriendo"})

    token = os.environ.get("AUTOREPLY_BOT_TOKEN") or _read_env_var("AUTOREPLY_BOT_TOKEN")
    if not token:
        return jsonify({"ok": False, "error": "Token no configurado"}), 400

    try:
        import time, subprocess
        bot_script = str(BASE_DIR / "botfather_bot.py")
        log_file = str(BASE_DIR / "botfather_bot.log")
        with open(log_file, "a") as f:
            f.write(f"\n--- Started at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            subprocess.Popen(
                [sys.executable, bot_script],
                stdout=f, stderr=subprocess.STDOUT,
                start_new_session=True
            )
        return jsonify({"ok": True, "message": "BotFather iniciado"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Main ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")  # 0.0.0.0 para acceder desde la red
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    print(f"🚀 Panel AutoReply corriendo en http://localhost:{port}")
    print(f"📁 Mensajes: {MESSAGES_FILE}")
    print(f"🎵 Audios: {AUDIO_DIR}")
    print(f"🔄 Para producción: set HOST=0.0.0.0 PORT=5000 FLASK_SECRET=...")
    print(f"   Y usa gunicorn o espera a que te ayude a configurarlo.")

    app.run(host=host, port=port, debug=debug)
