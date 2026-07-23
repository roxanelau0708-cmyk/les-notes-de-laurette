const ARTICLES_JSON = 'articles.json';
let allArticles = [];
let activeRegion = null;

const REGION_EMOJI = {
  'chine': '🇨🇳', 'etats-unis': '🇺🇸', 'europe': '🇪🇺', 'international': '🌍', 'francophonie': '🇫🇷'
};

function regionFromTag(tag) {
  if (tag.includes('Chine')) return 'chine';
  if (tag.includes('États-Unis')) return 'etats-unis';
  if (tag.includes('Europe')) return 'europe';
  if (tag.includes('International')) return 'international';
  if (tag.includes('Québec') || tag.includes('Suisse') || tag.includes('Belgique') || tag.includes('Afrique') || tag.includes('Francophonie')) return 'francophonie';
  // Tags without explicit region → Francophonie
  return 'francophonie';
}

function regionLabel(r) {
  return { 'chine': 'Chine', 'etats-unis': 'États-Unis', 'europe': 'Europe', 'international': 'International', 'francophonie': 'Francophonie' }[r] || r;
}

function isRead(date, briefIndex) {
  return localStorage.getItem(`read_${date}_${briefIndex}`) === 'true';
}

function isHideRead() {
  return document.getElementById('hide-read')?.checked === true;
}

// === Flatten briefs ===
function flattenBriefs(articles) {
  const items = [];
  articles.forEach(a => {
    a.briefs.forEach((b, idx) => {
      items.push({
        date: a.date,
        region: regionFromTag(b.tag) || 'international',
        topic: b.tag.split(' / ')[0],
        title_cn: b.title_cn,
        title: b.title,
        briefIndex: idx,
        sourceArticle: a,
      });
    });
  });
  return items;
}

// ========== VIEWS ==========

function showArticleView(article, briefIndex) {
  const brief = article.briefs[briefIndex];
  if (!brief) return;

  const container = document.getElementById('article-list');
  const filters = document.querySelector('.filters');
  const count = document.getElementById('article-count');

  filters.style.display = 'none';
  if (count) count.style.display = 'none';

  const dateDisplay = article.date.replace(/-/g, '/');
  const region = regionFromTag(brief.tag);
  const noteKey = `note_${article.date}_${briefIndex}`;
  const readKey = `read_${article.date}_${briefIndex}`;
  const savedNote = localStorage.getItem(noteKey) || '';
  const isRead = localStorage.getItem(readKey) === 'true';

  container.innerHTML = `
    <div class="article-view">
      <div class="av-back" id="back-to-list">← Retour</div>
      <div class="av-header">
        <div class="av-date">${dateDisplay} · ${REGION_EMOJI[region]} ${brief.tag}
        ${brief.auto ? '<span class="auto-badge auto">Auto</span>' : '<span class="auto-badge editorial">Rédaction</span>'}
        ${isRead ? '<span class="read-badge">✓ Lu</span>' : ''}
      </div>
      </div>
      ${brief.title_cn ? `<div class="av-title-cn">${brief.title_cn}</div>` : ''}
      <div class="av-title-fr">${brief.title}</div>
      <div class="av-body">${brief.body}</div>
      <div class="av-source"><strong>Source :</strong> ${brief.source} · ${brief.pub_date}</div>
      <div class="av-notes">
        <div class="av-notes-bar">
          <button class="av-read-btn" id="mark-read-btn">${isRead ? '✓ Lu' : '☐ Marquer comme lu'}</button>
          <span class="av-notes-label">📝 Notes</span>
        </div>
        <textarea class="av-notes-input" id="notes-input" rows="4" placeholder="Prendre une note…">${savedNote}</textarea>
        <div class="av-notes-footer">
          <span class="av-notes-status" id="notes-status"></span>
          <button class="av-notes-del" id="notes-del">Supprimer la note</button>
        </div>
      </div>
    </div>
  `;

  document.getElementById('back-to-list').addEventListener('click', showListView);
  window.scrollTo(0, 0);

  // Mark as read
  document.getElementById('mark-read-btn').addEventListener('click', () => {
    const newVal = localStorage.getItem(readKey) !== 'true';
    localStorage.setItem(readKey, newVal);
    // Re-render to update UI
    showArticleView(article, briefIndex);
  });

  // Auto-save notes
  const notesInput = document.getElementById('notes-input');
  let saveTimer;
  notesInput.addEventListener('input', () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      localStorage.setItem(noteKey, notesInput.value);
      document.getElementById('notes-status').textContent = '✓ Sauvegardé';
      setTimeout(() => {
        const st = document.getElementById('notes-status');
        if (st) st.textContent = '';
      }, 1500);
    }, 500);
  });

  // Delete note
  document.getElementById('notes-del').addEventListener('click', () => {
    if (notesInput.value.trim()) {
      localStorage.removeItem(noteKey);
      notesInput.value = '';
      document.getElementById('notes-status').textContent = '✓ Note supprimée';
    }
  });

  // Reset dict UI when entering article view
  const dictResults = document.getElementById('dict-results');
  const dictBack = document.getElementById('dict-back');
  dictResults.classList.remove('active');
  dictResults.innerHTML = '';
  dictBack.style.display = 'none';
  document.getElementById('dict-status').textContent = '';

  window._articleView = { article, briefIndex };
}

