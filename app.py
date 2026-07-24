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
AUDIO_DIR = BASE_DIR / "audios"
MESSAGES_FILE = BASE_DIR / "messages.json"

app = Flask(__name__)
APP_SECRET = os.environ.get("FLASK_SECRET", "bot-autoreply-secret-change-me")
app.secret_key = APP_SECRET

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
        <span id="bot-status" class="badge bg-secondary" style="font-size:0.75rem;">📱 TG: Verificando...</span>
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
      <h6 class="mb-2">📱 Telegram</h6>
      <details class="mb-2">
        <summary class="text-muted small" style="cursor:pointer;">📖 ¿Cómo crear un bot en Telegram?</summary>
        <ol class="small mt-2" style="padding-left:1.5rem;">
          <li>Abre Telegram y busca <strong>@BotFather</strong></li>
          <li>Envía <code>/newbot</code> y sigue las instrucciones</li>
          <li>Elige un nombre y un username (termina en <em>bot</em>)</li>
          <li>BotFather te dará un <strong>token</strong> (ej: <code>123456789:ABCdefGHIjkl...</code>)</li>
          <li>Copia ese token y pégalo abajo</li>
        </ol>
      </details>
      <div class="d-flex align-items-center gap-2 mb-2">
        <input id="tg-token-input" type="text" class="form-control form-control-sm" placeholder="Pega aquí el token de BotFather" style="flex:1;font-family:monospace;font-size:0.8rem;">
        <button class="btn btn-sm btn-primary" onclick="linkTelegram()">🔗 Vincular</button>
        <button class="btn btn-sm btn-outline-light" onclick="testTelegram()">🔍 Probar</button>
      </div>
      <div id="tg-link-status" class="small text-muted mb-3"></div>

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
  const formData = new FormData();
  formData.append("audio", file);
  formData.append("lang", lang);
  formData.append("step", step);

  try {
    const r = await fetch("/api/upload_audio", { method: "POST", body: formData });
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

async function uploadCallAudio(lang, file) {
  if (!file) return;
  const formData = new FormData();
  formData.append("audio", file);
  formData.append("lang", lang);
  formData.append("type", "call");

  try {
    const r = await fetch("/api/upload_call_audio", { method: "POST", body: formData });
    const resp = await r.json();
    if (resp.ok) {
      toast("🎵 Audio de llamada subido: " + resp.filename);
      loadData();
    } else {
      toast("❌ Error: " + resp.error, "error");
    }
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
    el.innerHTML = '📱 TG: <span class="status-dot status-online"></span> Online';
  } else if (running === false) {
    el.className = "badge bg-danger";
    el.innerHTML = '📱 TG: <span class="status-dot status-offline"></span> Offline';
  } else {
    el.className = "badge bg-secondary";
    el.innerHTML = '📱 TG: Incierto';
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
  fetch("/api/tg_status").then(r => r.json()).then(d => {
    const el = document.getElementById("tg-link-status");
    if (d.linked) {
      el.innerHTML = '✅ <strong>Vinculado</strong> como @' + (d.bot_name || 'desconocido');
      document.getElementById("tg-token-input").placeholder = 'Token ya configurado — pega uno nuevo para cambiarlo';
    } else {
      el.innerHTML = '⚠️ No hay token. Crea un bot en @BotFather y pega el token.';
    }
  }).catch(() => {});
}

async function testTelegram() {
  const token = document.getElementById("tg-token-input").value.trim();
  if (!token) { toast("❌ Pega un token primero", "error"); return; }
  document.getElementById("tg-link-status").innerHTML = '🔄 Probando token...';
  try {
    const r = await fetch("/api/test_telegram", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token})
    });
    const d = await r.json();
    if (d.ok) {
      toast("✅ Token válido — @" + d.bot_name, "success");
      document.getElementById("tg-link-status").innerHTML = '✅ Token válido — @' + d.bot_name + '. Haz click en "🔗 Vincular" para guardarlo.';
    } else {
      toast("❌ " + (d.error || "Token inválido"), "error");
      document.getElementById("tg-link-status").innerHTML = '❌ ' + (d.error || "Token inválido");
    }
  } catch(e) {
    toast("❌ Error: " + e.message, "error");
  }
}

async function linkTelegram() {
  const token = document.getElementById("tg-token-input").value.trim();
  if (!token) { toast("❌ Pega el token primero", "error"); return; }
  if (!token.includes(":")) { toast("❌ Token inválido — debe tener formato 123456:ABC...", "error"); return; }
  
  const btn = event.target;
  btn.disabled = true;
  btn.innerHTML = '⏳ Validando...';
  document.getElementById("tg-link-status").innerHTML = '🔄 Validando token con Telegram...';
  
  try {
    const r = await fetch("/api/link_telegram", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token})
    });
    const d = await r.json();
    if (d.ok) {
      toast("✅ Telegram vinculado como @" + d.bot_name, "success");
      document.getElementById("tg-link-status").innerHTML = '✅ <strong>Vinculado</strong> como @' + d.bot_name;
      setTimeout(() => document.getElementById("setup-modal").style.display = 'none', 1500);
    } else {
      toast("❌ " + (d.error || "Error al vincular"), "error");
      document.getElementById("tg-link-status").innerHTML = '❌ ' + (d.error || "Error");
    }
  } catch(e) {
    toast("❌ Error de conexión: " + e.message, "error");
    document.getElementById("tg-link-status").innerHTML = '❌ Error de conexión';
  }
  btn.disabled = false;
  btn.innerHTML = '🔗 Vincular';
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

