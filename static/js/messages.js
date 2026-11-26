// KedaiKopi — messages.js
// Virtual scrolling, message DOM builders, delete/regenerate/swipe/clear.

// ─── Virtual Scrolling ─────────────────────────
const VIRTUAL_SCROLL_BATCH = 50; // default number of messages to render
let rpMessages = []; // full message array for RP mode
let rpVisibleCount = { value: VIRTUAL_SCROLL_BATCH };
let rpObserver = null;
let rpPhoneVisible = { value: VIRTUAL_SCROLL_BATCH };   // phone pane has its own scroll-back
let rpPhoneObserver = null;

function initVirtualScroll(containerId, messagesArr, visibleCountObj, observerRef) {
  const container = document.getElementById(containerId);
  if (!container) return null;
  // Clean up old observer
  if (observerRef) observerRef.disconnect();
  // Create sentinel
  let sentinel = container.querySelector('.virtual-scroll-sentinel');
  if (!sentinel) {
    sentinel = document.createElement('div');
    sentinel.className = 'virtual-scroll-sentinel';
    sentinel.style.height = '1px';
    sentinel.style.width = '100%';
    container.prepend(sentinel);
  }
  const obs = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        // User scrolled to the top — load more. NEVER shrink: capping the
        // window to messagesArr.length on a SHORT list collapses it (the
        // sentinel is always visible there, so this callback runs at init)
        // and Math.min keeps it tiny forever — the field "one by one" bug
        // where each new message replaced the previous on screen.
        if (messagesArr.length <= visibleCountObj.value) return;
        const oldCount = visibleCountObj.value;
        visibleCountObj.value = Math.min(visibleCountObj.value + VIRTUAL_SCROLL_BATCH, messagesArr.length);
        if (visibleCountObj.value > oldCount) {
          const prevScrollHeight = container.scrollHeight;
          renderVirtualMessages(containerId, messagesArr, visibleCountObj.value);
          // Preserve scroll position so the view doesn't jump
          requestAnimationFrame(() => {
            container.scrollTop = container.scrollHeight - prevScrollHeight;
          });
        }
      }
    }
  }, { root: container, threshold: 0 });
  obs.observe(sentinel);
  observerRef = obs;   // (local — callers must use the return value)
  return obs;
}

function renderVirtualMessages(containerId, messagesArr, visibleCount) {
  const container = document.getElementById(containerId);
  if (!container) return;
  // Save sentinel if present
  const sentinel = container.querySelector('.virtual-scroll-sentinel');
  // Clear container
  container.innerHTML = '';
  // Re-add sentinel at top
  if (sentinel) container.appendChild(sentinel);
  // Calculate which messages to show
  const total = messagesArr.length;
  const start = Math.max(0, total - visibleCount);
  // Render messages from start to end
  for (let i = start; i < total; i++) {
    const msg = messagesArr[i];
    const frag = (containerId === 'rpPhoneMessages') ? buildTextMessageDOM(msg, i)
                                                     : buildRPMessageDOM(msg, i);
    container.appendChild(frag);
  }
  // Scroll to bottom on new messages (only if already near bottom)
  const wasNearBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 100;
  if (wasNearBottom || sentinel === null) {
    container.scrollTop = container.scrollHeight;
  }
  // The phone pane mirrors the prose pane whenever the dock is open
  if (containerId === 'rpChatMessages'
      && typeof isRPPhoneDockOpen === 'function' && isRPPhoneDockOpen()) {
    renderVirtualMessages('rpPhoneMessages', messagesArr, rpPhoneVisible.value);
  }
}

