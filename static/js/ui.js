// KedaiKopi — ui.js (shared UI: editors, themes, backgrounds)
// Shared UI: persona editor, card editor, report, themes, backgrounds, init.

// ─── Chat ───────────────────────────────────────

let _lastUserMsgDiv = null;
let _clientMsgCounter = 0;


// ─── Persona Management ──────────────────────────
function openPersonaEditor() {
  document.getElementById('personaOverlay').classList.add('show');
  // Refresh persona list in the load select
  loadPersonaList();
  updatePersonaPreview();
}

function closePersonaEditor() {
  document.getElementById('personaOverlay').classList.remove('show');
}

function newPersona() {
  personaEditorData = {
    name: '', tags: [],
    description: '', personality: '', scenario: '', first_mes: '', mes_example: '', what_it_tests: ''
  };
  personaEditorFilename = '';
  document.getElementById('personaLoadSelect').value = '';
  fillPersonaForm();
}

function loadPersonaForEdit() {
  const filename = document.getElementById('personaLoadSelect').value;
  if (!filename) return;
  fetch('/api/personas/' + filename).then(r => r.json()).then(p => {
    personaEditorData = p;
    personaEditorFilename = filename;
    fillPersonaForm();
  });
}

function fillPersonaForm() {
  if (!personaEditorData) return;
  const d = personaEditorData;
  document.getElementById('persona_name').value = d.name || '';
  document.getElementById('persona_tags').value = (d.tags || []).join(', ');
  document.getElementById('persona_description').value = d.description || '';
  document.getElementById('persona_personality').value = d.personality || '';
  document.getElementById('persona_scenario').value = d.scenario || '';
  document.getElementById('persona_first_mes').value = d.first_mes || '';
  document.getElementById('persona_mes_example').value = d.mes_example || '';
  document.getElementById('persona_tests').value = d.what_it_tests || '';
  document.getElementById('personaEditorFilename').textContent = personaEditorFilename || '(new)';
  updatePersonaPreview();
}

function collectPersonaData() {
  const name = document.getElementById('persona_name').value.trim();
  const tags = document.getElementById('persona_tags').value.split(',').map(s=>s.trim()).filter(Boolean);
  return {
    name, tags,
    description: document.getElementById('persona_description').value,
    personality: document.getElementById('persona_personality').value,
    scenario: document.getElementById('persona_scenario').value,
    first_mes: document.getElementById('persona_first_mes').value,
    mes_example: document.getElementById('persona_mes_example').value,
    what_it_tests: document.getElementById('persona_tests').value,
  };
}

function updatePersonaPreview() {
  const d = collectPersonaData();
  const preview = document.getElementById('personaPreview');
  if (!d.name) { preview.innerHTML = '<i>Enter a name to see preview...</i>'; return; }
  preview.innerHTML = `<b>${escapeHtml(d.name)}</b><br>${d.tags.join(', ') || '(no tags)'}<br><br>${d.description ? '<b>Description:</b> ' + escapeHtml(d.description.substring(0,200)) + '...' : '<i>(no description)</i>'}`;
}