function showListView() {
  const filters = document.querySelector('.filters');
  filters.style.display = 'flex';
  renderList(allArticles);

  // Reset dict UI when returning to list
  const dr = document.getElementById('dict-results');
  dr.classList.remove('active');
  dr.innerHTML = '';
  document.getElementById('dict-back').style.display = 'none';
  document.getElementById('dict-status').textContent = '';

  window._articleView = null;
}

// ========== LIST RENDER ==========

function renderList(articles) {
  const container = document.getElementById('article-list');

  if (articles.length === 0) {
    container.innerHTML = '<div class="empty-state">Aucun article.</div>';
    return;
  }

  if (activeRegion) {
    renderRegionalView(articles, container);
  } else {
    renderTousView(articles, container);
  }
}

function renderTousView(articles, container) {
  let items = flattenBriefs(articles);
  if (isHideRead()) {
    items = items.filter(item => !isRead(item.date, item.briefIndex));
  }
  if (items.length === 0) {
    container.innerHTML = '<div class="empty-state">Tout est lu ! ✅</div>';
    return;
  }

  container.innerHTML = items.map(item => {
    const dateDisplay = item.date.replace(/-/g, '/');
    const titleCn = item.title_cn || '';
    const read = isRead(item.date, item.briefIndex);
    return `
      <div class="tous-row ${read ? 'read' : ''}" data-date="${item.date}" data-brief="${item.briefIndex}">
        <span class="tous-date">${dateDisplay}</span>
        <span class="tous-emoji">${REGION_EMOJI[item.region]}</span>
        <span class="tous-title-fr">${item.title}</span>
        ${titleCn ? `<span class="tous-title-cn">${titleCn}</span>` : ''}
        ${read ? '<span class="read-badge">✓</span>' : ''}
      </div>
    `;
  }).join('');

  container.querySelectorAll('.tous-row').forEach(el => {
    el.addEventListener('click', () => {
      const article = allArticles.find(a => a.date === el.dataset.date);
      if (article) showArticleView(article, parseInt(el.dataset.brief));
    });
  });
}