function buildRPActions(msg, index) {
  if (msg.role === 'system') return null;
  const actionsDiv = document.createElement('div');
    actionsDiv.className = 'rp-msg-actions';
    if (msg.role === 'character') {
      const wordCount = (msg.content || '').trim().split(/\s+/).filter(w => w.length > 0).length;
      const wcSpan = document.createElement('span');
      wcSpan.className = 'msg-word-count';
      wcSpan.textContent = wordCount + ' words';
      actionsDiv.appendChild(wcSpan);
      // Swipe controls
      const swipeCount = (msg.swipes && msg.swipes.length) ? msg.swipes.length : 1;
      const activeSwipe = msg.activeSwipe || 0;
      if (swipeCount > 1) {
        const swipeDiv = document.createElement('span');
        swipeDiv.className = 'swipe-controls';
        const leftBtn = document.createElement('a');
        leftBtn.textContent = '◀';
        leftBtn.className = 'swipe-arrow';
        leftBtn.onclick = () => swipeRPMessage(index, activeSwipe - 1);
        if (activeSwipe <= 0) leftBtn.style.opacity = '0.3';
        swipeDiv.appendChild(leftBtn);
        const counter = document.createElement('span');
        counter.className = 'swipe-counter';
        counter.textContent = (activeSwipe + 1) + '/' + swipeCount;
        swipeDiv.appendChild(counter);
        const rightBtn = document.createElement('a');
        rightBtn.textContent = '▶';
        rightBtn.className = 'swipe-arrow';
        rightBtn.onclick = () => swipeRPMessage(index, activeSwipe + 1);
        if (activeSwipe >= swipeCount - 1) rightBtn.style.opacity = '0.3';
        swipeDiv.appendChild(rightBtn);
        actionsDiv.appendChild(swipeDiv);
      }
      const regenLink = document.createElement('a');
      if (msg.truncated && index === rpMessages.length - 1) {
        const contLink = document.createElement('a');
        contLink.className = 'continue-link';
        contLink.textContent = 'continue';
        contLink.title = 'This reply hit the length limit — extend it';
        contLink.onclick = () => continueRPMessage();
        actionsDiv.appendChild(contLink);
      }
      regenLink.className = 'rp-regenerate-link';
      regenLink.textContent = 'regenerate';
      regenLink.onclick = () => regenerateRPMessage(index);
      actionsDiv.appendChild(regenLink);
    }
    const delLink = document.createElement('a');
    delLink.className = 'rp-delete-link';
    delLink.textContent = 'delete';
    delLink.onclick = () => deleteRPMessage(index);
    actionsDiv.appendChild(delLink);
    const delFromHere = document.createElement('a');
    delFromHere.className = 'rp-delete-link';
    delFromHere.textContent = 'delete from here';
    delFromHere.onclick = () => deleteRPMessageFromHere(index);
  actionsDiv.appendChild(delFromHere);
  return actionsDiv;
}

// ─── Diegetic text lines: `Name: message` from a known speaker ───
// One protocol, three surfaces: the prose pane renders them as text
// blocks, the phone pane extracts them into bubbles, and the model is
// told to write texts in exactly this format (engine: PHONE TEXTS).
function knownTextSenders() {
  const out = [];
  const expand = n => {
    if (!n) return;
    out.push(n);
    // ALL tokens: the card says "Lisa Surihani", the model writes `Lisa:`
    // (field evidence) — and a hand-typed `Razif:` must match "M. Razif Hussin".
    String(n).split(/\s+/).forEach(t => { if (t) out.push(t); });
  };
  if (typeof rpCharacters !== 'undefined') {
    rpCharacters.forEach(c => { if (c && c.name) expand(c.name); });
  }
  if (typeof currentPersona !== 'undefined' && currentPersona && currentPersona.name) {
    expand(currentPersona.name);
  }
  out.push('You', 'User');   // no-persona fallbacks (prompt + label defaults)
  // longest first so the canonical form wins when both would match
  return out.filter(Boolean).sort((a, b) => b.length - a.length);
}

