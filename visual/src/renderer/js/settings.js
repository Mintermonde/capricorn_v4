'use strict';

const DEFAULT_CAPRI_PERSONA = `Ты разговариваешь с пользователем как живая собеседница и напарница, которая живёт в его компьютере. Тебя зовут Капри.
Манера общения: естественно, с лёгкой дерзостью и дружеской иронией, без грубости. Отвечай кратко и по делу (1-2 ёмкие фразы), без списков и «воды». В играх реагируй мгновенно и чётко. О себе говоришь только «я».`;


// Capri Settings Controller (v4.0 Ultimate Edition)

let state = {
  visual: {},
  backend: {},
  games: { auto_detect: true, active_game: 'war_thunder', games: {} }
};

let selectedGameId = 'war_thunder';
let isEditingGameDraft = false;
let allMacrosExpanded = true;
let recordedKeyResult = null;
let recordingCallback = null;
let cachedActionGroups = []; // Array of { id, phrases: string[], action: any, expanded: boolean }
let windowSelectTarget = 'game'; // 'game' | 'new_game_modal' | 'hub_quick'

// DirectInput Key Mapping Reference
const DI_KEYS = [
  'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm',
  'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z',
  '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
  'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
  'alt', 'ctrl', 'shift', 'space', 'enter', 'tab', 'escape', 'backspace', 'delete',
  'up', 'down', 'left', 'right',
  'mouse1', 'mouse2', 'mouse3', 'mouse4', 'mouse5'
];

document.addEventListener('DOMContentLoaded', async () => {
  setupNavigation();
  setupWindowControls();
  setupEventListeners();
  await loadData();
});

// ============================================================================
// 1. NAVIGATION & WINDOW CONTROLS
// ============================================================================
function setupNavigation() {
  const tabs = document.querySelectorAll('.nav-tab');
  const panes = document.querySelectorAll('.tab-pane');

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((t) => t.classList.remove('active'));
      panes.forEach((p) => p.classList.remove('active'));

      tab.classList.add('active');
      const targetId = tab.dataset.tab;
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add('active');

      // When navigating to Games tab, default to Hub view if not actively editing
      if (targetId === 'tab-games') {
        const hub = document.getElementById('game-view-hub');
        const editor = document.getElementById('game-view-editor');
        if (hub && editor && editor.classList.contains('hidden')) {
          populateGamesHub();
        }
      }
    });
  });
}

function setupWindowControls() {
  document.getElementById('btn-minimize')?.addEventListener('click', () => {
    window.host?.minimizeSettings?.();
  });

  const maxBtn = document.getElementById('btn-maximize');
  const updateMaxState = (isMax) => {
    document.body.classList.toggle('maximized', Boolean(isMax));
    if (maxBtn) {
      maxBtn.textContent = isMax ? '🗗' : '🗖';
      maxBtn.title = isMax ? 'Восстановить' : 'Развернуть';
    }
  };

  maxBtn?.addEventListener('click', async () => {
    const isMax = await window.host?.toggleMaximizeSettings?.();
    updateMaxState(isMax);
  });

  // Double click header to maximize / restore
  document.querySelector('.settings-header')?.addEventListener('dblclick', async (e) => {
    if (e.target.closest('.window-controls') || e.target.closest('button')) return;
    const isMax = await window.host?.toggleMaximizeSettings?.();
    updateMaxState(isMax);
  });

  window.host?.onSettingsMaximizeChange?.((isMax) => {
    updateMaxState(isMax);
  });

  document.getElementById('btn-close')?.addEventListener('click', () => {
    window.host?.closeSettings?.();
  });

  document.getElementById('btn-cancel')?.addEventListener('click', () => {
    window.host?.closeSettings?.();
  });
}

// ============================================================================
// 2. DATA LOADING & POPULATION
// ============================================================================
async function loadData() {
  try {
    const loaded = await window.host?.loadAllSettings?.();
    if (loaded) {
      state.visual = loaded.visual || {};
      state.backend = loaded.backend || {};
      state.games = loaded.games || { auto_detect: true, games: {} };
    }
  } catch (err) {
    console.warn('[capri-settings] Could not load settings via host:', err);
  }

  // Apply Theme early (dark | pastel | light)
  const currentTheme = state.visual.theme || 'dark';
  document.documentElement.setAttribute('data-theme', currentTheme);

  populatePersonalization();
  await populateSoundAndMic();
  populateAI();
  initGamesData();
  populateGamesHub();
  populateAppsAndSites();
  populateSystem();
}

// 2.1 Personalization
function populatePersonalization() {
  const v = state.visual;
  const currentTheme = v.theme || 'dark';
  setVal('cfg-theme', currentTheme);
  document.documentElement.setAttribute('data-theme', currentTheme);

  setVal('cfg-userName', v.userName || '');
  setVal('cfg-persona', v.persona || DEFAULT_CAPRI_PERSONA);
  setVal('cfg-rest', v.rest || 'taskbar');
  setVal('cfg-motion', v.motion || 'auto');

  setChecked('cfg-wander', v.wander !== false);
  setChecked('cfg-possess', v.possess !== false);
  setChecked('cfg-jealous', v.jealous !== false);
  setChecked('cfg-pcReact', v.pcReact !== false);
  setChecked('cfg-startup', Boolean(v.startup));

  // Live Theme Switcher
  const themeSelect = document.getElementById('cfg-theme');
  if (themeSelect) {
    themeSelect.onchange = (e) => {
      const theme = e.target.value;
      document.documentElement.setAttribute('data-theme', theme);
      state.visual.theme = theme;
    };
  }
}

// 2.2 Sound and Mic
async function populateSoundAndMic() {
  const v = state.visual;
  const b = state.backend;

  const vol = typeof v.volume === 'number' ? Math.round(v.volume * 100) : 70;
  const rangeEl = document.getElementById('cfg-volume');
  const valEl = document.getElementById('volume-val');
  if (rangeEl && valEl) {
    rangeEl.value = vol;
    valEl.textContent = `${vol}%`;
    rangeEl.oninput = () => { valEl.textContent = `${rangeEl.value}%`; };
  }

  setChecked('cfg-muted', Boolean(v.muted));
  setChecked('cfg-bargeIn', b.barge_in !== false);

  await populateMics();

  const wakeWords = Array.isArray(b.wake_words) ? b.wake_words : ['капри', 'capri', 'капли'];
  renderWakeWords(wakeWords);
}

async function populateMics() {
  const select = document.getElementById('cfg-mic');
  if (!select) return;
  select.innerHTML = '<option value="">По умолчанию (Default System Mic)</option>';

  const current = state.backend.mic_device || '';
  try {
    const devices = await navigator.mediaDevices?.enumerateDevices?.();
    if (devices) {
      const audioIns = devices.filter((d) => d.kind === 'audioinput');
      audioIns.forEach((d) => {
        const label = d.label || `Микрофон ${d.deviceId.slice(0, 5)}`;
        const opt = document.createElement('option');
        opt.value = label;
        opt.textContent = label;
        if (current && (label.includes(current) || current.includes(label))) {
          opt.selected = true;
        }
        select.appendChild(opt);
      });
    }
  } catch {}

  if (current && !Array.from(select.options).some((o) => o.value === current)) {
    const opt = document.createElement('option');
    opt.value = current;
    opt.textContent = current;
    opt.selected = true;
    select.appendChild(opt);
  }
}

function renderWakeWords(words) {
  const container = document.getElementById('wake-words-list');
  if (!container) return;
  container.innerHTML = '';

  words.forEach((w, idx) => {
    const chip = document.createElement('div');
    chip.className = 'phrase-chip';
    chip.innerHTML = `<span>${escapeHtml(w)}</span><span class="phrase-chip-del" data-idx="${idx}">&times;</span>`;
    container.appendChild(chip);
  });

  container.querySelectorAll('.phrase-chip-del').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      const idx = Number(e.target.dataset.idx);
      const list = getWakeWords();
      list.splice(idx, 1);
      renderWakeWords(list);
    });
  });
}

function getWakeWords() {
  const container = document.getElementById('wake-words-list');
  if (!container) return [];
  return Array.from(container.querySelectorAll('.phrase-chip span:first-child'))
    .map((el) => el.textContent.trim())
    .filter(Boolean);
}

