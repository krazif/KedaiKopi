// KedaiKopi — cards.js
// Card upload/download/delete/list, character generation modal.

// ─── API ────────────────────────────────────────

// ─── Character Generation ──────────────────────
let genNsfwOn = false;
let genLastCard = null;
let genLastVersion = 2;

function openGenerateModal() {
  resetGenerateForm();
  document.getElementById('genOverlay').classList.add('show');
}

function closeGenerateModal() {
  document.getElementById('genOverlay').classList.remove('show');
}

function toggleGenNsfw() {
  genNsfwOn = !genNsfwOn;
  const toggle = document.getElementById('genNsfwToggle');
  const label = document.getElementById('genNsfwLabel');
  if (genNsfwOn) {
    toggle.classList.add('on');
    label.textContent = 'NSFW';
    label.style.color = 'var(--accent)';
  } else {
    toggle.classList.remove('on');
    label.textContent = 'SFW';
    label.style.color = 'var(--text-dim)';
  }
}

function showGenView(view) {
  // view: 'form', 'loading', 'preview'
  document.getElementById('genForm').style.display = view === 'form' ? '' : 'none';
  document.getElementById('genLoading').style.display = view === 'loading' ? '' : 'none';
  document.getElementById('genError').style.display = 'none';
  document.getElementById('genPreview').classList.toggle('show', view === 'preview');
  document.getElementById('genFooterForm').style.display = view === 'form' ? '' : 'none';
  document.getElementById('genFooterPreview').style.display = view === 'preview' ? '' : 'none';
}

function resetGenerateForm() {
  document.getElementById('genConcept').value = '';
  document.getElementById('genName').value = '';
  document.getElementById('genAge').value = '';
  document.getElementById('genPersonality').value = '';
  document.getElementById('genScenario').value = '';
  document.getElementById('genAppearance').value = '';
  document.getElementById('genVersion').value = '2';
  document.getElementById('genCreator').value = 'Richard';
  genNsfwOn = false;
  document.getElementById('genNsfwToggle').classList.remove('on');
  document.getElementById('genNsfwLabel').textContent = 'SFW';
  document.getElementById('genNsfwLabel').style.color = 'var(--text-dim)';
  genLastCard = null;
  showGenView('form');
}

