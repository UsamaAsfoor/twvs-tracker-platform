const TAB_DEFINITIONS = [
  ['skz', 'Stray Kids', 'Stray Kids'],
  ['vtuber', 'VTuber', 'VTuber'],
  ['bts', 'BTS', 'BTS'],
  ['jpop', 'J-Pop', 'J-Pop'],
  ['ateez', 'ATEEZ', 'ATEEZ'],
  ['euro', 'Europe / Eurovision', 'Europe / Eurovision'],
  ['morekpop', 'More K-Pop / Korean', 'More K-Pop / Korean'],
  ['enhypen', 'ENHYPEN', 'ENHYPEN'],
  ['rock', 'Rock / Alt / Folk', 'Rock / Alt / Folk'],
  ['anime', 'Anime', 'Anime'],
  ['game', 'Video Game', 'Video Game'],
  ['musical', 'Musicals & Soundtracks', 'Musicals & Soundtracks'],
  ['other', 'Pop & Misc', 'Pop & Misc'],
];

const TAB_CUTOFF = {
  skz: 5,
  vtuber: 5,
  morekpop: 4,
  jpop: 4,
  bts: 4,
  other: 4,
  ateez: 3,
  rock: 3,
  euro: 3,
  game: 3,
  anime: 3,
  enhypen: 3,
};
const DEFAULT_CUTOFF = 4;
const PERSIST_MONTHS = 3;
const PERSIST_FLOOR = 2;

const MONTH_ABBR = {
  '01': 'Jan',
  '02': 'Feb',
  '03': 'Mar',
  '04': 'Apr',
  '05': 'May',
  '06': 'Jun',
  '07': 'Jul',
  '08': 'Aug',
  '09': 'Sep',
  '10': 'Oct',
  '11': 'Nov',
  '12': 'Dec',
};

const MONTH_NAMES = {
  '01': 'January',
  '02': 'February',
  '03': 'March',
  '04': 'April',
  '05': 'May',
  '06': 'June',
  '07': 'July',
  '08': 'August',
  '09': 'September',
  '10': 'October',
  '11': 'November',
  '12': 'December',
};

let state = {
  mode: 'cumulative',
  tab: 'all',
  search: '',
  data: null,
};

function qualifies(tab, totalHearts, monthsRequested) {
  const cutoff = TAB_CUTOFF[tab] ?? DEFAULT_CUTOFF;
  if (totalHearts >= cutoff) return true;
  if (monthsRequested >= PERSIST_MONTHS && totalHearts >= PERSIST_FLOOR) return true;
  return false;
}

function esc(text) {
  const el = document.createElement('span');
  el.textContent = String(text ?? '');
  return el.innerHTML;
}

function fmtMonthLabel(ym) {
  const [year, month] = ym.split('-');
  return `${MONTH_NAMES[month] ?? month} ${year}`;
}

function fmtMonthShort(ym) {
  return MONTH_ABBR[ym.slice(5, 7)] ?? ym;
}

function fmtMonthRange(months) {
  if (!months.length) return '';
  const first = months[0];
  const last = months[months.length - 1];
  const short = (ym) => `${MONTH_ABBR[ym.slice(5, 7)]}'${ym.slice(2, 4)}`;
  return `${short(first)} – ${short(last)}`;
}

function fmtMonths(byMonth) {
  return Object.entries(byMonth)
    .filter(([, hearts]) => hearts)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([m, h]) => `${fmtMonthShort(m)}:${h}`)
    .join(' ');
}

function doneBadge(doneDate) {
  if (!doneDate) return '';
  const d = new Date(`${doneDate}T12:00:00`);
  if (Number.isNaN(d.getTime())) return '<span class="badge done">✅ DONE</span>';
  const label = d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
  return `<span class="badge done">✅ DONE ${esc(label)}</span>`;
}

