const API = '';
const TOKEN_KEY = 'twvs_admin_token';
const STEP_LABELS = {
  scrape: 'Scrape Patreon comments',
  llm_requests: 'LLM extract requests',
  llm_library: 'LLM extract library',
  llm_done: 'LLM match done',
  engine: 'Rebuild engine',
  publish: 'Publish frontend',
};

let pollTimer = null;
let activeJobId = null;

function token() {
  return localStorage.getItem(TOKEN_KEY);
}

function setToken(value) {
  if (value) localStorage.setItem(TOKEN_KEY, value);
  else localStorage.removeItem(TOKEN_KEY);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (token()) headers.Authorization = `Bearer ${token()}`;
  if (options.body) headers['Content-Type'] = 'application/json';
  const res = await fetch(`${API}${path}`, { ...options, headers });
  if (res.status === 401) {
    setToken(null);
    showLogin();
    throw new Error('Session expired');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function showLogin() {
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('dashboard').classList.add('hidden');
  stopPolling();
}

function showDashboard() {
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('dashboard').classList.remove('hidden');
  startPolling();
}

function fmtTime(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000 || ts).toLocaleString();
}

function fmtFileTime(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString();
}

function setSessionPill(valid, message) {
  const el = document.getElementById('session-status');
  el.textContent = valid ? 'Session valid' : 'Session invalid';
  el.className = `status-pill ${valid ? 'ok' : 'err'}`;
  document.getElementById('session-detail').textContent = message || '';
}

function renderSteps(available) {
  const box = document.getElementById('steps');
  box.innerHTML = available
    .map(
      (step) => `
      <label class="step-chip">
        <input type="checkbox" name="step" value="${step}" checked>
        ${STEP_LABELS[step] || step}
      </label>`,
    )
    .join('');
}

function renderSystemStatus(data) {
  const ul = document.getElementById('system-status');
  ul.innerHTML = `
    <li><strong>API key:</strong> ${data.anthropic_key_configured ? 'Configured' : 'Not set (LLM steps will skip)'}</li>
    <li><strong>Engine data:</strong> ${data.engine_data_updated ? fmtFileTime(data.engine_data_updated) : 'Not built yet'}</li>
    <li><strong>Published frontend:</strong> ${data.standalone_updated ? fmtFileTime(data.standalone_updated) : 'Not published yet'}</li>
    <li><strong>Next scheduled run:</strong> ${data.schedule.next_run_at || '—'}</li>
    <li><strong>Last scheduled run:</strong> ${data.schedule.last_run_at || '—'}</li>
  `;
}

function renderJobs(jobs) {
  const list = document.getElementById('jobs-list');
  const activeBox = document.getElementById('active-job');
  const running = jobs.find((j) => j.status === 'running' || j.status === 'pending');

  if (running) {
    activeJobId = running.id;
    activeBox.classList.remove('hidden');
    activeBox.innerHTML = `
      <strong>Active: ${running.kind}</strong> — ${running.current_step || 'starting…'}
      <div class="job-logs">${(running.logs || []).slice(-12).join('\n')}</div>
    `;
  } else {
    activeBox.classList.add('hidden');
    activeJobId = null;
  }

  list.innerHTML = jobs
    .map(
      (j) => `
      <div class="job-item">
        <header>
          <span><strong>${j.kind}</strong> · ${j.id}</span>
          <span class="job-status ${j.status}">${j.status}</span>
        </header>
        <div class="muted">${j.created_at}${j.finished_at ? ` → ${j.finished_at}` : ''}</div>
        ${j.error ? `<div style="color:var(--err)">${j.error}</div>` : ''}
        ${j.logs?.length ? `<div class="job-logs">${j.logs.slice(-8).join('\n')}</div>` : ''}
      </div>`,
    )
    .join('');
}

async function refreshDashboard() {
  const data = await api('/api/admin/status');
  setSessionPill(data.patreon_session_valid, data.patreon_message);
  renderSteps(data.available_steps);
  renderSystemStatus(data);

  document.getElementById('schedule-enabled').checked = !!data.schedule.enabled;
  document.getElementById('schedule-hours').value = data.schedule.interval_hours || 24;
  document.getElementById('schedule-meta').textContent =
    `Last run: ${data.schedule.last_run_at || 'never'} · Next: ${data.schedule.next_run_at || '—'}`;

  const jobs = await api('/api/admin/jobs');
  renderJobs(jobs.jobs || []);
}

function startPolling() {
  stopPolling();
  refreshDashboard().catch(console.error);
  pollTimer = setInterval(() => {
    refreshDashboard().catch(console.error);
    if (activeJobId) {
      api(`/api/admin/jobs/${activeJobId}`).then((j) => {
        if (j.status === 'running' || j.status === 'pending') {
          document.querySelector('#active-job .job-logs').textContent = (j.logs || []).slice(-12).join('\n');
        }
      }).catch(() => {});
    }
  }, 4000);
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const errEl = document.getElementById('login-error');
  errEl.classList.add('hidden');
  try {
    const res = await fetch(`${API}/api/admin/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: document.getElementById('password').value }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Login failed');
    setToken(data.access_token);
    showDashboard();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove('hidden');
  }
});

document.getElementById('logout-btn').addEventListener('click', () => {
  setToken(null);
  showLogin();
});

document.getElementById('login-patreon-btn').addEventListener('click', async () => {
  const data = await api('/api/admin/patreon/login', { method: 'POST' });
  alert(data.message);
  activeJobId = data.job_id;
});

document.getElementById('refresh-session-btn').addEventListener('click', () => refreshDashboard());
document.getElementById('refresh-jobs-btn').addEventListener('click', () => refreshDashboard());

document.getElementById('save-schedule-btn').addEventListener('click', async () => {
  await api('/api/admin/schedule', {
    method: 'PUT',
    body: JSON.stringify({
      enabled: document.getElementById('schedule-enabled').checked,
      interval_hours: Number(document.getElementById('schedule-hours').value),
    }),
  });
  await refreshDashboard();
});

document.getElementById('run-pipeline-btn').addEventListener('click', async () => {
  const steps = [...document.querySelectorAll('input[name="step"]:checked')].map((el) => el.value);
  const data = await api('/api/admin/pipeline/run', {
    method: 'POST',
    body: JSON.stringify({ steps }),
  });
  activeJobId = data.job_id;
  await refreshDashboard();
});

if (token()) showDashboard();
else showLogin();