function matchTextLine(line, names) {
  let t = line.trim();
  // Tolerate label shapes the model has actually produced: a bracketed
  // label (`[Farah]: msg`, and the old marking echo `[Farah (you)]: msg`)
  // is a sender line all the same — field evidence: the history marking
  // leaked into replies and stranded the first text in the chat scene.
  if (t.startsWith('[')) {
    const bclose = t.indexOf(']:');
    if (bclose !== -1) t = t.slice(1, bclose) + ':' + t.slice(bclose + 2);
  }
  for (const n of names) {
    if (t.length > n.length + 1 &&
        t.slice(0, n.length + 1).toLowerCase() === (n + ':').toLowerCase()) {
      const text = t.slice(n.length + 1).trim();
      if (text) return { name: n, text };
    }
    // Decorated echo from the old history marking (`Farah (you): msg`) —
    // accept it and report the plain name, so already-stored messages
    // extract into bubbles instead of stranding in the chat (field bug:
    // a 2-text reply showed 1 bubble, the first text sat in the scene).
    if (t.length > n.length + 1 &&
        t.slice(0, n.length + 1).toLowerCase() === (n + ' ').toLowerCase()) {
      const rest = t.slice(n.length + 1);
      if (rest.startsWith('(')) {
        const close = rest.indexOf('):');
        if (close !== -1) {
          const text = rest.slice(close + 2).trim();
          if (text) return { name: n, text };
        }
      }
    }
  }
  return null;
}

function extractTextLines(content) {
  const names = knownTextSenders();
  const out = [];
  (content || '').split('\n').forEach(line => {
    const hit = matchTextLine(line, names);
    if (hit) out.push(hit);
  });
  return out;
}

function isUserSideTextName(name) {
  const persona = (typeof currentPersona !== 'undefined' && currentPersona && currentPersona.name) || null;
  const n = (name || '').toLowerCase();
  if (persona && persona.toLowerCase().split(/\s+/).includes(n)) return true;  // full or token
  return n === 'you' || n === 'user';
}

// Texting style: drop a leading own-sender `Name:` echo before bubbling
// (the bubble's side + header already say who sent it).
function stripOwnSenderPrefix(content, msg) {
  const sender = msg.role === 'user'
    ? ((typeof currentPersona !== 'undefined' && currentPersona && currentPersona.name) || 'You')
    : (msg.speaker || null);
  if (!sender) return content;
  const nl = content.indexOf('\n');
  const first = nl === -1 ? content : content.slice(0, nl);
  const rest = nl === -1 ? '' : content.slice(nl);
  const f = first.trim();
  if (f.length > sender.length + 1 &&
      f.slice(0, sender.length + 1).toLowerCase() === (sender + ':').toLowerCase()) {
    return f.slice(sender.length + 1).trim() + rest;
  }
  return content;
}

// Prose pane = narration only. Recognized text lines are parsed OUT of
// the chat and live in the phone; each message leaves a tappable chip
// where they were, so closing the phone never hides content silently.
// Texting-style sessions keep the raw mirror (that pane pair IS the
// conversation there) — exclusion is for RP, where texts mix into prose.
function renderProseContent(content) {
  const frag = document.createDocumentFragment();
  if (typeof rpResponseStyle !== 'undefined' && rpResponseStyle === 'texting') {
    const div = document.createElement('div');
    div.className = 'rp-prose-run';
    div.innerHTML = formatMessage(content || '');
    frag.appendChild(div);
    return frag;
  }
  const names = knownTextSenders();
  let proseRun = [];
  let chip = null;
  let dropped = 0;
  const flushProse = () => {
    if (!proseRun.length) return;
    const div = document.createElement('div');
    div.className = 'rp-prose-run';
    div.innerHTML = formatMessage(proseRun.join('\n'));
    frag.appendChild(div);
    proseRun = [];
  };
  (content || '').split('\n').forEach(line => {
    if (matchTextLine(line, names)) {
      flushProse();
      if (!chip) {
        chip = document.createElement('div');
        chip.className = 'rp-texts-chip';
        chip.title = 'Show in the phone';
        chip.onclick = () => toggleRPTextView(true);
        frag.appendChild(chip);
      }
      dropped++;
    } else {
      proseRun.push(line);
    }
  });
  flushProse();
  if (chip) chip.textContent = `💬 ${dropped} text${dropped > 1 ? 's' : ''}`;
  return frag;
}