function persistBadge(byMonth) {
  const n = Object.values(byMonth).filter(Boolean).length;
  return n >= 2 ? `<span class="badge persist">🔥 ${n} MO</span>` : '';
}

function renderRequesters(requesters, limit = 6) {
  if (!requesters?.length) return '';
  if (requesters.length <= limit) return requesters.map(esc).join(', ');
  const shown = requesters.slice(0, limit).map(esc).join(', ');
  return `${shown} (+${requesters.length - limit} more)`;
}

function renderYt(url) {
  if (!url) return '';
  return ` <a href="${esc(url)}" target="_blank" rel="noopener" class="yt-link" aria-label="Watch on YouTube">▶</a>`;
}

function renderEntry({ hearts, artist, song, metaHtml, url, isTop, badges = '' }) {
  const heartsCls = isTop ? 'hearts top' : 'hearts';
  const title = esc(`${artist} — ${song}`);
  return `
    <div class="req">
      <span class="${heartsCls}">${hearts}</span>
      <div class="content">
        <div class="song">${title}${renderYt(url)}${badges}</div>
        <div class="meta">${metaHtml}</div>
      </div>
    </div>`;
}

function buildHistoryLookup(cumulative) {
  const hist = new Map();
  for (const row of cumulative) {
    hist.set(`${row.artist.toLowerCase()}|${row.song.toLowerCase()}`, row);
  }
  return hist;
}

function processData(eng) {
  const months = eng.months ?? [];
  const currentMonth = months[months.length - 1] ?? eng.current_month;
  const cumulative = eng.cumulative ?? [];
  const currentRows = eng.current_month_rows ?? [];
  const hist = buildHistoryLookup(cumulative);

  const cumByTab = {};
  for (const row of cumulative) {
    const monthCount = Object.values(row.by_month ?? {}).filter(Boolean).length;
    if (!qualifies(row.tab, row.total, monthCount)) continue;
    (cumByTab[row.tab] ??= []).push(row);
  }
  for (const rows of Object.values(cumByTab)) {
    rows.sort((a, b) => b.total - a.total);
  }

  const curByTab = {};
  for (const row of currentRows) {
    const key = `${row.artist.toLowerCase()}|${row.song.toLowerCase()}`;
    const history = hist.get(key);
    const monthCount = history
      ? Object.values(history.by_month ?? {}).filter(Boolean).length
      : 0;
    (curByTab[row.tab] ??= []).push({ row, history, monthCount });
  }
  for (const rows of Object.values(curByTab)) {
    rows.sort((a, b) => b.row.hearts - a.row.hearts);
  }

  return {
    months,
    currentMonth,
    coverageLabel: fmtMonthRange(months),
    cumByTab,
    curByTab,
  };
}

function sectionHtml(tabKey, h2, rowsHtml, countLine, mode) {
  return `
    <section class="genre-section" data-tab="all ${tabKey}" data-mode="${mode}">
      <div class="genre-header">
        <h2>${esc(h2)}</h2>
        <span class="genre-count">${esc(countLine)}</span>
      </div>
      <div class="req-list">${rowsHtml || '<div class="empty-state">No requests in this category.</div>'}</div>
    </section>`;
}

function renderCumulativeRows(rows) {
  const nTop = Math.max(1, Math.floor((rows.length * 15) / 100));
  return rows
    .map((row, i) => {
      let meta = renderRequesters(row.requesters);
      const breakdown = fmtMonths(row.by_month ?? {});
      if (breakdown) meta += ` · <span class="ctx">${esc(breakdown)}</span>`;
      const badges = doneBadge(row.done_date) + persistBadge(row.by_month ?? {});
      return renderEntry({
        hearts: row.total,
        artist: row.artist,
        song: row.song,
        metaHtml: meta,
        url: row.url,
        isTop: i < nTop,
        badges,
      });
    })
    .join('');
}

