// KedaiKopi — core.js
// Core state, card version helpers, console, token estimation.

// ─── State ──────────────────────────────────────
let currentCard = null;
let currentFilename = null;
let currentPersona = null;
let currentPersonaFilename = null;
let editorData = null;
let editorTab = 'core';
let editorVersion = 2;
let editorNormalized = null;
let editorOriginal = null;
// Active stack builder context
let activeStackConfig = null;
let activeStackWS = null;

// ─── Card Version Support (V1/V2/V3) ──────────────
const V3_ALIASES = { first_mes: 'first_message', mes_example: 'message_examples' };
function detectCardVersion(card) {
  const spec = card.spec || '';
  if (spec.includes('v3')) return 3;
  if (spec.includes('v2')) return 2;
  if (card.data) return 2;
  return 1;
}
function contentToString(val) {
  if (!val) return '';
  if (typeof val === 'string') return val;
  if (Array.isArray(val)) return val.map(b => (typeof b === 'object' && b.text) ? b.text : (typeof b === 'string' ? b : '')).join('\n');
  return String(val);
}
function normalizeForEditing(card) {
  const d = card.data || card;
  const normalized = {};
  for (const [key, val] of Object.entries(d)) {
    const v2Key = Object.entries(V3_ALIASES).find(([_, v3]) => v3 === key)?.[0];
    const targetKey = v2Key || key;
    if (targetKey === 'tags') {
      normalized[targetKey] = Array.isArray(val) ? val : (typeof val === 'string' ? val.split(',').map(s=>s.trim()).filter(Boolean) : val);
    } else if (targetKey === 'alternate_greetings' || targetKey === 'group_only_greetings') {
      normalized[targetKey] = Array.isArray(val) ? val.map(v => contentToString(v)) : val;
    } else {
      normalized[targetKey] = contentToString(val);
    }
  }
  return normalized;
}
function denormalizeForSaving(normalized, version, original) {
  if (version === 1) {
    const flat = {};
    for (const [key, val] of Object.entries(normalized)) {
      if (key === 'system_prompt' || key === 'post_history_instructions' || key === 'creator_notes' || key === 'alternate_greetings') continue; // V1 doesn't have these
      flat[key] = val;
    }
    return flat;
  } else if (version === 3) {
    const d = {};
    for (const [key, val] of Object.entries(normalized)) {
      const v3Key = V3_ALIASES[key] || key;
      d[v3Key] = val;
    }
    return { ...original, spec: 'chara_card_v3', spec_version: original.spec_version || '3.0', data: d };
  } else {
    return { ...original, spec: original.spec || 'chara_card_v2', spec_version: original.spec_version || '2.0', data: { ...normalized } };
  }
}
let isWaiting = false;
let personasList = [];
let personaEditorData = null;
let personaEditorFilename = null;
let consoleOpen = false;
let consoleMaximized = false;
let consoleLimit = parseInt(localStorage.getItem('cs_console_limit')); // 0 = unlimited
if (isNaN(consoleLimit)) consoleLimit = 300; // sensible default so consoles don't grow without bound

// Restore console limit inputs on load
function initConsoleLimit() {
  const si = document.getElementById('consoleLimitInput');
  const ri = document.getElementById('rpConsoleLimitInput');
  if (si) si.value = consoleLimit;
  if (ri) ri.value = consoleLimit;
}

function onConsoleLimitChange(val) {
  consoleLimit = Math.max(0, parseInt(val) || 0);
  localStorage.setItem('cs_console_limit', consoleLimit);
  // Sync both inputs
  const si = document.getElementById('consoleLimitInput');
  const ri = document.getElementById('rpConsoleLimitInput');
  if (si) si.value = consoleLimit;
  if (ri) ri.value = consoleLimit;
  // Immediately trim existing entries
  trimConsoleEntries(document.getElementById('consoleInner'));
  trimConsoleEntries(document.getElementById('rpConsoleInner'));
}

function trimConsoleEntries(inner) {
  if (!inner || consoleLimit <= 0) return;
  const entries = inner.querySelectorAll('.console-entry');
  const excess = entries.length - consoleLimit;
  if (excess > 0) {
    for (let i = 0; i < excess; i++) entries[i].remove();
    // Update count badges to reflect actual visible entries
    const visible = inner.querySelectorAll('.console-entry').length;
    if (inner.id === 'rpConsoleInner') {
      rpConsoleEvents = visible;
      const el = document.getElementById('rpConsoleCount');
      if (el) el.textContent = rpConsoleEvents;
    }
  }
}