function buildRPMessageDOM(msg, index) {
  const frag = document.createDocumentFragment();
  // Image-only message: just a middle balloon, no chat bubble
  if (msg.imagePath && (!msg.content || !msg.content.trim())) {
    frag.appendChild(buildImageBalloon(msg.imagePath, '/api/rp/images/', index, deleteRPMessage, msg.imagePrompt, msg.seed));
    return frag;
  }
  const div = document.createElement('div');
  div.className = 'rp-msg ' + msg.role;
  div.dataset.messageId = msg.messageId || '';
  div.dataset.clientId = msg.clientId || '';
  // Badge
  const badge = document.createElement('span');
  badge.className = 'rp-msg-badge';
  badge.textContent = index;
  div.appendChild(badge);
  // Label
  const label = document.createElement('span');
  label.className = 'rp-msg-label';
  div.appendChild(document.createTextNode(' '));
  if (msg.role === 'user') {
    label.textContent = msg.personaName || 'You';
  } else if (msg.role === 'system') {
    label.textContent = 'System';
  } else {
    label.textContent = msg.speaker || 'Character';
  }
  div.appendChild(label);
  // Content — text lines get the text-block treatment, rest stays prose
  const contentDiv = document.createElement('div');
  contentDiv.className = 'rp-msg-content';
  contentDiv.appendChild(renderProseContent(msg.content));
  div.appendChild(contentDiv);
  const actionsDiv = buildRPActions(msg, index);
  if (actionsDiv) div.appendChild(actionsDiv);
  frag.appendChild(div);
  // If message also has an image, split it into a separate middle balloon below
  if (msg.imagePath) {
    frag.appendChild(buildImageBalloon(msg.imagePath, '/api/rp/images/', index, deleteRPMessage, msg.imagePrompt, msg.seed));
  }
  return frag;
}

// ─── Texting (SMS) view ──────────────────────────────────────
// Animate only the first build of a message: seeded history is registered
// here up front, so only messages that arrive live pop in.
const txSeen = new Set();

function txSeedSeen() {
  rpMessages.forEach(m => {
    const k = m.clientId || m.messageId;
    if (k) txSeen.add(k);
  });
}

// One bubble per burst: a line containing only ··· (or ... / …) splits the
// message the way a texter would have sent it.
function splitBursts(content) {
  const text = (content || '').trim();
  if (!text) return [];
  const parts = text.split(/^[ \t]*(?:···|\.\.\.|…)[ \t]*$/m)
                   .map(s => s.trim()).filter(Boolean);
  return parts.length ? parts : [text];
}

