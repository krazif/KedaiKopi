// KedaiKopi — messages.js
// Virtual scrolling, message DOM builders, delete/regenerate/swipe/clear.

// ─── Virtual Scrolling ─────────────────────────
const VIRTUAL_SCROLL_BATCH = 50; // default number of messages to render
let rpMessages = []; // full message array for RP mode
let rpVisibleCount = { value: VIRTUAL_SCROLL_BATCH };
let rpObserver = null;

function initVirtualScroll(containerId, messagesArr, visibleCountObj, observerRef) {
  const container = document.getElementById(containerId);
  if (!container) return;
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
        // User scrolled to the top — load more
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
  observerRef = obs;
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
    const frag = buildRPMessageDOM(msg, i);
    container.appendChild(frag);
  }
  // Scroll to bottom on new messages (only if already near bottom)
  const wasNearBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 100;
  if (wasNearBottom || sentinel === null) {
    container.scrollTop = container.scrollHeight;
  }
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
  // Content
  const contentDiv = document.createElement('div');
  contentDiv.className = 'rp-msg-content';
  contentDiv.innerHTML = formatMessage(msg.content);
  div.appendChild(contentDiv);
  // Actions (delete + regenerate for character)
  if (msg.role !== 'system') {
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
    div.appendChild(actionsDiv);
  }
  frag.appendChild(div);
  // If message also has an image, split it into a separate middle balloon below
  if (msg.imagePath) {
    frag.appendChild(buildImageBalloon(msg.imagePath, '/api/rp/images/', index, deleteRPMessage, msg.imagePrompt, msg.seed));
  }
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
  rpVisibleCount.value = Math.min(rpVisibleCount.value, rpMessages.length);
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
  rpVisibleCount.value = Math.min(rpVisibleCount.value, rpMessages.length);
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
  rpVisibleCount.value = Math.min(rpVisibleCount.value, rpMessages.length);
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
  rpVisibleCount.value = VIRTUAL_SCROLL_BATCH;
  const container = document.getElementById('rpChatMessages');
  if (container) container.innerHTML = '';
  if (rpObserver) { rpObserver.disconnect(); rpObserver = null; }
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
  _streamBubble = { containerId: 'rpChatMessages', el: div, contentEl, text: '' };
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
  b.contentEl.innerHTML = formatMessage(b.text);
  if (wasNearBottom) container.scrollTop = container.scrollHeight;
}

function clearStreamBubble() {
  if (_streamBubble) {
    _streamBubble.el.remove();
    _streamBubble = null;
  }
}

function handleStreamDelta(data) {
  if (!_streamBubble) {
    startStreamBubble(data.character_name || 'Someone');
  }
  appendStreamText(data.text || '');
}