// ─── Console ────────────────────────────────────
function toggleConsole() {
  consoleOpen = !consoleOpen;
  const panels = document.querySelectorAll('#rpConsolePanel');
  const chevrons = document.querySelectorAll('#consoleChevron, #rpConsoleChevron');
  panels.forEach(p => {
    if (consoleOpen) { p.classList.add('open'); } else { p.classList.remove('open'); }
  });
  chevrons.forEach(c => {
    if (consoleOpen) { c.classList.add('open'); } else { c.classList.remove('open'); }
  });
  if (consoleOpen) {
    // Scroll whichever inner is visible
    const inners = document.querySelectorAll('#consoleInner, #rpConsoleInner');
    inners.forEach(i => { i.scrollTop = i.scrollHeight; });
  }
}

function toggleConsoleMax() {
  const panels = document.querySelectorAll('#consolePanel, #rpConsolePanel');
  const maxBtns = document.querySelectorAll('#consoleMaxBtn, #rpConsoleMaxBtn');
  consoleMaximized = !consoleMaximized;
  panels.forEach(p => {
    if (consoleMaximized) { p.classList.add('maximized'); } else { p.classList.remove('maximized'); }
  });
  maxBtns.forEach(b => {
    b.textContent = consoleMaximized ? '⤓' : '⤢';
    b.title = consoleMaximized ? 'Restore' : 'Expand to maximum';
  });
  if (consoleMaximized && !consoleOpen) {
    consoleOpen = true;
    panels.forEach(p => p.classList.add('open'));
    document.querySelectorAll('#consoleChevron, #rpConsoleChevron').forEach(c => c.classList.add('open'));
  }
  setTimeout(() => {
    const inners = document.querySelectorAll('#consoleInner, #rpConsoleInner');
    inners.forEach(i => { i.scrollTop = i.scrollHeight; });
  }, 250);
}

// ─── Token estimation (~4 chars/token, +4 overhead per message) ─────────
function estimateTokens(messages) {
  if (!messages || !messages.length) return 0;
  let total = 0;
  for (const m of messages) {
    const content = m.content || '';
    total += Math.ceil(content.length / 4) + 4;
  }
  return total;
}

function getSessionMessages() {
  // Extract messages from the virtual scrolling arrays (not DOM, since not all are rendered)
  const messages = rpMessages;
  return messages.map(m => ({ content: m.content }));
}

function estimateBlockTokens(block, allMsgs) {
  const btype = block.type;
  if (btype === 'system') {
    // System prompt is built server-side; use the stored text from session payload
    const cfg = rpStackConfig;
    const text = (cfg && cfg._systemPromptText) ? cfg._systemPromptText : '';
    return { summary: text ? Math.ceil(text.length / 4) + 4 : 0, raw: 0 };
  }
  if (btype === 'custom') {
    const text = block.text || '';
    return { summary: text ? Math.ceil(text.length / 4) + 4 : 0, raw: 0 };
  }
  if (btype === 'summary_chunk') {
    const summaryTok = block.text ? Math.ceil(block.text.length / 4) + 4 : 0;
    const start = block.start ?? 0;
    const end = block.end ?? 0;
    const rawMsgs = allMsgs.slice(start, end);
    const rawTok = estimateTokens(rawMsgs);
    return { summary: summaryTok, raw: rawTok };
  }
  if (btype === 'head') {
    const n = block.n ?? 2;
    const rawMsgs = allMsgs.slice(0, n);
    return { summary: 0, raw: estimateTokens(rawMsgs) };
  }
  if (btype === 'raw_mid') {
    const start = block.start ?? 0;
    const end = block.end ?? 0;
    const rawMsgs = allMsgs.slice(start, end);
    return { summary: 0, raw: estimateTokens(rawMsgs) };
  }
  if (btype === 'tail') {
    const n = block.n ?? 3;
    const rawMsgs = allMsgs.slice(-n);
    return { summary: 0, raw: estimateTokens(rawMsgs) };
  }
  return { summary: 0, raw: 0 };
}

function formatTokens(n) {
  if (n === 0) return '0';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(n);
}