async function savePersona() {
  const data = collectPersonaData();
  if (!data.name) { alert('Name is required'); return; }
  // Generate filename from name if new
  let filename = personaEditorFilename;
  if (!filename) {
    filename = data.name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') + '.json';
  }
  try {
    const resp = await fetch('/api/personas/' + filename, {
      method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    const result = await resp.json();
    if (result.status === 'saved') {
      personaEditorFilename = filename;
      document.getElementById('personaEditorFilename').textContent = filename;
      await loadPersonaList();
      alert('Persona saved as ' + filename);
    } else {
      alert('Error: ' + (result.error || 'Unknown'));
    }
  } catch(e) { alert('Save error: ' + e.message); }
}

// Auto-update preview on input
document.addEventListener('input', (e) => {
  if (e.target && e.target.id && (e.target.id.startsWith('persona_') || e.target.id.startsWith('trait_') || e.target.id === 'persona_tests')) {
    updatePersonaPreview();
  }
});

// ─── Editor ─────────────────────────────────────
async function openEditor() {
  if (!currentFilename) return;
  const resp = await fetch('/api/cards/' + currentFilename);
  const raw = await resp.json();
  editorOriginal = raw;
  editorVersion = detectCardVersion(raw);
  editorNormalized = normalizeForEditing(raw);
  editorData = raw; // keep for backwards compat
  const badge = document.getElementById('editorVersionBadge');
  badge.textContent = 'V' + editorVersion;
  badge.className = 'version-badge v' + editorVersion;
  document.getElementById('editorFilename').textContent = currentFilename;
  document.getElementById('editorOverlay').classList.add('show');
  renderEditor();
}

function closeEditor() {
  document.getElementById('editorOverlay').classList.remove('show');
}

function switchTab(tab, el) {
  editorTab = tab;
  document.querySelectorAll('.editor-tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  renderEditor();
}

function renderEditor() {
  const d = editorNormalized;
  const body = document.getElementById('editorBody');
  const v3Extra = editorVersion === 3 ? [['nickname','text','Nickname']] : [];
  const fields = {
    core: [...v3Extra, ['name','text','Name'],['description','textarea-large','Description'],['personality','textarea','Personality'],['scenario','textarea','Scenario'],['first_mes','textarea-large','First Message']],
    prompt: [['system_prompt','textarea-large','System Prompt'],['post_history_instructions','textarea-large','Post-History Instructions']],
    persona: [['creator_notes','textarea-large','Creator Notes'],['mes_example','textarea-large','Example Messages']],
    meta: [['creator','text','Creator'],['character_version','text','Version'],['tags','text','Tags (comma-separated)']],
  };

  const currentFields = fields[editorTab] || [];
  body.innerHTML = currentFields.map(f => {
    const [key, type, label] = f;
    const val = d[key] || '';
    const isLarge = type.includes('large');
    const isTextarea = type.startsWith('textarea');
    const isTags = key === 'tags';
    const displayVal = isTags && Array.isArray(val) ? val.join(', ') : val;
    if (isTextarea) {
      return `<div class="editor-field ${isLarge?'large':''}">
        <label>${label}</label>
        <textarea id="edit_${key}">${escapeHtml(displayVal)}</textarea>
        <div class="char-count">${displayVal.length} chars</div>
      </div>`;
    } else {
      return `<div class="editor-field">
        <label>${label}</label>
        <input id="edit_${key}" type="text" value="${escapeHtml(displayVal)}" />
        <div class="char-count">${displayVal.length} chars</div>
      </div>`;
    }
  }).join('');

  // Insert {{char}} name mode selector at the top of core tab (before name field)
  if (editorTab === 'core') {
    const charMode = d['char_name_mode'] || 'full';
    const selectorHtml = `<div class="editor-field" style="flex-direction:row;align-items:center;gap:8px;padding:8px 12px;background:rgba(255,255,255,0.03);border-radius:6px;">
      <label style="margin:0;white-space:nowrap;font-size:13px;">{{char}} resolves to</label>
      <select id="edit_char_name_mode" style="background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:2px 8px;font-size:13px;">
        <option value="full" ${charMode==='full'?'selected':''}>Full name</option>
        <option value="first" ${charMode==='first'?'selected':''}>First name</option>
        <option value="last" ${charMode==='last'?'selected':''}>Last name</option>
      </select>
      <span style="font-size:11px;color:#777;">e.g. Donald Duck &rarr; "Donald" / "Duck" / "Donald Duck"</span>
    </div>`;
    body.innerHTML = selectorHtml + body.innerHTML;
  }

  // Add change listeners
  currentFields.forEach(f => {
    const [key] = f;
    const el = document.getElementById('edit_'+key);
    if (el) {
      el.addEventListener('input', () => {
        let val = el.value;
        if (key === 'tags') val = val.split(',').map(s=>s.trim()).filter(Boolean);
        d[key] = val;
        const count = el.nextElementSibling;
        if (count) count.textContent = (typeof val === 'string' ? val.length : JSON.stringify(val).length) + ' chars';
      });
    }
  });

  // {{char}} name mode selector (core tab only)
  const charModeSelect = document.getElementById('edit_char_name_mode');
  if (charModeSelect) {
    charModeSelect.addEventListener('change', () => {
      d['char_name_mode'] = charModeSelect.value;
    });
  }
}

function importCard() {
  document.getElementById('importCardFile').click();
}

function handleImportFile(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const imported = JSON.parse(e.target.result);
      const version = detectCardVersion(imported);
      editorVersion = version;
      editorOriginal = imported;
      editorNormalized = normalizeForEditing(imported);
      editorData = imported;
      const badge = document.getElementById('editorVersionBadge');
      badge.textContent = 'V' + version;
      badge.className = 'version-badge v' + version;
      renderEditor();
      const name = (imported.data || imported).name || '';
      alert('Imported ' + (name ? '"' + name + '"' : 'card') + ' (V' + version + '). Review and Save to apply.');
    } catch (err) {
      alert('Import failed: ' + err.message);
    }
  };
  reader.readAsText(file);
  event.target.value = ''; // reset so same file can be re-selected
}

async function saveCard() {
  if (!editorNormalized || !currentFilename) return;
  const card = denormalizeForSaving(editorNormalized, editorVersion, editorOriginal);
  try {
    const resp = await fetch('/api/cards/' + currentFilename, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(card)
    });
    const result = await resp.json();
    if (result.status === 'saved') {
      editorOriginal = card;
      editorData = card;
      currentCard = card;
      alert('Card saved!');
    } else {
      alert('Error: ' + (result.error || 'Unknown error'));
    }
  } catch(e) {
    alert('Save error: ' + e.message);
  }
}