// AI Provider Presets and Configuration
const PROVIDER_PRESETS = {
  gemini: {
    name: 'Google Gemini',
    keyPlaceholder: 'AQ.Ab8...',
    urlPlaceholder: 'https://your-worker.workers.dev/v1beta/openai (или оставьте пустым)',
    urlHint: 'Cloudflare Worker или прокси для прямого доступа без VPN из РФ. При прямом доступе оставьте пустым.',
    models: [
      { id: 'gemini-3.6-flash', label: 'gemini-3.6-flash (Рекомендуется — Флагманский баланс)' },
      { id: 'gemini-3.5-flash-lite', label: 'gemini-3.5-flash-lite (Сверхбыстрая и экономичная)' },
      { id: 'gemini-3.7-flash', label: 'gemini-3.7-flash (Новейшая модель Gemini 3.7)' },
      { id: 'gemini-2.5-flash', label: 'gemini-2.5-flash' },
      { id: 'gemini-2.5-pro', label: 'gemini-2.5-pro' },
      { id: 'gemini-1.5-flash', label: 'gemini-1.5-flash' },
      { id: 'gemini-1.5-pro', label: 'gemini-1.5-pro' },
      { id: 'custom', label: 'Ввести другую модель вручную...' }
    ],
    defaultModel: 'gemini-3.6-flash'
  },
  anthropic: {
    name: 'Anthropic Claude',
    keyPlaceholder: 'sk-ant-api03-...',
    urlPlaceholder: 'Официальный API Anthropic (прямой доступ)',
    urlHint: 'Для работы требуется ключ Anthropic API Console.',
    models: [
      { id: 'claude-3-7-sonnet-latest', label: 'claude-3-7-sonnet-latest (Флагман 2026)' },
      { id: 'claude-3-5-sonnet-latest', label: 'claude-3-5-sonnet-latest (Интеллект и зрение)' },
      { id: 'claude-3-5-haiku-latest', label: 'claude-3-5-haiku-latest (Быстрый отклик)' },
      { id: 'claude-opus-5-5', label: 'claude-opus-5-5' },
      { id: 'custom', label: 'Ввести другую модель вручную...' }
    ],
    defaultModel: 'claude-3-5-haiku-latest'
  },
  openai: {
    name: 'OpenAI (ChatGPT)',
    keyPlaceholder: 'sk-proj-...',
    urlPlaceholder: 'https://api.openai.com/v1 (или ваш прокси)',
    urlHint: 'Официальный API OpenAI или совместимый реверс-прокси.',
    models: [
      { id: 'gpt-4o', label: 'gpt-4o (Флагманская мультимодальная модель)' },
      { id: 'gpt-4o-mini', label: 'gpt-4o-mini (Быстрая и недорогая)' },
      { id: 'o3-mini', label: 'o3-mini (Продвинутая модель с рассуждениями)' },
      { id: 'o1', label: 'o1' },
      { id: 'custom', label: 'Ввести другую модель вручную...' }
    ],
    defaultModel: 'gpt-4o-mini'
  },
  deepseek: {
    name: 'DeepSeek',
    keyPlaceholder: 'sk-...',
    urlPlaceholder: 'https://api.deepseek.com/v1',
    urlHint: 'Официальный эндпоинт DeepSeek Open Platform.',
    models: [
      { id: 'deepseek-chat', label: 'deepseek-chat (DeepSeek V3)' },
      { id: 'deepseek-reasoner', label: 'deepseek-reasoner (DeepSeek R1)' },
      { id: 'custom', label: 'Ввести другую модель вручную...' }
    ],
    defaultModel: 'deepseek-chat'
  },
  groq: {
    name: 'Groq',
    keyPlaceholder: 'gsk_...',
    urlPlaceholder: 'https://api.groq.com/openai/v1',
    urlHint: 'Сверхбыстрый чип LPU с задержкой ответа менее 0.3 сек.',
    models: [
      { id: 'llama-3.3-70b-versatile', label: 'llama-3.3-70b-versatile (Рекомендуется)' },
      { id: 'mixtral-8x7b-32768', label: 'mixtral-8x7b-32768' },
      { id: 'custom', label: 'Ввести другую модель вручную...' }
    ],
    defaultModel: 'llama-3.3-70b-versatile'
  },
  mistral: {
    name: 'Mistral AI',
    keyPlaceholder: '...',
    urlPlaceholder: 'https://api.mistral.ai/v1',
    urlHint: 'Европейские открытые и закрытые модели Mistral.',
    models: [
      { id: 'mistral-large-latest', label: 'mistral-large-latest' },
      { id: 'codestral-latest', label: 'codestral-latest' },
      { id: 'custom', label: 'Ввести другую модель вручную...' }
    ],
    defaultModel: 'mistral-large-latest'
  },
  openrouter: {
    name: 'OpenRouter',
    keyPlaceholder: 'sk-or-v1-...',
    urlPlaceholder: 'https://openrouter.ai/api/v1',
    urlHint: 'Единый шлюз ко всем моделям: Claude, GPT-4o, Llama, Gemini и др.',
    models: [
      { id: 'google/gemini-2.0-flash-001', label: 'google/gemini-2.0-flash-001' },
      { id: 'anthropic/claude-3.5-haiku', label: 'anthropic/claude-3.5-haiku' },
      { id: 'meta-llama/llama-3.3-70b-instruct', label: 'meta-llama/llama-3.3-70b-instruct' },
      { id: 'deepseek/deepseek-chat', label: 'deepseek/deepseek-chat' },
      { id: 'custom', label: 'Ввести другую модель вручную...' }
    ],
    defaultModel: 'google/gemini-2.0-flash-001'
  },
  ollama: {
    name: 'Ollama (Локально)',
    keyPlaceholder: 'Ключ не требуется (локальный сервер)',
    urlPlaceholder: 'http://127.0.0.1:11434',
    urlHint: 'Работает полностью локально на вашей видеокарте без интернета.',
    models: [
      { id: 'qwen2.5vl:3b', label: 'qwen2.5vl:3b (Рекомендуется — распознавание экрана)' },
      { id: 'qwen3:8b', label: 'qwen3:8b' },
      { id: 'llama3.2', label: 'llama3.2' },
      { id: 'deepseek-r1:8b', label: 'deepseek-r1:8b' },
      { id: 'mistral', label: 'mistral' },
      { id: 'custom', label: 'Ввести другое имя модели...' }
    ],
    defaultModel: 'qwen2.5vl:3b'
  },
  custom: {
    name: 'Пользовательский сервер',
    keyPlaceholder: 'sk-... (если требуется)',
    urlPlaceholder: 'http://127.0.0.1:1234/v1 (LM Studio, vLLM, прокси)',
    urlHint: 'Любой OpenAI-совместимый эндпоинт (LocalAI, Text-Gen-WebUI, LM Studio).',
    models: [
      { id: 'custom', label: 'Ввести имя модели...' }
    ],
    defaultModel: 'custom'
  }
};

// 2.3 AI Settings
function populateAI() {
  const b = state.backend;
  const v = state.visual;

  const prov = b.ai_provider || v.provider || 'gemini';
  setVal('cfg-aiProvider', prov);

  const currentModel = b.model || (prov === 'ollama' ? b.local_model : v.chatModel) || '';
  const currentKey = b.gemini_api_key || b.anthropic_api_key || v.apiKeys?.[prov] || '';
  const currentUrl = v.geminiUrl || v.customUrl || b.gemini_base_url || '';

  renderAIProviderUI(prov, currentModel, currentKey, currentUrl);

  setChecked('cfg-chatter', b.chatter !== false);
  setVal('cfg-chatterMin', b.chatter_min_minutes || 15);
  setVal('cfg-chatterMax', b.chatter_max_minutes || 40);
}

function renderAIProviderUI(prov, currentModel, currentKey, currentUrl) {
  const preset = PROVIDER_PRESETS[prov] || PROVIDER_PRESETS.gemini;

  // Key
  const keyGroup = document.getElementById('group-ai-key');
  const keyInput = document.getElementById('cfg-aiKey');
  const keyHint = document.getElementById('hint-ai-key');
  if (keyGroup) keyGroup.style.display = (prov === 'ollama') ? 'none' : 'block';
  if (keyInput) {
    if (currentKey !== undefined) keyInput.value = currentKey;
    keyInput.placeholder = preset.keyPlaceholder || 'Введите API ключ...';
  }
  if (keyHint) keyHint.textContent = (prov === 'ollama') ? 'Локальная Ollama не требует API ключа.' : 'Ключ безопасно хранится на вашем компьютере.';

  // Models
  const modelSelect = document.getElementById('cfg-aiModel');
  const customInput = document.getElementById('cfg-aiModelCustom');
  const modelHint = document.getElementById('hint-ai-model');

  if (modelSelect) {
    modelSelect.innerHTML = '';
    preset.models.forEach((m) => {
      const opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = m.label;
      modelSelect.appendChild(opt);
    });

    const activeModel = currentModel || preset.defaultModel;
    const hasInList = preset.models.some((m) => m.id === activeModel);
    if (hasInList && activeModel !== 'custom') {
      modelSelect.value = activeModel;
      if (customInput) customInput.classList.add('hidden');
    } else {
      modelSelect.value = 'custom';
      if (customInput) {
        customInput.classList.remove('hidden');
        customInput.value = activeModel === 'custom' ? '' : activeModel;
      }
    }
  }

  if (modelHint) {
    modelHint.textContent = `Выбрано для ${preset.name}. ${prov === 'gemini' ? 'Поддерживает анализ экрана и диалоги.' : ''}`;
  }

  // URL / Proxy
  const urlInput = document.getElementById('cfg-aiUrl');
  const urlHint = document.getElementById('hint-ai-url');
  if (urlInput) {
    if (currentUrl !== undefined) urlInput.value = currentUrl;
    urlInput.placeholder = preset.urlPlaceholder || '';
  }
  if (urlHint) {
    urlHint.textContent = preset.urlHint || '';
  }
}