function renderRegionalView(articles, container) {
  let items = flattenBriefs(articles).filter(i => i.region === activeRegion);
  if (isHideRead()) {
    items = items.filter(item => !isRead(item.date, item.briefIndex));
  }

  if (items.length === 0) {
    container.innerHTML = '<div class="empty-state">Tout est lu ! ✅</div>';
    return;
  }
  const byDate = {};
  items.forEach(item => {
    if (!byDate[item.date]) byDate[item.date] = [];
    byDate[item.date].push(item);
  });
  const sortedDates = Object.keys(byDate).sort().reverse();

  container.innerHTML = sortedDates.map(d => {
    const dateDisplay = d.replace(/-/g, '/');
    return `
      <div class="region-date-group">
        <div class="region-date-header">${dateDisplay}</div>
        ${byDate[d].map(item => {
          const read = isRead(item.date, item.briefIndex);
          return `
          <div class="tous-row ${read ? 'read' : ''}" data-date="${item.date}" data-brief="${item.briefIndex}">
            <span class="tous-title-fr" style="padding-left:16px">${item.title}</span>
            ${item.sourceArticle?.briefs?.[item.briefIndex]?.auto ? '<span class="auto-badge auto">Auto</span>' : ''}
            ${read ? '<span class="read-badge">✓</span>' : ''}
          </div>`;
        }).join('')}
      </div>
    `;
  }).join('');

  container.querySelectorAll('.tous-row').forEach(el => {
    el.addEventListener('click', () => {
      const article = allArticles.find(a => a.date === el.dataset.date);
      if (article) showArticleView(article, parseInt(el.dataset.brief));
    });
  });
}

// ========== FILTERS ==========

function setupFilters() {
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const filter = btn.dataset.filter;

      if (filter === 'all') {
        activeRegion = null;
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        applyFilters();
        return;
      }

      btn.classList.toggle('active');
      if (btn.classList.contains('active')) {
        document.querySelectorAll('.filter-btn.region').forEach(b => {
          if (b !== btn) b.classList.remove('active');
        });
        activeRegion = filter;
      } else {
        activeRegion = null;
      }

      document.querySelector('[data-filter="all"]').classList.toggle('active', !activeRegion);
      applyFilters();
    });
  });
}

function applyFilters() {
  let filtered = allArticles;
  if (activeRegion) {
    filtered = filtered.filter(a =>
      a.briefs.some(b => regionFromTag(b.tag) === activeRegion)
    );
  }
  renderList(filtered);
}

// ========== MARKET DATA (CNBC-style) ==========

const MARKET_SYMBOLS = [
  { id: '%5EGSPC', label: 'S&P 500' },
  { id: '%5ENDX', label: 'NASDAQ 100' },
  { id: '%5ERUT', label: 'Russell 2000' },
  { id: '000300.SS', label: 'CSI 300' },
  { id: '000905.SS', label: 'CSI 500' },
  { id: 'HSTECH.HK', label: 'HSTECH' },
];

function sparklineSVG(closes, up) {
  const w = 120, h = 32;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const pts = closes.map((c, i) => {
    const x = (i / (closes.length - 1)) * w;
    const y = h - ((c - min) / range) * (h - 4) - 2;
    return `${x},${y}`;
  });
  const color = up ? '#dc2626' : '#16a34a';
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="display:block"><polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
}