async function validateCard() {
  if (!editorNormalized) return;
  const card = denormalizeForSaving(editorNormalized, editorVersion, editorOriginal);
  try {
    const resp = await fetch('/api/cards/' + currentFilename + '/validate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(card)
    });
    const result = await resp.json();
    if (result.valid && (!result.issues || result.issues.length === 0)) {
      alert('✅ Card is valid! No issues found.');
    } else if (result.issues && result.issues.length > 0) {
      let msg = result.issues.map(i => `[${i.severity}] ${i.field}: ${i.message}`).join('\n');
      alert(`Found ${result.issues.length} issue(s):\n\n${msg}`);
    } else {
      alert('✅ Card is valid!');
    }
  } catch(e) {
    alert('Validation error: ' + e.message);
  }
}

// ─── Report ─────────────────────────────────────
function showReport(report) {
  document.getElementById('reportOverlay').classList.add('show');
  const body = document.getElementById('reportBody');
  let html = '';

  if (report.overall_verdict) {
    const cls = report.overall_verdict.includes('pass') ? 'pass' : report.overall_verdict.includes('fail') ? 'fail' : 'partial';
    html += `<div class="verdict ${cls}">${report.overall_verdict.toUpperCase()}</div>`;
  }

  if (report.compliance_score) {
    html += `<div class="report-section"><h3>Compliance</h3><p>${escapeHtml(report.compliance_score)}</p></div>`;
  }

  if (report.phase_results) {
    html += `<div class="report-section"><h3>Phase Results</h3>`;
    for (const [phase, result] of Object.entries(report.phase_results)) {
      html += `<p>• ${phase}: ${escapeHtml(result)}</p>`;
    }
    html += `</div>`;
  }

  if (report.issues_by_severity) {
    html += `<div class="report-section"><h3>Issues</h3>`;
    for (const [sev, issues] of Object.entries(report.issues_by_severity)) {
      if (issues && issues.length > 0) {
        issues.forEach(i => html += `<div class="issue ${sev}">${escapeHtml(i)}</div>`);
      }
    }
    html += `</div>`;
  }

  if (report.recommended_fixes) {
    html += `<div class="report-section"><h3>🔧 Recommended Fixes</h3>`;
    report.recommended_fixes.forEach(f => {
      const pri = f.priority || '·';
      html += `<div class="fix-item">`;
      html += `<div class="fix-issue">⚠ ${escapeHtml(f.issue || '')}</div>`;
      html += `<div><span class="fix-location">📍 ${escapeHtml(f.field||'')} ${escapeHtml(f.location||'')}</span>`;
      html += ` <span class="fix-action">→ ${escapeHtml(f.action || 'add')}</span>`;
      html += ` <span class="fix-priority fix-priority-${pri === 1 ? 'critical' : pri === 2 ? 'high' : pri === 3 ? 'medium' : 'low'}">P${pri}</span></div>`;
      if (f.placement) {
        html += `<div style="font-size:11px;color:var(--orange);margin-top:4px">📌 ${escapeHtml(f.placement)}</div>`;
      }
      html += `<div class="fix-text">${escapeHtml(f.fix || '')}</div>`;
      if (f.suggested_text) {
        html += `<div class="fix-text" style="margin-top:4px;color:var(--text-dim)">${escapeHtml(f.suggested_text)}</div>`;
      }
      html += `</div>`;
    });
    html += `</div>`;
  }

  if (report.enhancement_suggestions && report.enhancement_suggestions.length > 0) {
    html += `<div class="report-section"><h3>💡 Enhancement Suggestions</h3>`;
    report.enhancement_suggestions.forEach(e => {
      html += `<div class="enhancement-item">`;
      html += `<div class="enh-suggestion">${escapeHtml(e.suggestion || '')}</div>`;
      html += `<div class="enh-location">📍 ${escapeHtml(e.field || 'unknown field')}</div>`;
      if (e.placement) {
        html += `<div style="font-size:11px;color:var(--orange);margin-top:2px">📌 ${escapeHtml(e.placement)}</div>`;
      }
      if (e.suggested_text) {
        html += `<div class="fix-text" style="margin-top:4px;color:var(--text-dim)">${escapeHtml(e.suggested_text)}</div>`;
      }
      if (e.rationale) html += `<div class="enh-rationale">${escapeHtml(e.rationale)}</div>`;
      html += `</div>`;
    });
    html += `</div>`;
  }

  if (report.rule_effectiveness) {
    html += `<div class="report-section"><h3>Rule Effectiveness</h3>`;
    report.rule_effectiveness.forEach(r => {
      const color = r.status === 'strong' ? 'var(--green)' : r.status === 'fragile' ? 'var(--yellow)' : 'var(--red)';
      html += `<p><span style="color:${color}">●</span> ${escapeHtml(r.rule)} — ${escapeHtml(r.status)}: ${escapeHtml(r.notes||'')}</p>`;
    });
    html += `</div>`;
  }

  if (report.fragility_summary) {
    html += `<div class="report-section"><h3>Fragility Summary</h3><p>${escapeHtml(report.fragility_summary)}</p></div>`;
  }

  if (report.leakage_summary) {
    html += `<div class="report-section"><h3>Leakage Summary</h3><p>${escapeHtml(report.leakage_summary)}</p></div>`;
  }

  if (report.training_data_conflicts && report.training_data_conflicts.length > 0) {
    html += `<div class="report-section"><h3>Training Data Conflicts</h3>`;
    report.training_data_conflicts.forEach(c => html += `<p>• ${escapeHtml(c)}</p>`);
    html += `</div>`;
  }

  if (report.retest_recommendation) {
    html += `<div class="report-section"><h3>Retest</h3><p>${escapeHtml(report.retest_recommendation)}</p></div>`;
  }

  // Persona used
  if (report.persona_used) {
    html += `<div class="report-section"><h3>Persona Used</h3>`;
    html += `<p><b>${escapeHtml(report.persona_used.name || '')}</b></p>`;
    if (report.persona_used.what_it_tests) {
      html += `<p style="font-size:12px;color:var(--text-dim)">${escapeHtml(report.persona_used.what_it_tests)}</p>`;
    }
    html += `</div>`;
  }

  // Raw stats
  if (report.raw_stats) {
    html += `<div class="report-section"><h3>Raw Stats</h3>`;
    const s = report.raw_stats;
    html += `<p>Messages: ${s.total_messages} | Pass: ${s.passes} | Fail: ${s.fails} | Partial: ${s.partials}</p>`;
    if (s.fragility_distribution) {
      html += `<p>Fragility: Strong=${s.fragility_distribution.strong||0} Fragile=${s.fragility_distribution.fragile||0} Broken=${s.fragility_distribution.broken||0}</p>`;
    }
    if (s.all_banned_words && s.all_banned_words.length > 0) {
      html += `<p>Banned words found: ${s.all_banned_words.length} instances</p>`;
    }
    html += `</div>`;
  }

  body.innerHTML = html || '<p>No report data available.</p>';
}