function renderCurrentRows(rows, currentMonth) {
  const nTop = Math.max(1, Math.floor((rows.length * 15) / 100));
  return rows
    .map(({ row, history, monthCount }, i) => {
      let meta = renderRequesters(row.requesters);
      if (monthCount >= 2 && history?.by_month) {
        const prior = Object.keys(history.by_month)
          .filter((m) => m !== currentMonth && history.by_month[m])
          .sort()
          .map(fmtMonthShort);
        if (prior.length) {
          meta += ` · <span class="ctx">↩ also requested ${esc(prior.join(', '))}</span>`;
        }
      }
      const badges =
        doneBadge(row.done_date) +
        (history ? persistBadge(history.by_month ?? {}) : '');
      return renderEntry({
        hearts: row.hearts,
        artist: row.artist,
        song: row.song,
        metaHtml: meta,
        url: row.url,
        isTop: i < nTop,
        badges,
      });
    })
    .join('');
}

function renderTracker(eng) {
  const processed = processData(eng);
  const { months, currentMonth, coverageLabel, cumByTab, curByTab } = processed;

  const cumCounts = {};
  const curCounts = {};
  const cumSections = [];
  const curSections = [];

  let cumTotalHearts = 0;
  let cumTotalSongs = 0;
  let curTotalHearts = 0;
  let curTotalSongs = 0;

  for (const [tabKey, , h2] of TAB_DEFINITIONS) {
    const cumRows = cumByTab[tabKey] ?? [];
    if (cumRows.length) {
      const totalH = cumRows.reduce((sum, r) => sum + r.total, 0);
      cumCounts[tabKey] = `${totalH} ❤️`;
      cumTotalHearts += totalH;
      cumTotalSongs += cumRows.length;
      cumSections.push(
        sectionHtml(
          tabKey,
          h2,
          renderCumulativeRows(cumRows),
          `${coverageLabel} · ${cumRows.length} requests · ${totalH} ❤️`,
          'cumulative',
        ),
      );
    }

    const curRows = curByTab[tabKey] ?? [];
    if (curRows.length) {
      const totalH = curRows.reduce((sum, r) => sum + r.row.hearts, 0);
      curCounts[tabKey] = `${totalH} ❤️`;
      curTotalHearts += totalH;
      curTotalSongs += curRows.length;
      curSections.push(
        sectionHtml(
          tabKey,
          h2,
          renderCurrentRows(curRows, currentMonth),
          `${fmtMonthLabel(currentMonth)} · ${curRows.length} requests · ${totalH} ❤️`,
          'current',
        ),
      );
    }
  }

  const tabs = [
    `<button type="button" class="tab active" data-tab="all" data-label="All" data-cumulative-count="" data-current-count="">All</button>`,
  ];
  for (const [tabKey, label] of TAB_DEFINITIONS) {
    const cum = cumCounts[tabKey] ?? '';
    const cur = curCounts[tabKey] ?? '';
    if (!cum && !cur) continue;
    const visible = cum ? `${label} (${cum})` : label;
    tabs.push(
      `<button type="button" class="tab" data-tab="${tabKey}" data-label="${esc(label)}" data-cumulative-count="${esc(cum)}" data-current-count="${esc(cur)}">${esc(visible)}</button>`,
    );
  }

  const today = new Date().toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });

  document.getElementById('subtitle').textContent =
    `Updated ${today} · Coverage: ${fmtMonthLabel(months[0])} → ${fmtMonthLabel(currentMonth)} · toggle Cumulative ↔ Current Month.`;

  document.getElementById('mode-cumulative-btn').textContent =
    `Cumulative · ${coverageLabel}`;
  document.getElementById('mode-current-btn').textContent =
    `Current Month · ${fmtMonthLabel(currentMonth)}`;

  document.getElementById('cum-scope').textContent =
    `Coverage: ${months.map(fmtMonthLabel).join(' → ')} (${months.length} months), rebuilt from live source comments. Hearts summed across months; songs requested in 3+ months with ≥2♥ kept even below the per-tab cutoff.`;
  document.getElementById('cur-scope').innerHTML =
    `${esc(fmtMonthLabel(currentMonth))} · from the monthly General + K-Pop request posts. Shows <b>every</b> request this month (even with no hearts yet) so your post appears as soon as you make it — duplicate requests are merged. 🔥 badges / "↩ also requested" notes show sustained multi-month demand.`;

  document.getElementById('cum-requests').textContent = String(cumTotalSongs);
  document.getElementById('cum-hearts').textContent = cumTotalHearts.toLocaleString();
  document.getElementById('cur-requests').textContent = String(curTotalSongs);
  document.getElementById('cur-hearts').textContent = curTotalHearts.toLocaleString();

  document.getElementById('tabs').innerHTML = tabs.join('');
  document.getElementById('sections').innerHTML = [...cumSections, ...curSections].join('');

  bindEvents();
  applyView();
}