function getSelectedAIModel() {
  const modelSelect = document.getElementById('cfg-aiModel');
  const customInput = document.getElementById('cfg-aiModelCustom');
  if (!modelSelect) return 'gemini-3.6-flash';
  if (modelSelect.value === 'custom') {
    return (customInput?.value || '').trim() || 'gemini-3.6-flash';
  }
  return modelSelect.value;
}

// ============================================================================
// 3. GAME MODE HUB & BUILDER
// ============================================================================
function initGamesData() {
  const gConfig = state.games;
  if (!gConfig.games || typeof gConfig.games !== 'object') {
    gConfig.games = {};
  }

  // Fallback defaults for War Thunder if missing or empty
  const wt = gConfig.games['war_thunder'];
  if (!wt || !wt.bindings || Object.keys(wt.bindings).length === 0) {
    gConfig.games['war_thunder'] = {
      name: 'War Thunder',
      processes: ['aces.exe', 'aces_BE.exe', 'aces'],
      focus_mode: 'foreground',
      enabled: true,
      bindings: {
        'лтц': ['mouse4'],
        'выпусти лтц': ['mouse4'],
        'выпустить лтц': ['mouse4'],
        'сбрось лтц': ['mouse4'],
        'сбросить лтц': ['mouse4'],
        'отстрели лтц': ['mouse4'],
        'отстрелить лтц': ['mouse4'],
        'дай лтц': ['mouse4'],
        'сброс лтц': ['mouse4'],
        'сбросить лтц': ['mouse4'],
        'пуск лтц': ['mouse4'],
        'диполи': ['mouse4'],
        'выпусти диполи': ['mouse4'],
        'сбрось диполи': ['mouse4'],
        'отстрели диполи': ['mouse4'],
        'режим захвата': [['alt', 'a'], 0.08, ['alt', 'w']],
        'включи режим захвата': [['alt', 'a'], 0.08, ['alt', 'w']],
        'включить режим захвата': [['alt', 'a'], 0.08, ['alt', 'w']],
        'захват цели': [['alt', 'a'], 0.08, ['alt', 'w']],
        'захват': [['alt', 'a'], 0.08, ['alt', 'w']],
        'радарный захват': [['alt', 'a'], 0.08, ['alt', 'w']],
        'парл на ик': ['alt', 'w'],
        'с парл на ик': ['alt', 'w'],
        'ик на парл': ['alt', 'w'],
        'с ик на парл': ['alt', 'w'],
        'смени ракету': ['alt', 'w'],
        'сменить ракету': ['alt', 'w'],
        'переключение рлс-олс': [['alt', 'a']],
        'радар': [['alt', 'r']],
        'захват цели рлс': [['alt', 'f']]
      }
    };
  }

  if (!state.games.games[selectedGameId]) {
    selectedGameId = Object.keys(state.games.games)[0] || 'war_thunder';
  }
}