function closeReport() {
  document.getElementById('reportOverlay').classList.remove('show');
}

// ─── Utils ──────────────────────────────────────
function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Escape HTML first, then apply lightweight markdown:
 *   *text*  → italic
 *   "text"  → bold
 */
function formatMessage(text) {
  if (!text) return '';
  // Extract quoted dialog BEFORE escaping, replace with placeholders
  const dialogs = [];
  // Straight quotes: "text"
  text = text.replace(/"([^"\n]+?)"/g, (m, p1) => { dialogs.push(p1); return `\x00D${dialogs.length - 1}\x00`; });
  // Smart/curly quotes: "text" "text" «text»
  text = text.replace(/[\u201C\u201D\u201E\u201F\u00AB\u00BB]([^\u201C\u201D\u201E\u201F\u00AB\u00BB\n]+?)[\u201C\u201D\u201E\u201F\u00AB\u00BB]/g, (m, p1) => { dialogs.push(p1); return `\x00D${dialogs.length - 1}\x00`; });
  let safe = escapeHtml(text);
  // *text* → <em>text</em>  (non-greedy, no nesting across newlines)
  safe = safe.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
  // Restore dialog placeholders as <strong class="dialog"> (with quotes preserved)
  safe = safe.replace(/\x00D(\d+)\x00/g, (m, i) => `<strong class="dialog">&ldquo;${escapeHtml(dialogs[parseInt(i)])}&rdquo;</strong>`);
  return safe;
}