function formatPrice(v) {
  return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

async function fetchMarketData() {
  const bar = document.getElementById('market-bar');
  if (!bar) return;

  const PROXY = '/api/yahoo?symbol=';

  function fetchYahoo(symbol, interval, range) {
    return fetch(`${PROXY}${symbol}&interval=${interval}&range=${range}`)
      .then(r => { if (!r.ok) throw new Error(r.statusText); return r.json(); });
  }

  // Step 1: fetch intraday data (fast, for price + change)
  const results = await Promise.allSettled(MARKET_SYMBOLS.map(s =>
    fetchYahoo(s.id, s.interval || '5m', s.range || '1d')
  ));

  // Step 2: for symbols with no intraday sparkline, fallback
  const fallbacks = [];
  results.forEach((r, i) => {
    if (r.status !== 'fulfilled') { fallbacks.push(i); return; }
    const closes = r.value?.chart?.result?.[0]?.indicators?.quote?.[0]?.close;
    const valid = closes ? closes.filter(c => c != null).length : 0;
    if (valid < 2) fallbacks.push(i);
  });
  const fallbackPromises = fallbacks.map(i => {
    return fetchYahoo(MARKET_SYMBOLS[i].id, '1d', '1mo');
  });
  const fallbackResults = await Promise.allSettled(fallbackPromises);
  const fallbackMap = {};
  fallbacks.forEach((i, j) => { fallbackMap[i] = fallbackResults[j]; });

  let html = '';
  MARKET_SYMBOLS.forEach((s, i) => {
    const r = results[i];
    if (r.status !== 'fulfilled' || !r.value?.chart?.result?.[0]) {
      html += `<div class="mc-card"><div class="mc-name">${s.label}</div><div class="mc-price">—</div></div>`;
      return;
    }
    try {
      const d = r.value.chart.result[0];
      const meta = d.meta;
      const quote = d.indicators.quote[0];
      const closes = quote.close;
      const current = meta.regularMarketPrice ?? closes.filter(c => c != null).pop();
      const prev = meta.chartPreviousClose;
      const chg = current - prev;
      const pct = (chg / prev) * 100;
      const up = chg >= 0;
      const arrow = up ? '▲' : '▼';

      // Try intraday sparkline first; fallback to 1mo daily
      let spark = '';
      const validCloses = closes.filter(c => c != null);
      if (validCloses.length > 1) {
        spark = sparklineSVG(validCloses, up);
      } else if (fallbackMap[i]?.status === 'fulfilled') {
        const f = fallbackMap[i].value?.chart?.result?.[0];
        if (f) {
          const dailyCloses = f.indicators.quote[0].close.filter(c => c != null);
          if (dailyCloses.length > 1) spark = sparklineSVG(dailyCloses, up);
        }
      }

      html += `<div class="mc-card ${up ? 'mc-up' : 'mc-down'}">
        <div class="mc-name">${s.label}</div>
        <div class="mc-price">${formatPrice(current)}</div>
        <div class="mc-chg"><span class="mc-arrow">${arrow}</span> ${formatPrice(Math.abs(chg))} (${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%)</div>
        <div class="mc-spark">${spark}</div>
      </div>`;
    } catch (e) {
      html += `<div class="mc-card"><div class="mc-name">${s.label}</div><div class="mc-price">—</div></div>`;
    }
  });

  bar.innerHTML = `<div class="market-track">${html}</div>`;
  // Duplicate cards for seamless infinite scroll
  const track = bar.querySelector('.market-track');
  track.innerHTML += track.innerHTML;
  startAutoScroll(bar);
}

// ========== AUTO-SCROLL ==========

let autoScrollId = null;

function startAutoScroll(bar) {
  if (autoScrollId) cancelAnimationFrame(autoScrollId);

  const track = bar.querySelector('.market-track');
  if (!track) return;

  const totalDist = track.scrollWidth / 2;
  if (totalDist <= 0) return;

  const duration = 18750;
  let startTime = null;
  let paused = false;
  let resumeTimer = null;

  const pause = () => { paused = true; clearTimeout(resumeTimer); };
  const resume = () => { paused = false; };

  bar.addEventListener('mouseenter', pause);
  bar.addEventListener('mouseleave', resume);

  function step(timestamp) {
    if (!startTime) startTime = timestamp;
    if (!paused) {
      const elapsed = timestamp - startTime;
      const progress = (elapsed % duration) / duration;
      track.style.transform = `translateX(${-progress * totalDist}px)`;
    } else {
      startTime = null;
    }
    autoScrollId = requestAnimationFrame(step);
  }
  autoScrollId = requestAnimationFrame(step);
}

// ========== INIT ==========

document.addEventListener('DOMContentLoaded', () => {
  fetchMarketData();
  setInterval(fetchMarketData, 120000); // refresh every 2 min (avoid rate limits)

  fetch(ARTICLES_JSON)
    .then(r => { if (!r.ok) throw new Error('Failed to load'); return r.json(); })
    .then(data => {
      allArticles = data;
      setupFilters();
      document.getElementById('hide-read').addEventListener('change', applyFilters);
      applyFilters();
    })
    .catch(err => {
      document.getElementById('article-list').innerHTML =
        `<div class="empty-state">⚠️ ${err.message}</div>`;
    });

  initDict();
});

// ========== DICTIONARY ==========

const DICT_API = '/api/dict?word=';

function initDict() {
  const form = document.getElementById('dict-form');
  const input = document.getElementById('dict-input');
  const backBtn = document.getElementById('dict-back');
  const resultsEl = document.getElementById('dict-results');
  const statusEl = document.getElementById('dict-status');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const word = input.value.trim().toLowerCase();
    if (!word) return;
    doDictSearch(word);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeDict();
    }
  });

  // Keyboard shortcut: press / to focus search (only when dict-bar is visible)
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const tag = document.activeElement?.tagName;
      if (tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT') {
        const db = document.querySelector('.dict-bar');
        if (db && db.style.display !== 'none') {
          e.preventDefault();
          input.focus();
        }
      }
    }
  });

  backBtn.addEventListener('click', closeDict);

  function closeDict() {
    const resultsEl = document.getElementById('dict-results');
    const statusEl = document.getElementById('dict-status');
    const backBtn = document.getElementById('dict-back');
    resultsEl.classList.remove('active');
    resultsEl.innerHTML = '';
    backBtn.style.display = 'none';
    statusEl.textContent = '';

    if (window._articleView) {
      // Return to article
      showArticleView(window._articleView.article, window._articleView.briefIndex);
    } else {
      document.querySelector('.filters').style.display = 'flex';
      window.scrollTo(0, 0);
    }
  }

  window.doDictSearch = async function(word) {
    const input = document.getElementById('dict-input');
    const resultsEl = document.getElementById('dict-results');
    const backBtn = document.getElementById('dict-back');
    const statusEl = document.getElementById('dict-status');
    input.value = word;
    document.querySelector('.filters').style.display = 'none';
    backBtn.style.display = 'inline';
    resultsEl.classList.add('active');
    resultsEl.innerHTML = '<div class="dr-loading">Recherche en cours…</div>';
    statusEl.textContent = `Recherche de « ${word} »…`;
    window.scrollTo(0, 0);

    try {
      const r = await fetch(DICT_API + encodeURIComponent(word));
      if (!r.ok) throw new Error('Erreur serveur');
      const data = await r.json();

      if (data.not_found) {
        resultsEl.innerHTML = `<div class="dr-not-found"><strong>« ${word} »</strong> introuvable. Essayez un autre mot.</div>`;
        statusEl.textContent = `Aucun résultat pour « ${word} ».`;
        return;
      }

      renderDictResult(data, resultsEl);
      statusEl.textContent = `Résultat pour « ${word} »`;
    } catch (err) {
      resultsEl.innerHTML = `<div class="dr-error">Erreur : ${err.message}</div>`;
      statusEl.textContent = 'Erreur de recherche.';
    }
  };
}