function getMonogram(name) {
  if (!name) return 'GP';
  const parts = name.trim().split(/[\s_\-]+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

function populateGamesHub(filterQuery = '') {
  const grid = document.getElementById('games-grid');
  const counter = document.getElementById('hub-games-counter');
  const badge = document.getElementById('game-tab-badge');
  if (!grid) return;

  grid.innerHTML = '';
  const gamesObj = state.games.games || {};
  const gameEntries = Object.entries(gamesObj);

  const totalGames = gameEntries.length;
  if (badge) badge.textContent = String(totalGames);

  const query = (filterQuery || '').trim().toLowerCase();
  const filtered = gameEntries.filter(([gid, gdata]) => {
    if (!query) return true;
    const name = (gdata.name || gid).toLowerCase();
    const proc = ((gdata.processes || [])[0] || '').toLowerCase();
    return name.includes(query) || proc.includes(query) || gid.toLowerCase().includes(query);
  });

  if (counter) {
    counter.textContent = query ? `${filtered.length} из ${totalGames}` : String(totalGames);
  }

  if (filtered.length === 0) {
    grid.innerHTML = `
      <div style="grid-column: 1 / -1; color:var(--text-muted); padding:36px 16px; text-align:center; background:rgba(0,0,0,0.2); border-radius:8px;">
        ${query ? `Ничего не найдено по запросу «${escapeHtml(query)}».` : 'Список игр пуст. Добавьте первую игру через панель добавления выше!'}
      </div>
    `;
    return;
  }

  const frag = document.createDocumentFragment();
  filtered.forEach(([gid, gdata]) => {
    const tile = document.createElement('div');
    tile.className = 'game-tile';
    tile.dataset.gid = gid;

    const monogram = getMonogram(gdata.name || gid);
    const proc = (gdata.processes || [])[0] || 'Процесс не указан';
    const isEnabled = gdata.enabled !== false;

    // Calculate macro count & total phrases
    const bindings = gdata.bindings || {};
    const groups = groupBindings(bindings);
    const macroCount = groups.length;
    let phraseCount = 0;
    groups.forEach((g) => { phraseCount += g.phrases.length; });

    tile.innerHTML = `
      <div class="game-tile-top">
        <div class="game-tile-monogram">${gdata.icon ? `<img src="${escapeHtml(gdata.icon)}" class="game-hub-icon-img" alt="" />` : escapeHtml(monogram)}</div>
        <div class="game-tile-info">
          <div class="game-tile-name" title="${escapeHtml(gdata.name || gid)}">${escapeHtml(gdata.name || gid)}</div>
          <div class="game-tile-proc">${escapeHtml(proc)}</div>
        </div>
        <span class="badge-status-chip ${isEnabled ? 'active' : 'disabled'}">
          ${isEnabled ? 'Активен' : 'Отключен'}
        </span>
      </div>
      <div class="game-tile-stats">
        <span class="game-tile-count">${macroCount} ${pluralize(macroCount, 'макрос', 'макроса', 'макросов')} (${phraseCount} ${pluralize(phraseCount, 'фраза', 'фразы', 'фраз')})</span>
        <button class="btn btn-small btn-secondary btn-tune-game">Настроить →</button>
      </div>
    `;

    // Click on tile or "Настроить" button opens detail editor
    tile.addEventListener('click', () => {
      openGameEditor(gid);
    });

    frag.appendChild(tile);
  });

  grid.appendChild(frag);
}

function openGameEditor(gid) {
  // If we were already editing a different game in editor, save its draft
  if (isEditingGameDraft && selectedGameId && selectedGameId !== gid) {
    saveCurrentGameDraft();
  }

  selectedGameId = gid;
  isEditingGameDraft = true;

  const hubView = document.getElementById('game-view-hub');
  const editorView = document.getElementById('game-view-editor');
  if (hubView && editorView) {
    hubView.classList.add('hidden');
    editorView.classList.remove('hidden');
  }

  renderSelectedGame();
}

function closeGameEditorToHub() {
  if (isEditingGameDraft) {
    saveCurrentGameDraft();
    isEditingGameDraft = false;
  }

  const hubView = document.getElementById('game-view-hub');
  const editorView = document.getElementById('game-view-editor');
  if (hubView && editorView) {
    editorView.classList.add('hidden');
    hubView.classList.remove('hidden');
  }

  populateGamesHub();
}

function updateEditorGameMonogram(gdata) {
  const monogramEl = document.getElementById('editor-game-monogram');
  const resetBtn = document.getElementById('btn-reset-game-icon');
  if (!monogramEl) return;

  const monogram = getMonogram(gdata.name || selectedGameId);
  if (gdata.icon) {
    monogramEl.innerHTML = `<img src="${escapeHtml(gdata.icon)}" class="game-hub-icon-img" alt="" />`;
    monogramEl.classList.add('has-custom-img');
    if (resetBtn) resetBtn.classList.remove('hidden');
  } else {
    monogramEl.textContent = monogram;
    monogramEl.classList.remove('has-custom-img');
    if (resetBtn) resetBtn.classList.add('hidden');
  }
}

function renderSelectedGame() {
  const gamesObj = state.games.games || {};
  const gdata = gamesObj[selectedGameId];
  if (!gdata) return;

  updateEditorGameMonogram(gdata);
  const titleEl = document.getElementById('editor-game-title');
  const statusEl = document.getElementById('editor-game-status');

  if (titleEl) titleEl.textContent = gdata.name || selectedGameId;
  if (statusEl) {
    const isAct = gdata.enabled !== false;
    statusEl.className = `badge-status-chip ${isAct ? 'active' : 'disabled'}`;
    statusEl.textContent = isAct ? 'Активен' : 'Отключен';
  }

  setVal('game-name', gdata.name || selectedGameId);
  setVal('game-process', (gdata.processes || [])[0] || '');
  setVal('game-focus-mode', gdata.focus_mode || 'foreground');
  setChecked('game-enabled', gdata.enabled !== false);

  // Group raw bindings into Action Groups
  cachedActionGroups = groupBindings(gdata.bindings || {});
  filterAndRenderCommands();
}

function groupBindings(bindings) {
  const groups = [];

  Object.entries(bindings).forEach(([phrase, action]) => {
    const actionKey = JSON.stringify(action);
    const existing = groups.find((g) => JSON.stringify(g.action) === actionKey);
    if (existing) {
      if (!existing.phrases.includes(phrase)) existing.phrases.push(phrase);
    } else {
      groups.push({
        id: 'cmd_' + Math.random().toString(36).slice(2, 9),
        phrases: [phrase],
        action: action,
        expanded: false
      });
    }
  });

  return groups;
}

function filterAndRenderCommands() {
  const container = document.getElementById('commands-list');
  const searchInput = document.getElementById('search-game-commands');
  const countLabel = document.getElementById('commands-count-label');
  if (!container) return;

  const query = (searchInput?.value || '').trim().toLowerCase();
  container.innerHTML = '';

  const totalGroups = cachedActionGroups.length;
  let totalPhrases = 0;
  cachedActionGroups.forEach((g) => { totalPhrases += g.phrases.length; });

  const filtered = cachedActionGroups.filter((group) => {
    if (!query) return true;
    const matchPhrase = group.phrases.some((p) => p.toLowerCase().includes(query));
    const matchAction = JSON.stringify(group.action).toLowerCase().includes(query);
    return matchPhrase || matchAction;
  });

  if (countLabel) {
    if (query) {
      countLabel.textContent = `Найдено: ${filtered.length} из ${totalGroups} макросов`;
    } else {
      countLabel.textContent = `${totalGroups} макросов (${totalPhrases} фраз)`;
    }
  }

  if (filtered.length === 0) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1; color:var(--text-muted); padding:32px 16px; text-align:center; background:rgba(0,0,0,0.2); border-radius:8px;">
        ${query ? `Ничего не найдено по запросу «${escapeHtml(query)}».` : 'В этом профиле игры пока нет макросов. Нажмите «+ Создать макрос» выше!'}
      </div>
    `;
    return;
  }

  const frag = document.createDocumentFragment();
  filtered.forEach((group) => {
    const card = renderMacroCard(group);
    frag.appendChild(card);
  });
  container.appendChild(frag);
}

function renderMacroCard(group) {
  const card = document.createElement('div');
  card.className = 'action-card command-card';
  card.id = group.id;

  const mainTitle = group.phrases[0] || 'Новый макрос';
  const phrasesCount = group.phrases.length;

  card.innerHTML = `
    <div class="action-card-header cmd-top-bar">
      <div class="action-card-title cmd-title-zone">
        <span class="cmd-main-phrase">${escapeHtml(mainTitle)}</span>
        <span class="action-phrases-count cmd-phrases-count">${phrasesCount} ${pluralize(phrasesCount, 'фраза', 'фразы', 'фраз')}</span>
      </div>
      <div class="action-card-btns cmd-header-actions">
        <button class="btn btn-small btn-secondary btn-quick-rec" title="Запись действия">Запись</button>
        <button class="btn-card-del btn-del-group" title="Удалить макрос">&times;</button>
      </div>
    </div>

    <!-- Action Sequence Timeline -->
    <div class="action-timeline action-sequence-box action-timeline-row"></div>

    <!-- Synonyms / Voice Trigger Phrases Section -->
    <div class="action-phrases-area phrases-section">
      <div class="phrases-chip-list"></div>
      <div class="add-phrase-inline">
        <input type="text" class="input-text input-add-phrase" placeholder="+ синоним (Enter)" />
      </div>
    </div>
  `;

  // Render Action Chain Steps directly into .action-timeline
  const timelineRow = card.querySelector('.action-timeline');
  renderTimelineSteps(timelineRow, group);

  // Render Trigger Phrases Chips
  const chipsList = card.querySelector('.phrases-chip-list');
  renderPhraseChips(chipsList, group);

  // Add Phrase Input
  const phraseInput = card.querySelector('.input-add-phrase');
  phraseInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const val = phraseInput.value.trim().toLowerCase();
      if (val && !group.phrases.includes(val)) {
        group.phrases.push(val);
        phraseInput.value = '';
        renderPhraseChips(chipsList, group);
        const titleEl = card.querySelector('.cmd-main-phrase');
        if (titleEl) titleEl.textContent = group.phrases[0] || 'Новый макрос';
        const countEl = card.querySelector('.action-phrases-count, .cmd-phrases-count');
        if (countEl) countEl.textContent = `${group.phrases.length} ${pluralize(group.phrases.length, 'фраза', 'фразы', 'фраз')}`;
      }
    }
  });

  // Quick Record Macro Button
  const recBtn = card.querySelector('.btn-quick-rec');
  if (recBtn) {
    recBtn.addEventListener('click', () => {
      openKeyRecorder((res) => {
        if (res) {
          group.action = Array.isArray(res) ? res : [res];
          renderTimelineSteps(timelineRow, group);
        }
      });
    });
  }

  // Delete Group Button
  const delBtn = card.querySelector('.btn-card-del, .btn-del-group');
  if (delBtn) {
    delBtn.addEventListener('click', () => {
      const idx = cachedActionGroups.findIndex((g) => g.id === group.id);
      if (idx !== -1) {
        cachedActionGroups.splice(idx, 1);
        filterAndRenderCommands();
      }
    });
  }

  return card;
}

function renderTimelineSteps(container, group) {
  container.innerHTML = '';
  const seq = normalizeAction(group.action);

  seq.forEach((step, stepIdx) => {
    if (stepIdx > 0) {
      const arrow = document.createElement('span');
      arrow.className = 'timeline-arrow step-arrow';
      arrow.textContent = '→';
      container.appendChild(arrow);
    }

    const stepEl = document.createElement('div');
    stepEl.className = 'timeline-step';

    if (typeof step === 'number') {
      // Delay step
      stepEl.innerHTML = `
        <span class="step-delay-badge">Пауза: <input type="number" class="input-number step-delay-input" style="width:55px; padding:2px 4px; font-size:11px;" value="${Math.round(step * 1000)}" min="10" max="5000" /> мс</span>
        <button class="step-remove btn-del-step" title="Удалить шаг">&times;</button>
      `;

      stepEl.querySelector('.step-delay-input').addEventListener('change', (e) => {
        const ms = Number(e.target.value) || 100;
        seq[stepIdx] = ms / 1000;
        group.action = seq.length === 1 ? seq[0] : seq;
      });
    } else {
      // Key combination step
      const combo = Array.isArray(step) ? step : [step];
      const badgesHtml = combo.map((k) => `<span class="step-key-badge key-badge">${escapeHtml(k.toUpperCase())}</span>`).join(' <span style="font-size:10px; color:var(--text-dim); margin:0 1px;">+</span> ');

      stepEl.innerHTML = `
        <div class="step-combo-badges">${badgesHtml}</div>
        <button class="step-remove btn-del-step" title="Удалить шаг">&times;</button>
      `;

      stepEl.querySelector('.step-combo-badges').addEventListener('click', () => {
        openKeyRecorder((res) => {
          if (res) {
            seq[stepIdx] = res;
            group.action = seq.length === 1 ? seq[0] : seq;
            renderTimelineSteps(container, group);
          }
        });
      });
    }

    stepEl.querySelector('.step-remove, .btn-del-step').addEventListener('click', (e) => {
      e.stopPropagation();
      seq.splice(stepIdx, 1);
      if (seq.length === 0) seq.push('f');
      group.action = seq.length === 1 ? seq[0] : seq;
      renderTimelineSteps(container, group);
    });

    container.appendChild(stepEl);
  });

  // + Add Key button
  const addKeyBtn = document.createElement('button');
  addKeyBtn.className = 'btn btn-small btn-secondary btn-step-add';
  addKeyBtn.textContent = '+ Клавиша';
  addKeyBtn.addEventListener('click', () => {
    openKeyRecorder((res) => {
      if (res) {
        seq.push(res);
        group.action = seq.length === 1 ? seq[0] : seq;
        renderTimelineSteps(container, group);
      }
    });
  });
  container.appendChild(addKeyBtn);

  // + Add Delay button
  const addDelayBtn = document.createElement('button');
  addDelayBtn.className = 'btn btn-small btn-secondary btn-step-add';
  addDelayBtn.textContent = '+ Пауза';
  addDelayBtn.addEventListener('click', () => {
    seq.push(0.1);
    group.action = seq.length === 1 ? seq[0] : seq;
    renderTimelineSteps(container, group);
  });
  container.appendChild(addDelayBtn);
}

function renderPhraseChips(container, group) {
  container.innerHTML = '';
  const isTooMany = group.phrases.length > 7;
  const visiblePhrases = (isTooMany && !group.expanded) ? group.phrases.slice(0, 6) : group.phrases;

  visiblePhrases.forEach((phrase, pIdx) => {
    const chip = document.createElement('span');
    chip.className = 'phrase-chip phrase-tag-chip';
    chip.innerHTML = `${escapeHtml(phrase)} <span class="phrase-chip-del tag-del" data-idx="${pIdx}">&times;</span>`;

    chip.querySelector('.phrase-chip-del, .tag-del').addEventListener('click', (e) => {
      e.stopPropagation();
      if (group.phrases.length <= 1) {
        alert('Макрос должен содержать хотя бы одну фразу для активации.');
        return;
      }
      group.phrases.splice(pIdx, 1);
      renderPhraseChips(container, group);
      const card = container.closest('.action-card, .command-card');
      if (card) {
        const titleEl = card.querySelector('.cmd-main-phrase');
        if (titleEl) titleEl.textContent = group.phrases[0] || 'Новый макрос';
        const countEl = card.querySelector('.action-phrases-count, .cmd-phrases-count');
        if (countEl) countEl.textContent = `${group.phrases.length} ${pluralize(group.phrases.length, 'фраза', 'фразы', 'фраз')}`;
      }
    });

    container.appendChild(chip);
  });

  if (isTooMany) {
    const moreBtn = document.createElement('button');
    moreBtn.className = 'btn-link btn-expand-phrases btn-more-phrases';
    moreBtn.textContent = group.expanded ? 'Свернуть' : `Ещё ${group.phrases.length - 6} фраз...`;
    moreBtn.addEventListener('click', () => {
      group.expanded = !group.expanded;
      renderPhraseChips(container, group);
    });
    container.appendChild(moreBtn);
  }
}

function normalizeAction(action) {
  if (!action) return ['f'];
  if (typeof action === 'string') return [action];
  if (Array.isArray(action)) {
    const isFlatCombo = action.length > 0 && action.every((x) => typeof x === 'string');
    if (isFlatCombo && action.some((k) => ['alt', 'ctrl', 'shift', 'win'].includes(k.toLowerCase()))) {
      return [action];
    }
    return [...action];
  }
  return [action];
}

// ============================================================================
// 4. APPS AND SITES (253 APPS + 40 SITES)
// ============================================================================
function populateAppsAndSites() {
  const b = state.backend;
  const apps = b.apps || {};
  const sites = b.sites || {};

  const appsCount = Object.keys(apps).length;
  const sitesCount = Object.keys(sites).length;

  // Update Badges
  const tabBadge = document.getElementById('apps-tab-badge');
  if (tabBadge) tabBadge.textContent = String(appsCount + sitesCount);

  const appsCounter = document.getElementById('apps-counter');
  if (appsCounter) appsCounter.textContent = `${appsCount} программ`;

  const sitesCounter = document.getElementById('sites-counter');
  if (sitesCounter) sitesCounter.textContent = `${sitesCount} сайтов`;

  renderAppsTable(apps);
  renderSitesTable(sites);
}

function renderAppsTable(apps) {
  const tbody = document.querySelector('#apps-table tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  const frag = document.createDocumentFragment();
  Object.entries(apps).forEach(([cmd, target]) => {
    const tr = createAppRow(cmd, target);
    frag.appendChild(tr);
  });
  tbody.appendChild(frag);
}

function createAppRow(cmd = '', target = '') {
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><input type="text" class="input-text app-cmd" value="${escapeHtml(cmd)}" placeholder="блокнот" /></td>
    <td><input type="text" class="input-text app-target" value="${escapeHtml(target)}" placeholder="notepad" /></td>
    <td><button class="btn btn-small btn-secondary btn-browse-app">Обзор...</button></td>
    <td><button class="btn-link btn-del-row" style="color:var(--accent-red); font-size:16px;">&times;</button></td>
  `;

  tr.querySelector('.btn-browse-app').addEventListener('click', async () => {
    const file = await window.host?.selectFile?.({
      filters: [
        { name: 'Программы и ярлыки', extensions: ['exe', 'bat', 'cmd', 'lnk'] },
        { name: 'Все файлы', extensions: ['*'] }
      ]
    });
    if (file) {
      tr.querySelector('.app-target').value = file;
    }
  });

  tr.querySelector('.btn-del-row').addEventListener('click', () => {
    tr.remove();
    updateAppsCounter();
  });

  return tr;
}

function addAppRow(cmd = '', target = '') {
  const tbody = document.querySelector('#apps-table tbody');
  if (!tbody) return;
  const tr = createAppRow(cmd, target);
  tbody.insertBefore(tr, tbody.firstChild);
  tr.querySelector('.app-cmd')?.focus();
  updateAppsCounter();
}

function updateAppsCounter() {
  const rows = document.querySelectorAll('#apps-table tbody tr');
  const count = rows.length;
  const counter = document.getElementById('apps-counter');
  if (counter) counter.textContent = `${count} программ`;

  const sitesCount = document.querySelectorAll('#sites-table tbody tr').length;
  const tabBadge = document.getElementById('apps-tab-badge');
  if (tabBadge) tabBadge.textContent = String(count + sitesCount);
}

function renderSitesTable(sites) {
  const tbody = document.querySelector('#sites-table tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  const frag = document.createDocumentFragment();
  Object.entries(sites).forEach(([cmd, url]) => {
    const tr = createSiteRow(cmd, url);
    frag.appendChild(tr);
  });
  tbody.appendChild(frag);
}

function createSiteRow(cmd = '', url = '') {
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><input type="text" class="input-text site-cmd" value="${escapeHtml(cmd)}" placeholder="ютуб" /></td>
    <td><input type="text" class="input-text site-url" value="${escapeHtml(url)}" placeholder="https://www.youtube.com" /></td>
    <td><button class="btn-link btn-del-row" style="color:var(--accent-red); font-size:16px;">&times;</button></td>
  `;

  tr.querySelector('.btn-del-row').addEventListener('click', () => {
    tr.remove();
    updateSitesCounter();
  });

  return tr;
}

function addSiteRow(cmd = '', url = '') {
  const tbody = document.querySelector('#sites-table tbody');
  if (!tbody) return;
  const tr = createSiteRow(cmd, url);
  tbody.insertBefore(tr, tbody.firstChild);
  tr.querySelector('.site-cmd')?.focus();
  updateSitesCounter();
}

function updateSitesCounter() {
  const rows = document.querySelectorAll('#sites-table tbody tr');
  const count = rows.length;
  const counter = document.getElementById('sites-counter');
  if (counter) counter.textContent = `${count} сайтов`;

  const appsCount = document.querySelectorAll('#apps-table tbody tr').length;
  const tabBadge = document.getElementById('apps-tab-badge');
  if (tabBadge) tabBadge.textContent = String(appsCount + count);
}

// 4.1 Search Filtering for Apps & Sites
function filterApps(query) {
  const q = (query || '').trim().toLowerCase();
  const rows = document.querySelectorAll('#apps-table tbody tr');
  let visible = 0;

  rows.forEach((tr) => {
    const cmd = (tr.querySelector('.app-cmd')?.value || '').toLowerCase();
    const target = (tr.querySelector('.app-target')?.value || '').toLowerCase();
    const match = !q || cmd.includes(q) || target.includes(q);
    tr.style.display = match ? '' : 'none';
    if (match) visible++;
  });

  const counter = document.getElementById('apps-counter');
  if (counter) {
    counter.textContent = q ? `Найдено ${visible} из ${rows.length}` : `${rows.length} программ`;
  }
}

function filterSites(query) {
  const q = (query || '').trim().toLowerCase();
  const rows = document.querySelectorAll('#sites-table tbody tr');
  let visible = 0;

  rows.forEach((tr) => {
    const cmd = (tr.querySelector('.site-cmd')?.value || '').toLowerCase();
    const url = (tr.querySelector('.site-url')?.value || '').toLowerCase();
    const match = !q || cmd.includes(q) || url.includes(q);
    tr.style.display = match ? '' : 'none';
    if (match) visible++;
  });

  const counter = document.getElementById('sites-counter');
  if (counter) {
    counter.textContent = q ? `Найдено ${visible} из ${rows.length}` : `${rows.length} сайтов`;
  }
}

// ============================================================================
// 5. SYSTEM TAB
// ============================================================================
function populateSystem() {
  document.getElementById('link-github-capri')?.addEventListener('click', (e) => {
    e.preventDefault();
    window.host?.openSite?.('https://github.com/Mintermonde/capricorn_v3');
  });

  document.getElementById('link-github-desktop')?.addEventListener('click', (e) => {
    e.preventDefault();
    window.host?.openSite?.('https://github.com/mochiiwuff/capri-desktop');
  });
}

// ============================================================================
// 6. EVENT LISTENERS
// ============================================================================
function setupEventListeners() {
  // Save All
  document.getElementById('btn-save')?.addEventListener('click', saveAll);

  // Add App / Site
  document.getElementById('btn-add-app-row')?.addEventListener('click', () => addAppRow());
  document.getElementById('btn-add-site-row')?.addEventListener('click', () => addSiteRow());

  // Search in Apps & Sites
  document.getElementById('search-apps')?.addEventListener('input', (e) => {
    filterApps(e.target.value);
  });
  document.getElementById('search-sites')?.addEventListener('input', (e) => {
    filterSites(e.target.value);
  });

  // Collapsible: Apps list
  document.getElementById('btn-toggle-apps')?.addEventListener('click', (e) => {
    const wrapper = document.getElementById('apps-collapsible-wrapper');
    if (!wrapper) return;
    const isCollapsed = wrapper.classList.toggle('collapsed');
    e.target.textContent = isCollapsed ? 'Развернуть список' : 'Свернуть список';
  });

  // Collapsible: Sites list
  document.getElementById('btn-toggle-sites')?.addEventListener('click', (e) => {
    const wrapper = document.getElementById('sites-collapsible-wrapper');
    if (!wrapper) return;
    const isCollapsed = wrapper.classList.toggle('collapsed');
    e.target.textContent = isCollapsed ? 'Развернуть список' : 'Свернуть список';
  });

  // Collapsible: Games Hub list
  document.getElementById('btn-toggle-games-hub')?.addEventListener('click', (e) => {
    const grid = document.getElementById('games-grid');
    if (!grid) return;
    const isCollapsed = grid.classList.toggle('collapsed');
    e.target.textContent = isCollapsed ? 'Развернуть список игр' : 'Свернуть список игр';
  });

  // Collapsible: All Macro Phrases in Game Editor
  document.getElementById('btn-toggle-all-macros')?.addEventListener('click', (e) => {
    allMacrosExpanded = !allMacrosExpanded;
    cachedActionGroups.forEach((g) => { g.expanded = allMacrosExpanded; });
    e.target.textContent = allMacrosExpanded ? 'Свернуть фразы' : 'Развернуть фразы';
    filterAndRenderCommands();
  });

  // Refresh microphones
  document.getElementById('btn-refresh-mics')?.addEventListener('click', populateMics);

  // Add wake word
  document.getElementById('btn-add-wake-word')?.addEventListener('click', () => {
    const input = document.getElementById('new-wake-word');
    const word = input?.value?.trim().toLowerCase();
    if (!word) return;
    const current = getWakeWords();
    if (!current.includes(word)) {
      current.push(word);
      renderWakeWords(current);
    }
    input.value = '';
  });

  // ---------------- GAME HUB ACTIONS ----------------
  // Search in Games Hub
  document.getElementById('search-games-hub')?.addEventListener('input', (e) => {
    populateGamesHub(e.target.value);
  });

  // Quick Browse .exe in Hub
  document.getElementById('btn-hub-quick-browse')?.addEventListener('click', async () => {
    const file = await window.host?.selectFile?.({
      filters: [
        { name: 'Исполняемые файлы (.exe)', extensions: ['exe', 'lnk', 'bat'] },
        { name: 'Все файлы', extensions: ['*'] }
      ]
    });
    if (file) {
      const filename = file.split(/[/\\]/).pop() || file;
      setVal('hub-quick-exe', filename);
      const nameInput = document.getElementById('hub-quick-name');
      if (nameInput && !nameInput.value.trim()) {
        nameInput.value = filename.replace(/\.(exe|lnk|bat)$/i, '');
      }
    }
  });

  // Quick Add Game in Hub (+ Добавить игру)
  document.getElementById('btn-hub-quick-add')?.addEventListener('click', () => {
    const nameInput = document.getElementById('hub-quick-name');
    const exeInput = document.getElementById('hub-quick-exe');
    const name = (nameInput?.value || '').trim();

    if (!name) {
      nameInput?.focus();
      nameInput?.classList.add('input-error');
      setTimeout(() => nameInput?.classList.remove('input-error'), 1500);
      return;
    }

    const exe = (exeInput?.value || '').trim();
    const gid = name.toLowerCase().replace(/[^a-z0-9_]+/g, '_') || ('game_' + Date.now());

    state.games.games[gid] = {
      name: name,
      processes: exe ? [exe] : [gid + '.exe'],
      focus_mode: 'foreground',
      enabled: true,
      bindings: {}
    };

    if (nameInput) nameInput.value = '';
    if (exeInput) exeInput.value = '';

    openGameEditor(gid);
  });

  // Back to Hub Button (← Назад к списку игр)
  document.getElementById('btn-back-to-hub')?.addEventListener('click', () => {
    closeGameEditorToHub();
  });

  // ---------------- GAME EDITOR ACTIONS ----------------
  // Remove Game Profile
  document.getElementById('btn-remove-game')?.addEventListener('click', () => {
    const totalGames = Object.keys(state.games.games || {}).length;
    if (totalGames <= 1) {
      alert('Нельзя удалить единственный оставшийся профиль игры.');
      return;
    }
    const curName = state.games.games[selectedGameId]?.name || selectedGameId;
    if (confirm(`Вы уверены, что хотите удалить профиль "${curName}"?`)) {
      delete state.games.games[selectedGameId];
      isEditingGameDraft = false;
      selectedGameId = Object.keys(state.games.games)[0];
      closeGameEditorToHub();
    }
  });

  // Search Game Commands
  document.getElementById('search-game-commands')?.addEventListener('input', () => {
    filterAndRenderCommands();
  });

  // Create new macro card (+ Создать макрос)
  document.getElementById('btn-add-command-card')?.addEventListener('click', () => {
    const newGroup = {
      id: 'cmd_' + Math.random().toString(36).slice(2, 9),
      phrases: ['новая команда'],
      action: ['f'],
      expanded: true
    };
    cachedActionGroups.unshift(newGroup);
    filterAndRenderCommands();

    const firstCard = document.querySelector('.command-card');
    firstCard?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    firstCard?.querySelector('.input-add-phrase')?.focus();
  });

  // Capture Window from running processes
  
    // Show / Hide API Key toggle button
  document.getElementById('btn-toggle-key')?.addEventListener('click', (e) => {
    const input = document.getElementById('cfg-aiKey');
    if (!input) return;
    if (input.type === 'password') {
      input.type = 'text';
      e.target.textContent = 'Скрыть';
    } else {
      input.type = 'password';
      e.target.textContent = 'Показать';
    }
  });

  // Persona default & clear buttons
  document.getElementById('btn-default-persona')?.addEventListener('click', () => {
    setVal('cfg-persona', DEFAULT_CAPRI_PERSONA);
  });
  document.getElementById('btn-clear-persona')?.addEventListener('click', () => {
    setVal('cfg-persona', '');
  });

  // AI Provider change & model dropdown
  document.getElementById('cfg-aiProvider')?.addEventListener('change', (e) => {
    renderAIProviderUI(e.target.value);
  });
  document.getElementById('cfg-aiModel')?.addEventListener('change', (e) => {
    const customInput = document.getElementById('cfg-aiModelCustom');
    if (customInput) {
      if (e.target.value === 'custom') {
        customInput.classList.remove('hidden');
        customInput.focus();
      } else {
        customInput.classList.add('hidden');
      }
    }
  });

  // Test AI Connection button
  document.getElementById('btn-test-ai')?.addEventListener('click', async () => {
    const statusEl = document.getElementById('test-ai-status');
    const prov = getVal('cfg-aiProvider');
    const key = getVal('cfg-aiKey');
    const url = getVal('cfg-aiUrl');
    const model = getSelectedAIModel();

    if (statusEl) {
      statusEl.textContent = 'Проверка соединения...';
      statusEl.className = 'test-status';
    }

    try {
      const res = await window.host?.testAiConnection?.({ provider: prov, key, url, model });
      if (res?.ok) {
        if (statusEl) {
          statusEl.textContent = res.status || 'Связь успешно установлена!';
          statusEl.className = 'test-status ok';
        }
      } else {
        if (statusEl) {
          statusEl.textContent = `Ошибка: ${res?.error || 'Нет ответа'}`;
          statusEl.className = 'test-status error';
        }
      }
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = `Сбой: ${err.message}`;
        statusEl.className = 'test-status error';
      }
    }
  });

  // Game Icon: Pick Image File
  const pickGameIconHandler = async () => {
    if (!selectedGameId || !state.games.games[selectedGameId]) return;
    const gdata = state.games.games[selectedGameId];
    const dataUrl = await window.host?.selectImage?.();
    if (dataUrl) {
      gdata.icon = dataUrl;
      updateEditorGameMonogram(gdata);
      populateGamesHub();
    }
  };
  document.getElementById('btn-pick-game-icon')?.addEventListener('click', pickGameIconHandler);
  document.getElementById('editor-game-monogram')?.addEventListener('click', pickGameIconHandler);

  // Game Icon: Extract from .exe
  document.getElementById('btn-extract-game-icon')?.addEventListener('click', async () => {
    if (!selectedGameId || !state.games.games[selectedGameId]) return;
    const gdata = state.games.games[selectedGameId];
    const proc = (document.getElementById('game-process')?.value || gdata.processes?.[0] || '').trim();

    if (proc.includes('\\') || proc.includes('/')) {
      const icon = await window.host?.getFileIcon?.(proc);
      if (icon) {
        gdata.icon = icon;
        updateEditorGameMonogram(gdata);
        populateGamesHub();
        return;
      }
    }

    const exePath = await window.host?.selectFile?.({
      title: 'Выберите исполняемый файл игры (.exe)',
      filters: [{ name: 'Исполняемые файлы (*.exe)', extensions: ['exe'] }, { name: 'Все файлы', extensions: ['*'] }]
    });
    if (exePath) {
      const icon = await window.host?.getFileIcon?.(exePath);
      if (icon) {
        gdata.icon = icon;
        updateEditorGameMonogram(gdata);
        populateGamesHub();
      }
      const fileName = exePath.split(/[\\/]/).pop();
      if (fileName) {
        const procInput = document.getElementById('game-process');
        if (procInput && (!procInput.value || procInput.value === 'game.exe')) {
          procInput.value = fileName;
          gdata.processes = [fileName];
        }
      }
    }
  });

  // Game Icon: Reset
  document.getElementById('btn-reset-game-icon')?.addEventListener('click', () => {
    if (!selectedGameId || !state.games.games[selectedGameId]) return;
    delete state.games.games[selectedGameId].icon;
    updateEditorGameMonogram(state.games.games[selectedGameId]);
    populateGamesHub();
  });
  
  document.getElementById('btn-capture-window')?.addEventListener('click', () => {
    windowSelectTarget = 'game';
    openCaptureModal();
  });

  // ---------------- MODAL LISTENERS ----------------
  // Close Capture Modal
  document.getElementById('btn-close-win-modal')?.addEventListener('click', closeCaptureModal);
  document.getElementById('btn-cancel-win-modal')?.addEventListener('click', closeCaptureModal);
  document.getElementById('btn-refresh-win-modal')?.addEventListener('click', populateRunningWindows);

  // Close Record Modal
  document.getElementById('btn-close-rec-modal')?.addEventListener('click', closeKeyRecorder);
  document.getElementById('btn-cancel-rec')?.addEventListener('click', closeKeyRecorder);

  // Live Sync Game Name in Editor Header
  document.getElementById('game-name')?.addEventListener('input', (e) => {
    const val = e.target.value.trim();
    const titleEl = document.getElementById('editor-game-title');
    const monoEl = document.getElementById('editor-game-monogram');
    if (titleEl) titleEl.textContent = val || selectedGameId;
    if (monoEl) monoEl.textContent = getMonogram(val || selectedGameId);
  });

  // Live Sync Game Active State
  document.getElementById('game-enabled')?.addEventListener('change', (e) => {
    const isAct = e.target.checked;
    const statusEl = document.getElementById('editor-game-status');
    if (statusEl) {
      statusEl.className = `badge-status-chip ${isAct ? 'active' : 'disabled'}`;
      statusEl.textContent = isAct ? 'Активен' : 'Отключен';
    }
  });
}

// ============================================================================
// 7. WINDOW CAPTURE MODAL
// ============================================================================
function openCaptureModal() {
  const modal = document.getElementById('windows-modal');
  modal?.classList.remove('hidden');
  populateRunningWindows();
}

function closeCaptureModal() {
  const modal = document.getElementById('windows-modal');
  modal?.classList.add('hidden');
}

async function populateRunningWindows() {
  const listEl = document.getElementById('running-windows-list');
  if (!listEl) return;
  listEl.innerHTML = '<div style="color:var(--text-muted); padding:10px;">Обновление списка окон...</div>';

  try {
    const wins = await window.host?.getOpenWindows?.();
    if (!wins || wins.length === 0) {
      listEl.innerHTML = '<div style="color:var(--text-muted); padding:10px;">Нет доступных окон для захвата.</div>';
      return;
    }

    listEl.innerHTML = '';
    const frag = document.createDocumentFragment();

    wins.forEach((w) => {
      const item = document.createElement('div');
      item.className = 'running-item';
      item.innerHTML = `
        <div class="running-title">${escapeHtml(w.title || 'Безымянное окно')}</div>
        <div class="running-exe">${escapeHtml(w.process || '')}</div>
      `;

      item.addEventListener('click', () => {
        if (windowSelectTarget === 'game') {
          setVal('game-process', w.process || '');
          const curName = getVal('game-name');
          if (!curName || curName === selectedGameId) {
            setVal('game-name', (w.title || w.process || '').replace(/\.exe$/i, ''));
          }
          if (w.path && selectedGameId && state.games.games[selectedGameId]) {
            window.host?.getFileIcon?.(w.path).then((icon) => {
              if (icon) {
                state.games.games[selectedGameId].icon = icon;
                updateEditorGameMonogram(state.games.games[selectedGameId]);
                populateGamesHub();
              }
            });
          }
        } else if (windowSelectTarget === 'new_game_modal') {
          setVal('new-game-exe', w.process || '');
          const curName = getVal('new-game-name');
          if (!curName) {
            setVal('new-game-name', (w.title || w.process || '').replace(/\.exe$/i, ''));
          }
        }
        closeCaptureModal();
      });

      frag.appendChild(item);
    });

    listEl.appendChild(frag);
  } catch (e) {
    listEl.innerHTML = `<div style="color:var(--accent-red); padding:10px;">Ошибка получения окон: ${escapeHtml(e.message)}</div>`;
  }
}

// ============================================================================
// 8. KEY RECORDER MODAL
// ============================================================================
function openKeyRecorder(cb) {
  recordingCallback = cb;
  recordedKeyResult = null;

  const modal = document.getElementById('recorder-modal');
  const preview = document.getElementById('rec-preview');
  const acceptBtn = document.getElementById('btn-accept-rec');

  if (preview) preview.textContent = 'Ожидание нажатия клавиши или кнопки мыши...';
  if (acceptBtn) acceptBtn.disabled = true;

  modal?.classList.remove('hidden');

  const onKeyDown = (e) => {
    // Escape: cancel recording
    if (e.key === 'Escape' || e.code === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      closeKeyRecorder();
      return;
    }

    // Enter / NumpadEnter: if already recorded a key, accept it!
    if ((e.key === 'Enter' || e.code === 'Enter' || e.code === 'NumpadEnter') && recordedKeyResult) {
      e.preventDefault();
      e.stopPropagation();
      if (recordingCallback) recordingCallback(recordedKeyResult);
      closeKeyRecorder();
      return;
    }

    e.preventDefault();
    e.stopPropagation();

    const parts = [];
    if (e.altKey) parts.push('alt');
    if (e.ctrlKey) parts.push('ctrl');
    if (e.shiftKey) parts.push('shift');

    const mapped = mapKeyName(e.code, e.key);
    if (mapped && !parts.includes(mapped)) {
      parts.push(mapped);
    }

    if (parts.length > 0) {
      recordedKeyResult = parts.length === 1 ? parts[0] : parts;
      const displayStr = parts.map((k) => k.toUpperCase()).join(' + ');
      if (preview) preview.textContent = displayStr;
      if (acceptBtn) acceptBtn.disabled = false;
    }
  };

  const onMouseDown = (e) => {
    // If clicking action buttons in modal (Принять, Отмена, ×), DO NOT record!
    if (e.target && e.target.closest('#btn-accept-rec, #btn-cancel-rec, #btn-close-rec-modal, .modal-actions, .modal-footer, .btn-close-modal')) {
      return;
    }

    let btnName = null;
    if (e.button === 1) btnName = 'mouse3';       // Middle click
    else if (e.button === 3) btnName = 'mouse4';  // Back thumb button
    else if (e.button === 4) btnName = 'mouse5';  // Forward thumb button
    else if (e.button === 0) {
      // Left click is only recorded if clicked directly inside the target capture preview box
      if (e.target && e.target.closest('#rec-preview')) {
        btnName = 'mouse1';
      } else {
        return; // Ignore regular UI clicks elsewhere in the modal!
      }
    } else if (e.button === 2) {
      // Right click is only recorded if clicked directly inside the target capture preview box
      if (e.target && e.target.closest('#rec-preview')) {
        btnName = 'mouse2';
      } else {
        return;
      }
    }

    if (btnName) {
      e.preventDefault();
      e.stopPropagation();

      const parts = [];
      if (e.altKey) parts.push('alt');
      if (e.ctrlKey) parts.push('ctrl');
      if (e.shiftKey) parts.push('shift');
      parts.push(btnName);

      recordedKeyResult = parts.length === 1 ? parts[0] : parts;
      const displayStr = parts.map((k) => k.toUpperCase()).join(' + ');
      if (preview) preview.textContent = displayStr;
      if (acceptBtn) acceptBtn.disabled = false;
    }
  };

  window._recordCleanup = () => {
    window.removeEventListener('keydown', onKeyDown, true);
    window.removeEventListener('mousedown', onMouseDown, true);
    delete window._recordCleanup;
  };

  window.addEventListener('keydown', onKeyDown, true);
  window.addEventListener('mousedown', onMouseDown, true);

  acceptBtn.onclick = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (recordedKeyResult && recordingCallback) {
      recordingCallback(recordedKeyResult);
    }
    closeKeyRecorder();
  };
}

function closeKeyRecorder() {
  if (window._recordCleanup) window._recordCleanup();
  const modal = document.getElementById('recorder-modal');
  modal?.classList.add('hidden');
  recordingCallback = null;
  recordedKeyResult = null;
}

function mapKeyName(code, rawKey) {
  const key = (rawKey || '').toLowerCase();

  if (code.startsWith('Key')) return code.slice(3).toLowerCase();
  if (code.startsWith('Digit')) return code.slice(5);
  if (/^F\d{1,2}$/.test(code)) return code.toLowerCase();

  if (code === 'Space') return 'space';
  if (code === 'Enter') return 'enter';
  if (code === 'Tab') return 'tab';
  if (code === 'Escape') return 'escape';
  if (code === 'Backspace') return 'backspace';
  if (code === 'Delete') return 'delete';
  if (code === 'ArrowUp') return 'up';
  if (code === 'ArrowDown') return 'down';
  if (code === 'ArrowLeft') return 'left';
  if (code === 'ArrowRight') return 'right';

  if (DI_KEYS.includes(key)) return key;
  return key.length === 1 ? key : null;
}

// ============================================================================
// 9. SAVING SETTINGS
// ============================================================================
function saveCurrentGameDraft() {
  if (!isEditingGameDraft) return;
  const gamesObj = state.games.games || {};
  if (!gamesObj[selectedGameId]) return;

  const gdata = gamesObj[selectedGameId];
  const newName = getVal('game-name');
  if (newName) gdata.name = newName;
  const proc = getVal('game-process');
  if (proc) gdata.processes = [proc];
  gdata.focus_mode = getVal('game-focus-mode') || 'foreground';
  gdata.enabled = getChecked('game-enabled');

  // Convert cachedActionGroups back into flat bindings map ONLY if initialized
  if (Array.isArray(cachedActionGroups) && cachedActionGroups.length > 0) {
    const newBindings = {};
    cachedActionGroups.forEach((group) => {
      const phrases = group.phrases.map((s) => s.trim().toLowerCase()).filter(Boolean);
      const action = group.action;

      if (phrases.length > 0 && action) {
        phrases.forEach((p) => {
          newBindings[p] = action;
        });
      }
    });
    gdata.bindings = newBindings;
  }
}

async function saveAll() {
  const statusEl = document.getElementById('save-status');
  if (statusEl) {
    statusEl.textContent = 'Сохранение всех параметров...';
    statusEl.className = 'footer-status';
  }

  // 1. Gather Visual Settings
  const visualPatch = {
    theme: getVal('cfg-theme') || 'dark',
    userName: getVal('cfg-userName'),
    persona: getVal('cfg-persona'),
    rest: getVal('cfg-rest'),
    motion: getVal('cfg-motion'),
    wander: getChecked('cfg-wander'),
    possess: getChecked('cfg-possess'),
    jealous: getChecked('cfg-jealous'),
    pcReact: getChecked('cfg-pcReact'),
    startup: getChecked('cfg-startup'),
    volume: Number(document.getElementById('cfg-volume')?.value || 70) / 100,
    muted: getChecked('cfg-muted'),
    geminiUrl: getVal('cfg-aiUrl'),
  };

  // 2. Gather Backend Settings
  const apps = {};
  document.querySelectorAll('#apps-table tbody tr').forEach((tr) => {
    const cmd = tr.querySelector('.app-cmd')?.value?.trim().toLowerCase();
    const target = tr.querySelector('.app-target')?.value?.trim();
    if (cmd && target) apps[cmd] = target;
  });

  const sites = {};
  document.querySelectorAll('#sites-table tbody tr').forEach((tr) => {
    const cmd = tr.querySelector('.site-cmd')?.value?.trim().toLowerCase();
    const url = tr.querySelector('.site-url')?.value?.trim();
    if (cmd && url) sites[cmd] = url;
  });

  const prov = getVal('cfg-aiProvider') || 'gemini';
  const chosenModel = getSelectedAIModel();
  const apiKey = getVal('cfg-aiKey');
  const aiUrl = getVal('cfg-aiUrl');

  visualPatch.provider = prov;
  visualPatch.chatModel = chosenModel;
  if (!visualPatch.apiKeys) visualPatch.apiKeys = {};
  visualPatch.apiKeys[prov] = apiKey;
  if (prov === 'gemini') visualPatch.geminiUrl = aiUrl;
  else visualPatch.customUrl = aiUrl;

  const backendPatch = {
    enable_ai: true,
    ai_provider: prov,
    model: chosenModel,
    gemini_api_key: prov === 'gemini' ? apiKey : (state.backend.gemini_api_key || ''),
    anthropic_api_key: prov === 'anthropic' ? apiKey : (state.backend.anthropic_api_key || ''),
    gemini_base_url: prov === 'gemini' ? aiUrl : (state.backend.gemini_base_url || ''),
    local_model: chosenModel,
    mic_device: getVal('cfg-mic'),
    barge_in: getChecked('cfg-bargeIn'),
    wake_words: getWakeWords(),
    chatter: getChecked('cfg-chatter'),
    chatter_min_minutes: Number(getVal('cfg-chatterMin')) || 15,
    chatter_max_minutes: Number(getVal('cfg-chatterMax')) || 40,
    apps,
    sites,
  };

  // 3. Gather Game Profiles
  if (isEditingGameDraft) {
    saveCurrentGameDraft();
  }
  const gamesPatch = state.games;

  try {
    const res = await window.host?.saveAllSettings?.({
      visual: visualPatch,
      backend: backendPatch,
      games: gamesPatch,
    });

    if (res?.ok !== false) {
      if (statusEl) {
        statusEl.textContent = 'Все настройки успешно сохранены!';
        statusEl.className = 'footer-status saved';
        setTimeout(() => {
          if (statusEl) statusEl.textContent = 'Все изменения сохранены';
        }, 4000);
      }
    } else {
      if (statusEl) statusEl.textContent = `Ошибка: ${res?.error || 'Не удалось сохранить'}`;
    }
  } catch (e) {
    if (statusEl) statusEl.textContent = `Ошибка: ${e.message}`;
  }
}

// ============================================================================
// 10. UTILITIES
// ============================================================================
function getVal(id) {
  const el = document.getElementById(id);
  return el ? el.value : '';
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function getChecked(id) {
  const el = document.getElementById(id);
  return el ? el.checked : false;
}

function setChecked(id, checked) {
  const el = document.getElementById(id);
  if (el) el.checked = Boolean(checked);
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function pluralize(n, one, two, five) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 19) return five;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return two;
  return five;
}