// ─── Init ───────────────────────────────────────
// ── Theme & Background ───────────────────────────────────────────
const THEMES = {
  midnight: { name:'Midnight', colors:['#0d1117','#58a6ff','#3fb950','#f85149'] },
  dusk:     { name:'Dusk',     colors:['#0d0b10','#c084fc','#7c3aed','#fb7185'] },
  forest:   { name:'Forest',   colors:['#0a0d0b','#34d399','#166534','#f87171'] },
  ember:    { name:'Ember',    colors:['#0d0a08','#f97316','#9a3412','#ef4444'] },
  velvet:   { name:'Velvet',   colors:['#1c0e1e','#a855f7','#f472b6','#fb7185'] },
  abyss:    { name:'Abyss',    colors:['#06121f','#06b6d4','#3b82f6','#22d3ee'] },
  moca:     { name:'Moca',     colors:['#1a120c','#a16207','#d4a574','#e8a87c'] },
  light:    { name:'Light',    colors:['#f5f7fa','#0969da','#1a7f37','#cf222e'] },
};
function applyTheme(name) {
  if (name === 'midnight') {
    document.documentElement.removeAttribute('data-theme');
  } else {
    document.documentElement.setAttribute('data-theme', name);
  }
  localStorage.setItem('cs_theme', name);
  // update swatch selection
  document.querySelectorAll('.theme-swatch').forEach(s => {
    s.classList.toggle('selected', s.dataset.theme === name);
  });
}
function applyBgImage(url, overlay, persistLocal = true) {
  const r = document.documentElement;
  if (url && url.trim()) {
    r.style.setProperty('--bg-image', `url("${url.trim()}")`);
  } else {
    r.style.setProperty('--bg-image', 'none');
  }
  if (overlay != null) {
    r.style.setProperty('--bubble-opacity', String(overlay));
  }
  if (persistLocal) {
    localStorage.setItem('cs_bg_image', url || '');
    localStorage.setItem('cs_bg_overlay', String(overlay ?? 0.85));
  }
}

// ── Background Panel (RP only) ───────────────────────────────────
function getBgList() {
  try { return JSON.parse(localStorage.getItem('cs_bg_list') || '[]'); } catch { return []; }
}
function setBgList(list) {
  localStorage.setItem('cs_bg_list', JSON.stringify(list));
}
function toggleBgPanel() {
  const panel = document.getElementById('bgPanel');
  if (panel) panel.classList.toggle('show');
}
function persistSessionBg(url) {
  // Persist bg to the active RP session via WS
  if (typeof rpWS !== 'undefined' && rpWS.readyState === 1 && rpActiveSessionId) {
    rpWS.send(JSON.stringify({ type: 'set_bg_image', url: url || null }));
  }
}

