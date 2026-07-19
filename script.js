const ARTICLES_JSON = 'articles.json';
let allArticles = [];
let activeRegion = null;

const REGION_EMOJI = {
  'chine': '🇨🇳', 'etats-unis': '🇺🇸', 'europe': '🇪🇺', 'international': '🌍'
};

function regionFromTag(tag) {
  if (tag.includes('Chine')) return 'chine';
  if (tag.includes('États-Unis')) return 'etats-unis';
  if (tag.includes('Europe')) return 'europe';
  if (tag.includes('International')) return 'international';
  return null;
}

function regionLabel(r) {
  return { 'chine': 'Chine', 'etats-unis': 'États-Unis', 'europe': 'Europe', 'international': 'International' }[r] || r;
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

  container.innerHTML = `
    <div class="article-view">
      <div class="av-back" id="back-to-list">← Retour</div>
      <div class="av-header">
        <div class="av-date">${dateDisplay} · ${REGION_EMOJI[region]} ${brief.tag}</div>
      </div>
      <div class="av-title-cn">${brief.title_cn}</div>
      <div class="av-title-fr">${brief.title}</div>
      <div class="av-body">${brief.body}</div>
      <div class="av-source"><strong>Source :</strong> ${brief.source} · ${brief.pub_date}</div>
    </div>
  `;

  document.getElementById('back-to-list').addEventListener('click', showListView);
  window.scrollTo(0, 0);
}

function showListView() {
  const filters = document.querySelector('.filters');
  filters.style.display = 'flex';
  renderList(allArticles);
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
  const items = flattenBriefs(articles);

  container.innerHTML = items.map(item => {
    const dateDisplay = item.date.replace(/-/g, '/');
    return `
      <div class="tous-row" data-date="${item.date}" data-brief="${item.briefIndex}">
        <span class="tous-date">${dateDisplay}</span>
        <span class="tous-emoji">${REGION_EMOJI[item.region]}</span>
        <span class="tous-title-fr">${item.title}</span>
        <span class="tous-title-cn">${item.title_cn}</span>
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
  const items = flattenBriefs(articles).filter(i => i.region === activeRegion);

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
        ${byDate[d].map(item => `
          <div class="tous-row" data-date="${item.date}" data-brief="${item.briefIndex}">
            <span class="tous-title-fr" style="padding-left:16px">${item.title}</span>
          </div>
        `).join('')}
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
      applyFilters();
    })
    .catch(err => {
      document.getElementById('article-list').innerHTML =
        `<div class="empty-state">${err.message}</div>`;
    });
});
