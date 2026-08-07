/* ═══════════════════════════════════════════════════════════════════════
   Google Services AI Agent — Frontend Logic
   ═══════════════════════════════════════════════════════════════════════

   Boot sequence:
     1. checkAuth() → GET /api/auth-status
     2a. Not authenticated → show #authScreen  (user clicks "Sign in with Google"
                                                → /auth/login → Google OAuth
                                                → /auth/callback → redirected back)
     2b. Authenticated     → hide #authScreen, show #chatApp, open WebSocket
   ═══════════════════════════════════════════════════════════════════════ */

'use strict';

// ── Constants ──────────────────────────────────────────────────────────
const WS_URL       = `ws://${location.host}/ws`;
const RECONNECT_MS = 3500;
const MAX_INPUT_H  = 160;   // px

// ── DOM references ─────────────────────────────────────────────────────
const authScreenEl = document.getElementById('authScreen');
const chatAppEl    = document.getElementById('chatApp');
const messagesEl   = document.getElementById('messages');
const userInputEl  = document.getElementById('userInput');
const sendBtnEl    = document.getElementById('sendBtn');
const statusDotEl  = document.getElementById('statusDot');
const statusTxtEl  = document.getElementById('statusText');
const newChatBtnEl = document.getElementById('newChatBtn');
const welcomeCard  = document.getElementById('welcomeCard');

// ── State ──────────────────────────────────────────────────────────────
let ws          = null;
let isReady     = false;
let typingRowEl = null;

// ── Marked.js setup ────────────────────────────────────────────────────
marked.setOptions({
  gfm: true,
  breaks: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      return hljs.highlight(code, { language: lang }).value;
    }
    return hljs.highlightAuto(code).value;
  },
});

// ═══════════════════════════════════════════════════════════════════════
//  AUTH CHECK  — run once on page load
// ═══════════════════════════════════════════════════════════════════════

async function checkAuth() {
  try {
    const res  = await fetch('/api/auth-status');
    const data = await res.json();

    if (data.authenticated) {
      showChatApp();
      connectWS();
    } else {
      showAuthScreen();
    }
  } catch {
    // Server unreachable — show auth screen with an error hint
    showAuthScreen();
  }
}

function showAuthScreen() {
  authScreenEl.classList.remove('hidden');
  chatAppEl.classList.add('hidden');
}

function showChatApp() {
  authScreenEl.classList.add('hidden');
  chatAppEl.classList.remove('hidden');
}

// ═══════════════════════════════════════════════════════════════════════
//  WEBSOCKET
// ═══════════════════════════════════════════════════════════════════════

function connectWS() {
  setStatus('connecting', 'Connecting…');

  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    setStatus('connecting', 'Initializing…');
  };

  ws.onmessage = (evt) => {
    try { handleServerMsg(JSON.parse(evt.data)); }
    catch { /* ignore malformed frames */ }
  };

  ws.onclose = () => {
    isReady = false;
    sendBtnEl.disabled = true;
    setStatus('error', 'Disconnected');
    setTimeout(connectWS, RECONNECT_MS);
  };

  ws.onerror = () => {
    setStatus('error', 'Connection error');
  };
}

function handleServerMsg(msg) {
  switch (msg.type) {

    case 'auth_required':
      // Token expired between page load and WS connect — re-auth
      showAuthScreen();
      break;

    case 'status':
      setStatus('connecting', msg.message);
      break;

    case 'ready':
      isReady = true;
      sendBtnEl.disabled = !userInputEl.value.trim();
      setStatus('connected', 'Connected');
      break;

    case 'typing':
      showTyping();
      break;

    case 'message':
      hideTyping();
      appendMessage(msg.role, msg.content);
      break;

    case 'error':
      hideTyping();
      appendError(msg.message);
      break;
  }
}

// ── Status pill ────────────────────────────────────────────────────────
function setStatus(state, text) {
  statusDotEl.className = `status-dot ${state}`;
  statusTxtEl.textContent = text;
}

// ── Welcome card ───────────────────────────────────────────────────────
function dismissWelcome() {
  if (!welcomeCard || !welcomeCard.parentNode) return;
  welcomeCard.style.transition = 'opacity 0.3s, transform 0.3s';
  welcomeCard.style.opacity    = '0';
  welcomeCard.style.transform  = 'translateY(-8px)';
  setTimeout(() => welcomeCard.remove(), 320);
}

// ── Append message ─────────────────────────────────────────────────────
function appendMessage(role, content) {
  dismissWelcome();

  const wrap   = document.createElement('div');
  wrap.className = `msg ${role}`;

  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = role === 'user' ? 'You' : 'AI';

  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  if (role === 'assistant') {
    bubble.innerHTML = marked.parse(content);
    bubble.querySelectorAll('pre code').forEach(b => hljs.highlightElement(b));
    bubble.querySelectorAll('a[href]').forEach(a => {
      if (a.hostname !== location.hostname) a.target = '_blank';
    });
  } else {
    bubble.textContent = content;
  }

  wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  scrollBottom();
}

function appendError(text) {
  const el = document.createElement('div');
  el.className = 'error-row';
  el.textContent = `Error: ${text}`;
  messagesEl.appendChild(el);
  scrollBottom();
}

// ── Typing indicator ───────────────────────────────────────────────────
function showTyping() {
  hideTyping();
  const wrap   = document.createElement('div');
  wrap.className = 'typing-row';
  wrap.id = '__typing__';

  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = 'AI';

  const bubble = document.createElement('div');
  bubble.className = 'typing-bubble';
  bubble.innerHTML = '<div class="td"></div><div class="td"></div><div class="td"></div>';

  wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  typingRowEl = wrap;
  scrollBottom();
}

function hideTyping() {
  if (typingRowEl) { typingRowEl.remove(); typingRowEl = null; }
  document.getElementById('__typing__')?.remove();
}

function scrollBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── Send ───────────────────────────────────────────────────────────────
function sendMessage() {
  const text = userInputEl.value.trim();
  if (!text || !isReady || !ws || ws.readyState !== WebSocket.OPEN) return;

  appendMessage('user', text);
  ws.send(JSON.stringify({ type: 'message', content: text }));

  userInputEl.value = '';
  userInputEl.style.height = 'auto';
  sendBtnEl.disabled = true;
  userInputEl.focus();
}

// ── Input auto-resize ──────────────────────────────────────────────────
function resizeInput() {
  userInputEl.style.height = 'auto';
  userInputEl.style.height = Math.min(userInputEl.scrollHeight, MAX_INPUT_H) + 'px';
}

// ── Event listeners ────────────────────────────────────────────────────
sendBtnEl.addEventListener('click', sendMessage);

userInputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

userInputEl.addEventListener('input', () => {
  resizeInput();
  sendBtnEl.disabled = !userInputEl.value.trim() || !isReady;
});

document.querySelectorAll('.quick-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (!isReady) return;
    const prompt = btn.dataset.prompt;
    if (prompt) { userInputEl.value = prompt; resizeInput(); sendMessage(); }
  });
});

// Example chips in welcome card
window.useChip = (el) => {
  if (!isReady) return;
  userInputEl.value = el.textContent.replace(/^"+|"+$/g, '').trim();
  resizeInput();
  sendMessage();
};

// New conversation — reload resets history
newChatBtnEl.addEventListener('click', () => location.reload());

// ── Boot ───────────────────────────────────────────────────────────────
checkAuth();