function buildTextMessageDOM(msg, index) {
  const frag = document.createDocumentFragment();
  const textingStyle = (typeof rpResponseStyle !== 'undefined' && rpResponseStyle === 'texting');

  // Scene images belong to texting-style threads; in RP they're stage art,
  // not the messaging layer.
  if (msg.imagePath && (!msg.content || !msg.content.trim())) {
    if (textingStyle) {
      frag.appendChild(buildImageBalloon(msg.imagePath, '/api/rp/images/', index, deleteRPMessage, msg.imagePrompt, msg.seed));
    }
    return frag;
  }

  const key = msg.clientId || msg.messageId || '';
  const isNew = !!key && !txSeen.has(key);
  if (key) txSeen.add(key);

  const nameOf = mm => !mm ? null
    : mm.role === 'user' ? (mm.personaName || 'You')
    : mm.role === 'system' ? null
    : (mm.speaker || 'Character');

  if (textingStyle) {
    // The whole message is the text: one container, ··· bursts, and any
    // leading own-sender `Name:` echo stripped (side + header carry it).
    const role = msg.role === 'user' ? 'user' : (msg.role === 'system' ? 'system' : 'character');
    const div = document.createElement('div');
    div.className = 'tx-msg ' + role;
    div.dataset.messageId = msg.messageId || '';
    div.dataset.clientId = msg.clientId || '';
    if (isNew) div.classList.add('tx-new');

    const name = nameOf(msg);
    const prev = index > 0 ? rpMessages[index - 1] : null;
    const prevName = nameOf(prev);
    if (name && (!prev || name !== prevName || prev.role !== msg.role)) {
      const n = document.createElement('div');
      n.className = 'tx-name';
      n.textContent = name;
      div.appendChild(n);
    }

    const content = stripOwnSenderPrefix((msg.content || '').trim(), msg);
    if (content) {
      splitBursts(content).forEach((text, i) => {
        const bub = document.createElement('div');
        bub.className = 'tx-bubble';
        bub.style.setProperty('--i', String(i));
        bub.innerHTML = formatMessage(text);
        div.appendChild(bub);
      });
    }
    const actionsDiv = buildRPActions(msg, index);
    if (actionsDiv) div.appendChild(actionsDiv);
    frag.appendChild(div);
    if (msg.imagePath) {
      frag.appendChild(buildImageBalloon(msg.imagePath, '/api/rp/images/', index, deleteRPMessage, msg.imagePrompt, msg.seed));
    }
    return frag;
  }

  // RP session: the phone is the messaging layer — only extracted
  // `Name:` lines reach it; prose-only messages contribute nothing.
  const texts = extractTextLines(msg.content);
  if (!texts.length) return frag;
  const prev = index > 0 ? rpMessages[index - 1] : null;
  const prevName = nameOf(prev);
  let lastDiv = null;
  texts.forEach((t, i) => {
    const side = isUserSideTextName(t.name) ? 'user' : 'character';
    const div = document.createElement('div');
    div.className = 'tx-msg ' + side;
    div.dataset.messageId = msg.messageId || '';
    div.dataset.clientId = msg.clientId || '';
    if (isNew) div.classList.add('tx-new');

    // header: within the group, and vs the previous message's sender
    const headerAgainst = i > 0 ? texts[i - 1].name : prevName;
    if (t.name !== headerAgainst) {
      const n = document.createElement('div');
      n.className = 'tx-name';
      n.textContent = t.name;
      div.appendChild(n);
    }

    const bub = document.createElement('div');
    bub.className = 'tx-bubble';
    bub.style.setProperty('--i', String(i));
    bub.innerHTML = formatMessage(t.text);
    div.appendChild(bub);
    frag.appendChild(div);
    lastDiv = div;
  });
  // actions once per message, on its last bubble
  const actionsDiv = buildRPActions(msg, index);
  if (actionsDiv && lastDiv) lastDiv.appendChild(actionsDiv);
  return frag;
}

function deleteRPMessage(index) {
  if (index < 0 || index >= rpMessages.length) return;
  const msg = rpMessages[index];
  const msgId = msg.messageId;
  const cid = msg.clientId;
  if ((msgId || cid) && rpWS && rpWS.readyState === WebSocket.OPEN) {
    const payload = { type: 'delete_single_message' };
    if (msgId) payload.message_id = msgId;
    else payload.client_msg_id = cid;
    rpWS.send(JSON.stringify(payload));
  }
  rpMessages.splice(index, 1);
  renderVirtualMessages('rpChatMessages', rpMessages, rpVisibleCount.value);
}

function deleteRPMessageFromHere(index) {
  if (index < 0 || index >= rpMessages.length) return;
  const msg = rpMessages[index];
  const msgId = msg.messageId;
  const cid = msg.clientId;
  if ((msgId || cid) && rpWS && rpWS.readyState === WebSocket.OPEN) {
    const payload = { type: 'delete_message' };
    if (msgId) payload.message_id = msgId;
    else payload.client_msg_id = cid;
    rpWS.send(JSON.stringify(payload));
  }
  rpMessages.splice(index);
  renderVirtualMessages('rpChatMessages', rpMessages, rpVisibleCount.value);
}