function renderDictResult(data, el) {
  const parts = [];

  // Word + phonetic
  let headerHtml = `<div class="dr-word">${escHtml(data.word)}</div>`;
  if (data.phonetic) {
    const audioUrl = `https://www.frdic.com/dicts/fr/${encodeURIComponent(data.word)}`;
    headerHtml += `<div class="dr-phonetic">[${escHtml(data.phonetic)}] <a class="dr-audio" href="${audioUrl}" target="_blank" rel="noopener">🔊 发音</a></div>`;
  }
  headerHtml += `<hr class="dr-divider">`;
  parts.push(headerHtml);

  // Definitions
  if (data.definitions && data.definitions.length > 0) {
    let defHtml = `<div class="dr-section">`;
    defHtml += `<div class="dr-section-title">法汉词典</div>`;
    data.definitions.forEach(def => {
      defHtml += `<div class="dr-def">`;
      if (def.pos) defHtml += `<div class="dr-pos">${escHtml(def.pos)}</div>`;
      // Split numbered meanings into separate lines
      const lines = def.meaning.split(/(?=\d+\.)/).filter(Boolean);
      defHtml += `<div class="dr-meaning">${lines.map(l => escHtml(l).trim()).join('<br>')}</div>`;
      if (def.examples && def.examples.length > 0) {
        defHtml += `<div class="dr-examples">`;
        def.examples.slice(0, 3).forEach(ex => {
          defHtml += `<div class="dr-example"><div class="dr-ex-fr">${escHtml(ex.fr)}</div>`;
          if (ex.zh) defHtml += `<div class="dr-ex-zh">${escHtml(ex.zh)}</div>`;
          defHtml += `</div>`;
        });
        defHtml += `</div>`;
      }
      defHtml += `</div>`;
    });
    defHtml += `</div>`;
    parts.push(defHtml);
  }

  // Common usages (max 6)
  if (data.common_usages && data.common_usages.length > 0) {
    let cuHtml = `<div class="dr-section">`;
    cuHtml += `<div class="dr-section-title">常见用法</div>`;
    data.common_usages.slice(0, 6).forEach(u => {
      cuHtml += `<div class="dr-usage"><div>${escHtml(u.fr)}</div>`;
      if (u.zh) cuHtml += `<div class="dr-u-zh">${escHtml(u.zh)}</div>`;
      cuHtml += `</div>`;
    });
    cuHtml += `</div>`;
    parts.push(cuHtml);
  }

  // Synonyms & Antonyms
  if ((data.synonyms && data.synonyms.length > 0) || (data.antonyms && data.antonyms.length > 0)) {
    let saHtml = `<div class="dr-section">`;
    if (data.synonyms && data.synonyms.length > 0) {
      saHtml += `<div class="dr-section-title">近义词</div>`;
      saHtml += `<div class="dr-wordlist">`;
      data.synonyms.slice(0, 2).forEach(s => {
        saHtml += `<a href="#" class="dict-search-link" data-word="${escAttr(s)}">${escHtml(s)}</a>`;
      });
      saHtml += `</div>`;
    }
    if (data.antonyms && data.antonyms.length > 0) {
      saHtml += `<div style="margin-top:10px"><div class="dr-section-title">反义词</div>`;
      saHtml += `<div class="dr-wordlist">`;
      data.antonyms.slice(0, 2).forEach(a => {
        saHtml += `<a href="#" class="dict-search-link" data-word="${escAttr(a)}">${escHtml(a)}</a>`;
      });
      saHtml += `</div></div>`;
    }
    saHtml += `</div>`;
    parts.push(saHtml);
  }

  // Related words
  if (data.related_words && data.related_words.length > 0) {
    let rwHtml = `<div class="dr-section">`;
    rwHtml += `<div class="dr-section-title">联想词</div>`;
    rwHtml += `<div class="dr-related">`;
    data.related_words.forEach(rw => {
      rwHtml += `<span><a href="#" class="dict-search-link" data-word="${escAttr(rw.word)}">${escHtml(rw.word)}</a>`;
      if (rw.meaning) rwHtml += `<span class="dr-r-zh">${escHtml(rw.meaning)}</span>`;
      rwHtml += `</span>`;
    });
    rwHtml += `</div></div>`;
    parts.push(rwHtml);
  }

  // Conjugation link
  if (data.has_conjugation) {
    parts.push(`<div class="dr-section"><div class="dr-section-title">动词变位</div><a class="dr-conj-link" href="${escAttr(data.conjugation_url)}" target="_blank" rel="noopener">查看 ${escHtml(data.word)} 的变位 →</a></div>`);
  }

  // Example sentences
  if (data.sentences && data.sentences.length > 0) {
    let senHtml = `<div class="dr-section">`;
    senHtml += `<div class="dr-section-title">例句</div>`;
    data.sentences.slice(0, 6).forEach(s => {
      senHtml += `<div class="dr-sentence"><div class="dr-s-fr">${escHtml(s.fr)}</div><div class="dr-s-zh">${escHtml(s.zh)}</div></div>`;
    });
    senHtml += `</div>`;
    parts.push(senHtml);
  }

  el.innerHTML = parts.join('');

  // Click delegation for dict search links
  el.querySelectorAll('.dict-search-link').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      doDictSearch(link.dataset.word);
    });
  });
}

function escHtml(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function escAttr(s) {
  if (!s) return '';
  return escHtml(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