function renderBgPanel() {
  const grid = document.getElementById('bgPanelGrid');
  if (!grid) return;
  const list = getBgList();
  const activeBg = localStorage.getItem('cs_bg_image') || '';
  grid.innerHTML = '';
  // "None" option
  const noneEl = document.createElement('div');
  noneEl.className = 'bg-thumb-none' + (!activeBg ? ' active' : '');
  noneEl.textContent = 'None';
  noneEl.title = 'No background';
  noneEl.onclick = () => {
    applyBgImage('', null);
    persistSessionBg(null);
    renderBgPanel();
  };
  grid.appendChild(noneEl);
  // Thumbnails
  list.forEach((url, i) => {
    const el = document.createElement('div');
    el.className = 'bg-thumb' + (activeBg === url ? ' active' : '');
    el.style.backgroundImage = `url("${url}")`;
    el.title = 'Click to apply';
    el.onclick = () => {
      applyBgImage(url, null);
      persistSessionBg(url);
      renderBgPanel();
    };
    const rm = document.createElement('button');
    rm.className = 'bg-thumb-remove';
    rm.textContent = '✕';
    rm.title = 'Remove';
    rm.onclick = (e) => { e.stopPropagation(); removeBgImage(i); };
    el.appendChild(rm);
    grid.appendChild(el);
  });
}
function addBgFromUpload(file) {
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) { alert('Image too large (max 10MB).'); return; }
  const formData = new FormData();
  formData.append('file', file);
  fetch('/api/bg-upload', { method: 'POST', body: formData })
    .then(r => r.json())
    .then(data => {
      if (data.error) { alert(data.error); return; }
      const list = getBgList();
      list.push(data.url);
      setBgList(list);
      applyBgImage(data.url, null);
      persistSessionBg(data.url);
      renderBgPanel();
    })
    .catch(err => alert('Upload failed: ' + err.message));
}
function addBgFromUrl() {
  const input = document.getElementById('bgPanelUrl');
  if (!input || !input.value.trim()) return;
  const url = input.value.trim();
  const list = getBgList();
  list.push(url);
  setBgList(list);
  applyBgImage(url, null);
  persistSessionBg(url);
  input.value = '';
  renderBgPanel();
}
function removeBgImage(index) {
  const list = getBgList();
  const removed = list.splice(index, 1)[0];
  setBgList(list);
  // If active bg was removed, clear it
  if (localStorage.getItem('cs_bg_image') === removed) {
    applyBgImage('', null);
    persistSessionBg(null);
  }
  // Delete server-uploaded files from disk (skip data URLs and external URLs)
  if (removed && removed.startsWith('/api/bg/')) {
    const filename = removed.split('/api/bg/')[1];
    if (filename) fetch('/api/bg/' + encodeURIComponent(filename), { method: 'DELETE' }).catch(() => {});
  }
  renderBgPanel();
}
function buildThemeSwatches() {
  const container = document.getElementById('themeSwatches');
  if (!container) return;
  container.innerHTML = '';
  for (const [key, t] of Object.entries(THEMES)) {
    const sw = document.createElement('div');
    sw.className = 'theme-swatch';
    sw.dataset.theme = key;
    sw.title = t.name;
    sw.style.cssText = 'display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:8px;border:2px solid var(--border);cursor:pointer;transition:border-color 0.15s,transform 0.1s';
    sw.onmouseenter = () => sw.style.transform = 'scale(1.05)';
    sw.onmouseleave = () => sw.style.transform = 'scale(1)';
    for (const c of t.colors) {
      const dot = document.createElement('span');
      dot.style.cssText = `width:14px;height:14px;border-radius:50%;background:${c};border:1px solid rgba(255,255,255,0.15)`;
      sw.appendChild(dot);
    }
    const label = document.createElement('span');
    label.textContent = t.name;
    label.style.cssText = 'font-size:12px;color:var(--text-dim)';
    sw.appendChild(label);
    sw.onclick = () => applyTheme(key);
    container.appendChild(sw);
  }
  // selected style
  const style = document.createElement('style');
  style.textContent = '.theme-swatch.selected { border-color:var(--accent) !important; } .theme-swatch:hover { border-color:var(--text-dim) !important; }';
  container.appendChild(style);
}
// Load saved appearance on boot
(function initAppearance() {
  const savedTheme = localStorage.getItem('cs_theme') || 'midnight';
  const savedBg = localStorage.getItem('cs_bg_image') || '';
  const savedOverlay = parseFloat(localStorage.getItem('cs_bg_overlay')) ?? 0.85;
  // apply immediately (before DOM is fully ready, CSS vars on :root work)
  applyTheme(savedTheme);
  applyBgImage(savedBg, savedOverlay);
  // populate settings when DOM is ready
  document.addEventListener('DOMContentLoaded', () => {
    buildThemeSwatches();
    applyTheme(savedTheme); // update swatch selection
    renderBgPanel();
    const ovInput = document.getElementById('cfgBgOverlay');
    const ovVal = document.getElementById('bgOverlayVal');
    if (ovInput) ovInput.value = savedOverlay;
    if (ovVal) ovVal.textContent = savedOverlay;
    initConsoleLimit();
  });
})();
// Live-apply appearance settings from Settings modal (called on input change)
function liveApplyAppearance() {
  const url = localStorage.getItem('cs_bg_image') || '';
  const overlay = parseFloat(document.getElementById('cfgBgOverlay')?.value) ?? 0.55;
  applyBgImage(url, overlay);
}

// Boot calls moved to end of imagegen.js (last script) for correct load order