function deleteRPMessageByClientId(cid) {
  if (!cid) return;
  const idx = rpMessages.findIndex(m => m.clientId === cid);
  if (idx >= 0) deleteRPMessage(idx);
}

function regenerateRPMessage(index) {
  if (index < 0 || index >= rpMessages.length) return;
  const msg = rpMessages[index];
  if (msg.role !== 'character') return;
  const msgId = msg.messageId;
  if (!msgId || !rpWS || rpWS.readyState !== WebSocket.OPEN) return;
  // Remove subsequent messages but keep the target (swipe will update it)
  rpMessages.splice(index + 1);
  renderVirtualMessages('rpChatMessages', rpMessages, rpVisibleCount.value);
  // Tell server to truncate after target and regenerate as swipe
  rpWS.send(JSON.stringify({ type: 'regenerate_message', message_id: msgId }));
}

function swipeRPMessage(index, swipeIndex) {
  if (index < 0 || index >= rpMessages.length) return;
  const msg = rpMessages[index];
  const msgId = msg.messageId;
  if (!msgId || !rpWS || rpWS.readyState !== WebSocket.OPEN) return;
  if (swipeIndex < 0) return;
  rpWS.send(JSON.stringify({ type: 'swipe_message', message_id: msgId, swipe_index: swipeIndex }));
}

function openImageLightbox(src, promptText, seed) {
  const box = document.createElement('div');
  box.className = 'image-lightbox';
  const img = document.createElement('img');
  img.src = src;
  box.appendChild(img);
  // Seed badge (top-right corner)
  if (seed !== undefined && seed !== null) {
    const seedBadge = document.createElement('div');
    seedBadge.style.cssText = 'position:absolute;top:16px;right:16px;background:rgba(20,20,20,0.9);border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:6px 12px;font-size:13px;font-family:monospace;color:#a5d6a7;cursor:default;user-select:text';
    seedBadge.textContent = 'seed: ' + seed;
    seedBadge.onclick = (e) => e.stopPropagation();
    box.appendChild(seedBadge);
  }
  if (promptText) {
    const promptBox = document.createElement('div');
    promptBox.style.cssText = 'position:absolute;bottom:16px;left:50%;transform:translateX(-50%);max-width:80%;background:rgba(20,20,20,0.92);border:1px solid rgba(255,255,255,0.15);border-radius:8px;padding:10px 14px;display:flex;align-items:flex-start;gap:10px;cursor:default';
    const promptSpan = document.createElement('span');
    promptSpan.style.cssText = 'color:#ccc;font-size:12px;line-height:1.5;flex:1;white-space:pre-wrap;word-break:break-word';
    promptSpan.textContent = promptText;
    const copyBtn = document.createElement('button');
    copyBtn.textContent = 'Copy';
    copyBtn.style.cssText = 'flex-shrink:0;font-size:12px;padding:4px 10px;border:1px solid rgba(255,255,255,0.2);border-radius:4px;background:rgba(255,255,255,0.1);color:#fff;cursor:pointer';
    copyBtn.onclick = (e) => {
      e.stopPropagation();
      navigator.clipboard.writeText(promptText).then(() => {
        copyBtn.textContent = '✓';
        setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
      }).catch(() => {
        copyBtn.textContent = '✗';
        setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
      });
    };
    promptBox.appendChild(promptSpan);
    promptBox.appendChild(copyBtn);
    promptBox.onclick = (e) => e.stopPropagation();
    box.appendChild(promptBox);
  }
  box.onclick = () => box.remove();
  document.body.appendChild(box);
}