async function generateCharacter() {
  const concept = document.getElementById('genConcept').value.trim();
  if (!concept) {
    const err = document.getElementById('genError');
    err.textContent = 'Please provide a concept for the character.';
    err.style.display = 'block';
    return;
  }

  const payload = {
    concept,
    name: document.getElementById('genName').value.trim(),
    age: document.getElementById('genAge').value.trim(),
    personality: document.getElementById('genPersonality').value.trim(),
    scenario: document.getElementById('genScenario').value.trim(),
    appearance: document.getElementById('genAppearance').value.trim(),
    version: parseInt(document.getElementById('genVersion').value),
    creator: document.getElementById('genCreator').value.trim(),
    nsfw: genNsfwOn,
  };
  genLastVersion = payload.version;

  showGenView('loading');

  try {
    const res = await fetch('/api/generate-character', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    // Render console events (request + response/error) in the LLM console
    if (data.console_events) {
      for (const ev of data.console_events) {
        addRPConsoleEntry(ev);  // the only console left
      }
    }

    if (data.error) {
      const err = document.getElementById('genError');
      err.textContent = data.error;
      err.style.display = 'block';
      showGenView('form');
      return;
    }

    genLastCard = data.card;
    renderGenPreview(data.card, payload.version);
    showGenView('preview');
  } catch (e) {
    const err = document.getElementById('genError');
    err.textContent = 'Failed to generate: ' + e.message;
    err.style.display = 'block';
    showGenView('form');
  }
}

function regenerateCharacter() {
  // Keep form values, just regenerate
  generateCharacter();
}

function renderGenPreview(card, version) {
  const isV2 = version === 2;
  const data = isV2 ? (card.data || card) : card;

  // V2 text fields to show in preview
  const v2Fields = [
    ['name', 'Name', 'input'],
    ['description', 'Description', 'textarea'],
    ['personality', 'Personality', 'textarea'],
    ['scenario', 'Scenario', 'textarea'],
    ['first_mes', 'First Message', 'textarea'],
    ['mes_example', 'Message Examples', 'textarea'],
    ['creator_notes', 'Creator Notes', 'textarea'],
    ['system_prompt', 'System Prompt', 'textarea'],
  ];
  const v1Fields = [
    ['name', 'Name', 'input'],
    ['description', 'Description', 'textarea'],
    ['personality', 'Personality', 'textarea'],
    ['scenario', 'Scenario', 'textarea'],
    ['first_mes', 'First Message', 'textarea'],
    ['mes_example', 'Message Examples', 'textarea'],
  ];
  const fields = isV2 ? v2Fields : v1Fields;

  let html = '';
  for (const [key, label, type] of fields) {
    const val = (data[key] || '').toString();
    if (type === 'input') {
      html += `<div class="gen-preview-field"><label>${label}</label><input type="text" id="genPrev_${key}" value="${escapeHtml(val)}" style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:8px 10px;font-size:12px;font-family:inherit" /></div>`;
    } else {
      const rows = Math.max(3, Math.ceil(val.length / 80));
      html += `<div class="gen-preview-field"><label>${label}</label><textarea id="genPrev_${key}" rows="${rows}" style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:8px 10px;font-size:12px;font-family:inherit;resize:vertical;min-height:50px">${escapeHtml(val)}</textarea></div>`;
    }
  }

  // Tags
  const tags = Array.isArray(data.tags) ? data.tags.join(', ') : '';
  html += `<div class="gen-preview-field"><label>Tags (comma-separated)</label><input type="text" id="genPrev_tags" value="${escapeHtml(tags)}" style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:8px 10px;font-size:12px;font-family:inherit" /></div>`;

  document.getElementById('genPreviewFields').innerHTML = html;
}

function collectGenPreviewCard() {
  const isV2 = genLastVersion === 2;
  const data = isV2 ? (genLastCard.data || genLastCard) : genLastCard;

  const v2Fields = ['name', 'description', 'personality', 'scenario', 'first_mes', 'mes_example', 'creator_notes', 'system_prompt'];
  const v1Fields = ['name', 'description', 'personality', 'scenario', 'first_mes', 'mes_example'];
  const fields = isV2 ? v2Fields : v1Fields;

  for (const key of fields) {
    const el = document.getElementById('genPrev_' + key);
    if (el) data[key] = el.value;
  }

  // Tags
  const tagsEl = document.getElementById('genPrev_tags');
  if (tagsEl) {
    data.tags = tagsEl.value.split(',').map(t => t.trim()).filter(Boolean);
  }

  if (isV2) {
    genLastCard.data = data;
    genLastCard.spec = 'chara_card_v2';
    genLastCard.spec_version = '2.0';
  } else {
    genLastCard = data;
  }

  return genLastCard;
}

async function saveGeneratedCard() {
  if (!genLastCard) return;
  const card = collectGenPreviewCard();

  try {
    const res = await fetch('/api/generate-character/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ card }),
    });
    const data = await res.json();

    if (data.error) {
      const err = document.getElementById('genError');
      err.textContent = data.error;
      err.style.display = 'block';
      return;
    }

    // Refresh card list and close
    await loadCardList();
    closeGenerateModal();
    // Select the new card
    if (data.filename) {
      selectCard(data.filename);
    }
  } catch (e) {
    const err = document.getElementById('genError');
    err.textContent = 'Failed to save: ' + e.message;
    err.style.display = 'block';
  }
}

async function uploadCard(event) {
  const file = event.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const resp = await fetch('/api/cards/upload', {method: 'POST', body: formData});
    const result = await resp.json();
    if (resp.ok) {
      alert(`Uploaded (${result.format||'json'}): ${result.name} → ${result.filename}`);
      await loadCardList();
    } else {
      alert('Upload failed: ' + (result.error || 'Unknown error'));
    }
  } catch (e) {
    alert('Upload failed: ' + e.message);
  }
  event.target.value = ''; // reset so same file can be re-uploaded
}