def get_bot_token():
    """Obtiene el token del bot desde environment o desde archivo .env.local."""
    token = os.environ.get("AUTOREPLY_BOT_TOKEN")
    if token:
        return token
    # Fallback: leer desde .env.local en el directorio del bot
    env_file = BASE_DIR / ".env.local"
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("AUTOREPLY_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None

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
                ["pgrep", "-f", "bot.py"], capture_output=True, timeout=5
            )
            return result.returncode == 0
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

def is_bot_running():
    """Verifica si el bot responde haciendo un ping a Telegram API."""
    import subprocess
    try:
        # Usar getMe para verificar conectividad
        result = subprocess.run(
            ["curl", "-s", "--connect-timeout", "5",
             f"https://api.telegram.org/bot{get_bot_token()}/getMe"],
            capture_output=True, text=True, timeout=10
        )
        return '"ok":true' in result.stdout
    except:
        return False

@app.route("/api/tg_status")
def api_tg_status():
    """Estado de la vinculación de Telegram."""
    token = get_bot_token()
    linked = token is not None
    result = {"linked": linked}
    if linked:
        # Obtener nombre del bot desde el token
        try:
            import subprocess
            r = subprocess.run(
                ["curl", "-s", "--connect-timeout", "5",
                 f"https://api.telegram.org/bot{token}/getMe"],
                capture_output=True, text=True, timeout=10
            )
            import json
            data = json.loads(r.stdout)
            if data.get("ok"):
                result["bot_name"] = data["result"].get("username", "")
                result["bot_id"] = data["result"].get("id", "")
        except:
            pass
        # Mostrar solo primeros 8 chars del token
        result["token_preview"] = token[:8] + "..." if len(token) > 8 else token
    return jsonify(result)

@app.route("/api/test_telegram", methods=["POST"])
def api_test_telegram():
    """Prueba un token sin guardarlo."""
    import subprocess, json
    data = request.get_json()
    token = (data.get("token") or "").strip()
    if not token or ":" not in token:
        return jsonify({"ok": False, "error": "Token inválido"}), 400
    try:
        r = subprocess.run(
            ["curl", "-s", "--connect-timeout", "5",
             f"https://api.telegram.org/bot{token}/getMe"],
            capture_output=True, text=True, timeout=10
        )
        resp = json.loads(r.stdout)
        if resp.get("ok"):
            return jsonify({"ok": True, "bot_name": resp["result"].get("username", "desconocido")})
        else:
            return jsonify({"ok": False, "error": "Token inválido o revocado"})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error: {str(e)}"}), 500

@app.route("/api/link_telegram", methods=["POST"])
def api_link_telegram():
    """Vincula un token de Telegram, lo guarda en .env.local y reinicia el bot."""
    import subprocess, json
    
    data = request.get_json()
    token = (data.get("token") or "").strip()
    
    if not token or ":" not in token:
        return jsonify({"ok": False, "error": "Token inválido"}), 400
    
    # Validar token con Telegram API
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
        return jsonify({"ok": False, "error": f"No se pudo validar: {str(e)}"}), 500
    
    # Guardar en .env.local
    env_file = BASE_DIR / ".env.local"
    try:
        lines = []
        if env_file.exists():
            with open(env_file, "r") as f:
                lines = f.readlines()
        
        # Reemplazar o agregar la línea del token
        found = False
        new_lines = []
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
    except Exception as e:
        return jsonify({"ok": False, "error": f"No se pudo guardar token: {str(e)}"}), 500
    
    # Reiniciar el bot de Telegram de forma multiplataforma
    import subprocess, sys, time
    restart_script = str(BASE_DIR / "restart_bot.py")
    python = sys.executable
    env = os.environ.copy()
    env["AUTOREPLY_BOT_TOKEN"] = token
    
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.Popen(
            [python, restart_script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            startupinfo=startupinfo
        )
    else:
        subprocess.Popen(
            [python, restart_script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True
        )
    
    return jsonify({"ok": True, "bot_name": bot_name, "message": f"Vinculado como @{bot_name}"})

@app.route("/api/status")
def api_status():
    """Estado de los bots (para polling del frontend)."""
    return jsonify({
        "bot_running": is_bot_running(),
        "wa_running": wa_is_running()
    })

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
            if (BASE_DIR / "wa_auth").exists() and any((BASE_DIR / "wa_auth").iterdir()):
                return False  # Auth exists but process dead
            return None  # No vinculado aún
        else:
            result = subprocess.run(
                ["pgrep", "-f", "wa_bot.mjs"], capture_output=True, timeout=5
            )
            return result.returncode == 0
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
        token = get_bot_token()
        if token:
            env["AUTOREPLY_BOT_TOKEN"] = token
        
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