function bindEvents() {
  document.querySelectorAll('.mode-btn').forEach((btn) => {
    btn.onclick = () => showMode(btn.dataset.mode);
  });
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.onclick = () => showTab(tab.dataset.tab);
  });
  const search = document.getElementById('search');
  search.oninput = () => {
    state.search = search.value;
    filterRequests(search.value);
  };
}

function showMode(mode) {
  state.mode = mode;
  document.querySelectorAll('.mode-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });
  document.querySelectorAll('.mode-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.mode === mode);
  });
  document.querySelectorAll('.tab').forEach((tab) => {
    const label = tab.dataset.label || 'All';
    const count =
      mode === 'cumulative' ? tab.dataset.cumulativeCount : tab.dataset.currentCount;
    tab.textContent = count ? `${label} (${count})` : label;
  });
  const search = document.getElementById('search');
  search.value = '';
  state.search = '';
  showTab(state.tab);
}

function showTab(tab) {
  state.tab = tab;
  document.querySelectorAll('.tab').forEach((el) => {
    el.classList.toggle('active', el.dataset.tab === tab);
  });
  applyView();
}

function filterRequests(query) {
  state.search = query;
  applyView();
}

function applyView() {
  const q = state.search.trim().toLowerCase();
  const mode = state.mode;
  const tab = state.tab;

  document.querySelectorAll('.req').forEach((row) => {
    const text = row.textContent.toLowerCase();
    row.style.display = !q || text.includes(q) ? '' : 'none';
  });

  document.querySelectorAll('.genre-section').forEach((section) => {
    const inMode = section.dataset.mode === mode;
    const tags = section.dataset.tab.split(' ');
    const inTab = tab === 'all' ? tags.includes('all') : tags.includes(tab);
    if (!inMode || !inTab) {
      section.classList.remove('active');
      section.style.display = 'none';
      return;
    }
    if (!q) {
      section.classList.add('active');
      section.style.display = '';
      return;
    }
    const visible = Array.from(section.querySelectorAll('.req')).some(
      (row) => row.style.display !== 'none',
    );
    section.classList.toggle('active', visible);
    section.style.display = visible ? '' : 'none';
  });
}

async function init() {
  const root = document.getElementById('app');
  try {
    let data;
    if (window.__TRACKER_DATA__) {
      data = window.__TRACKER_DATA__;
    } else {
      const sources = ['/api/tracker', '/data/tracker_allmonths_engine.json'];
      let lastErr = 'No data source available';
      for (const url of sources) {
        try {
          const res = await fetch(url);
          if (!res.ok) {
            lastErr = `Failed to load ${url} (${res.status})`;
            continue;
          }
          data = await res.json();
          break;
        } catch (err) {
          lastErr = err.message;
        }
      }
      if (!data) throw new Error(lastErr);
    }
    state.data = data;
    renderTracker(data);
    root.classList.remove('loading');
  } catch (err) {
    root.innerHTML = `<div class="empty-state">Could not load tracker data.<br><small>${esc(err.message)}</small></div>`;
  }
}

init();