function downloadCardPNG(filename) {
  window.open(`/api/cards/${encodeURIComponent(filename)}/png`, '_blank');
}

function downloadCardJSON(filename) {
  window.open(`/api/cards/${encodeURIComponent(filename)}/json`, '_blank');
}

async function deleteCard(filename, name) {
  if (!confirm(`Delete "${name}"?\n\nThis will permanently remove the character card and its avatar from storage. This cannot be undone.`))
    return;
  try {
    const resp = await fetch('/api/cards/' + encodeURIComponent(filename), {method: 'DELETE'});
    const result = await resp.json();
    if (resp.ok) {
      // Clear current selection if we deleted the active card
      if (currentFilename === filename) {
        currentFilename = null;
        currentCard = null;
        document.querySelectorAll('.card-item').forEach(el => el.classList.remove('active'));
      }
      await loadCardList();
    } else {
      alert('Delete failed: ' + (result.error || 'Unknown error'));
    }
  } catch (e) {
    alert('Delete failed: ' + e.message);
  }
}

async function uploadPersona(event) {
  const file = event.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const resp = await fetch('/api/personas/upload', {method: 'POST', body: formData});
    const result = await resp.json();
    if (resp.ok) {
      alert(`Uploaded: ${result.name} → ${result.filename}`);
      await loadPersonaList();
    } else {
      alert('Upload failed: ' + (result.error || 'Unknown error'));
    }
  } catch (e) {
    alert('Upload failed: ' + e.message);
  }
  event.target.value = '';
}

async function loadCardList() {
  const resp = await fetch('/api/cards');
  const cards = await resp.json();
  const list = document.getElementById('cardList');
  list.innerHTML = '';
  cards.forEach(c => {
    const div = document.createElement('div');
    div.className = 'card-item';
    div.onclick = () => selectCard(c.filename);
    const vbadge = c.version ? `<span class="card-version v${c.version}">V${c.version}</span>` : '';
    div.innerHTML = `<div class="name">${escapeHtml(c.name)} ${vbadge}</div><div class="tags">${(c.tags||[]).slice(0,4).map(t=>'<span>'+escapeHtml(t)+'</span>').join('')}</div><div class="card-dl-btns"><button class="card-dl-btn" onclick="event.stopPropagation();downloadCardPNG('${c.filename}')" title="Download as PNG card">🖼️</button><button class="card-dl-btn" onclick="event.stopPropagation();downloadCardJSON('${c.filename}')" title="Download as JSON">{}</button><button class="card-dl-btn" onclick="event.stopPropagation();selectCard('${c.filename}').then(()=>openEditor())" title="Edit character card">✏️</button><button class="card-dl-btn danger" onclick="event.stopPropagation();deleteCard('${c.filename}','${escapeHtml(c.name).replace(/'/g,"\\'")}')" title="Delete character">🗑️</button></div>`;
    div.dataset.filename = c.filename;
    list.appendChild(div);
  });
  // Also load personas
  await loadPersonaList();
}

async function loadPersonaList() {
  const resp = await fetch('/api/personas');
  personasList = await resp.json();
  // Also populate persona editor load select
  const loadSelect = document.getElementById('personaLoadSelect');
  if (loadSelect) {
    loadSelect.innerHTML = '<option value="">— Select to edit —</option>';
    personasList.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.filename;
      opt.textContent = p.name;
      loadSelect.appendChild(opt);
    });
  }
}

async function selectCard(filename) {
  // Library selection: highlight + cache card data (card editor entry point).
  currentFilename = filename;
  document.querySelectorAll('.card-item').forEach(el => {
    el.classList.toggle('active', el.dataset.filename === filename);
  });
  const resp = await fetch('/api/cards/' + filename);
  currentCard = await resp.json();
}