function clearRPChat() {
  clearStreamBubble();
  rpMessages = [];
  txSeen.clear();
  rpVisibleCount.value = VIRTUAL_SCROLL_BATCH;
  rpPhoneVisible.value = VIRTUAL_SCROLL_BATCH;
  const container = document.getElementById('rpChatMessages');
  if (container) container.innerHTML = '';
  const phone = document.getElementById('rpPhoneMessages');
  if (phone) phone.innerHTML = '';
  if (rpObserver) { rpObserver.disconnect(); rpObserver = null; }
  if (rpPhoneObserver) { rpPhoneObserver.disconnect(); rpPhoneObserver = null; }
}

// ─── End Virtual Scrolling ──────────────────────

// ─── Live streaming ─────────────────────────────
// While the LLM generates, the server pushes `character_delta` frames; they
// render into this temporary bubble and the final `character_message`
// replaces it with the stored message. The server already holds back RP auto
// mode's leading "[Name]:" prefix, so what lands here matches the final text.
let _streamBubble = null;   // { containerId, el, contentEl, text }

function startStreamBubble(label) {
  clearStreamBubble();
  hideRPTyping();  // swap the typing dots for the growing bubble
  const container = document.getElementById('rpChatMessages');
  if (!container) return;
  const div = document.createElement('div');
  div.id = 'streamBubble';
  div.className = 'rp-msg character streaming';
  const labelEl = document.createElement('span');
  labelEl.className = 'rp-msg-label';
  labelEl.textContent = label || '';
  div.appendChild(labelEl);
  const contentEl = document.createElement('div');
  contentEl.className = 'rp-msg-content';
  div.appendChild(contentEl);
  container.appendChild(div);
  _streamBubble = { containerId: 'rpChatMessages', el: div, contentEl, text: '',
                    phoneEl: null, phoneContentEl: null };
  // The phone pane grows its own bubble alongside when the dock is open
  if (typeof isRPPhoneDockOpen === 'function' && isRPPhoneDockOpen()) {
    const pdiv = document.createElement('div');
    pdiv.id = 'streamBubblePhone';
    pdiv.className = 'tx-msg character streaming';
    const plabel = document.createElement('span');
    plabel.className = 'tx-name';
    plabel.textContent = label || '';
    pdiv.appendChild(plabel);
    const pcontent = document.createElement('div');
    pcontent.className = 'tx-bubble tx-streaming';
    pdiv.appendChild(pcontent);
    const pcont = document.getElementById('rpPhoneMessages');
    if (pcont) { pcont.appendChild(pdiv); pcont.scrollTop = pcont.scrollHeight; }
    _streamBubble.phoneEl = pdiv;
    _streamBubble.phoneContentEl = pcontent;
  }
}

function appendStreamText(text) {
  if (!_streamBubble || !text) return;
  const b = _streamBubble;
  const container = document.getElementById(b.containerId);
  if (!container) return;
  const wasNearBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 120;
  // The virtual scroller rebuilds the container — re-attach if it dropped us
  if (!b.el.isConnected) container.appendChild(b.el);
  b.text += text;
  b.contentEl.innerHTML = formatMessage(b.text);          // prose: raw, as stored
  if (b.phoneContentEl) {
    // phone: separators hidden mid-stream (the final render splits them)
    b.phoneContentEl.innerHTML = formatMessage(
      b.text.replace(/^[ \t]*(?:···|\.\.\.|…)[ \t]*$/gm, ''));
    const pcont = document.getElementById('rpPhoneMessages');
    if (pcont) pcont.scrollTop = pcont.scrollHeight;
  }
  if (wasNearBottom) container.scrollTop = container.scrollHeight;
}

function clearStreamBubble() {
  if (_streamBubble) {
    _streamBubble.el.remove();
    if (_streamBubble.phoneEl) _streamBubble.phoneEl.remove();
    _streamBubble = null;
  }
}

function handleStreamDelta(data) {
  if (!_streamBubble) {
    startStreamBubble(data.character_name || 'Someone');
  }
  appendStreamText(data.text || '');
}
