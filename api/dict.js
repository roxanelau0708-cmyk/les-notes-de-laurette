/* Vercel serverless function — French-Chinese dictionary via frdic.com */
module.exports = async (req, res) => {
  const { word } = req.query;
  if (!word) return res.status(400).json({ error: 'missing word' });

  res.setHeader('Access-Control-Allow-Origin', '*');

  try {
    let html = '';

    // Try direct URL first (GET)
    const url = `https://www.frdic.com/dicts/fr/${encodeURIComponent(word)}`;
    const r = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36' } });
    if (r.ok) {
      html = await r.text();
    }

    let data = parse(html, word);
    if (data && (data.definitions?.length || data.synonyms?.length)) {
      return res.json(data);
    }

    // Fallback: POST search (handles apostrophes, special chars)
    const r2 = await fetch('https://www.frdic.com/', {
      method: 'POST',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: `inputword=${encodeURIComponent(word)}&searchtype=search_dict`,
    });
    if (!r2.ok) {
      return res.json({ word, not_found: true });
    }
    html = await r2.text();
    data = parse(html, word);
    if (!data || (!data.definitions?.length && !data.synonyms?.length)) {
      return res.json({ word, not_found: true });
    }
    return res.json(data);
  } catch (e) {
    return res.status(502).json({ error: e.message });
  }
};

function unent(s) {
  if (!s) return '';
  return s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ').replace(/<br\s*\/?>/gi, ' ').replace(/<[^>]*(?:>|$)/g, '').replace(/\s+/g, ' ').trim();
}

function extractBetween(text, start, end) {
  const i = text.indexOf(start);
  if (i === -1) return '';
  const j = text.indexOf(end, i + start.length);
  if (j === -1) return text.slice(i + start.length);
  return text.slice(i + start.length, j);
}

/* Extract content of <span class="X">...</span> with proper nesting depth */
function extractSpans(text, className) {
  const results = [];
  const openTag = `<span class="${className}">`;
  let i = 0;
  while ((i = text.indexOf(openTag, i)) !== -1) {
    let depth = 1;
    let j = i + openTag.length;
    while (depth > 0 && j < text.length) {
      if (text[j] === '<') {
        if (text.startsWith('</span>', j)) depth--;
        else if (text.startsWith('<span ', j)) depth++;
        j++;
      } else {
        j++;
      }
    }
    results.push(text.slice(i + openTag.length, j - 7));
    i = j;
  }
  return results;
}

/* Extract eg span content, parsing trans sub-spans */
function extractEgWithTrans(text) {
  const results = [];
  const openTag = '<span class="eg">';
  let i = 0;
  while ((i = text.indexOf(openTag, i)) !== -1) {
    let depth = 1;
    let j = i + openTag.length;
    while (depth > 0 && j < text.length) {
      if (text[j] === '<') {
        if (text.startsWith('</span>', j)) depth--;
        else if (text.startsWith('<span ', j)) depth++;
        j++;
      } else {
        j++;
      }
    }
    const raw = text.slice(i + openTag.length, j - 7);

    // Extract trans content if present
    const transTag = '<span class="trans">';
    const ti = raw.indexOf(transTag);
    if (ti !== -1) {
      let td = 1;
      let tj = ti + transTag.length;
      while (td > 0 && tj < raw.length) {
        if (raw[tj] === '<') {
          if (raw.startsWith('</span>', tj)) td--;
          else if (raw.startsWith('<span ', tj)) td++;
          tj++;
        } else {
          tj++;
        }
      }
      const fr = unent(raw.slice(0, ti));
      const zh = unent(raw.slice(ti + transTag.length, tj - 7));
      if (fr && zh) results.push({ fr, zh });
    } else {
      results.push({ fr: unent(raw), zh: '' });
    }
    i = j;
  }
  return results;
}

function parse(html, word) {
  const data = { word, phonetic: '', definitions: [], common_usages: [], synonyms: [], antonyms: [], related_words: [], sentences: [], has_conjugation: false, conjugation_url: null };

  // Phonetic
  const ph = html.match(/class=Phonitic>\[([^\]]+)\]<\//i);
  if (ph) data.phonetic = ph[1];

  // Conjugation hint
  if (html.includes('动词变位') || html.includes('forcecg=true') || html.includes('/dicts/cg/')) {
    data.has_conjugation = true;
    data.conjugation_url = `https://www.frdic.com/dicts/cg/${encodeURIComponent(word)}?forcecg=true`;
  }

  // === 法汉-汉法词典 definitions ===
  const fcSection = extractBetween(html, 'id="ExpFCchild"', 'id="ExpSYN"');
  if (fcSection) {
    // Separate common usages section
    const commonIdx = fcSection.indexOf('<b>常见用法</b>');
    const mainSection = commonIdx !== -1 ? fcSection.slice(0, commonIdx) : fcSection;
    const commonSection = commonIdx !== -1 ? fcSection.slice(commonIdx) : '';

    // Parse common usages — split by <br> into individual phrases
    if (commonSection) {
      data.common_usages = [];
      const rawLines = commonSection.split(/<br\s*\/?>/i);
      for (const line of rawLines) {
        const cleaned = unent(line);
        if (!cleaned || cleaned === '常见用法') continue;
        // Try to split FR and ZH at first CJK character
        const m = cleaned.match(/^(.+?)([一-鿿㐀-䶿豈-﫿　-〿＀-￯].*)$/);
        if (m) {
          data.common_usages.push({ fr: m[1].trim(), zh: m[2].trim() });
        } else {
          data.common_usages.push({ fr: cleaned, zh: '' });
        }
      }
    }

    // Split main section by cara (part of speech)
    const caraSpans = extractSpans(mainSection, 'cara');
    const caraTexts = caraSpans.map(s => unent(s));

    // Split the main section into blocks at each cara position
    const caraTag = '<span class="cara">';
    const blocks = [];
    let pos = 0;
    while (pos < mainSection.length) {
      const nextCara = mainSection.indexOf(caraTag, pos);
      if (nextCara === -1) break;
      const caraEnd = mainSection.indexOf('</span>', nextCara);
      if (caraEnd === -1) break;
      const posText = unent(mainSection.slice(nextCara + caraTag.length, caraEnd));
      const blockStart = nextCara;
      // Find next cara or end
      const nextCara2 = mainSection.indexOf(caraTag, nextCara + 1);
      const blockEnd = nextCara2 !== -1 ? nextCara2 : mainSection.length;
      const block = mainSection.slice(blockStart, blockEnd);
      blocks.push({ pos: posText, html: block });
      pos = blockEnd;
    }

    // Process each block
    for (const block of blocks) {
      // Extract meanings from exp spans
      const expContents = extractSpans(block.html, 'exp');
      let meaning = expContents.map(s => unent(s)).filter(Boolean).join(' ');

      // If no exp spans, try plain text fallback
      if (!meaning) {
        meaning = unent(block.html.replace(/<span class="cara">[^<]*<\/span>/, '').replace(/<span class="eg">.*?<\/span>/gs, '').replace(/<br\s*\/?>/g, ' ').replace(/<[^>]+>/g, ''));
      }

      // Extract examples
      const examples = extractEgWithTrans(block.html);

      if (meaning) {
        data.definitions.push({ pos: block.pos, meaning, examples });
      }
    }
  }

  // === Synonyms / Antonyms ===
  const synSection = extractBetween(html, 'id="ExpSYNchild"', 'id="ExpLJ"');
  if (synSection) {
    const synMatch = synSection.match(/近义词：<\/h5>([^<]*(?:<[^>]+>[^<]*)*?)(?=<h5|$)/);
    if (synMatch) {
      const synLinks = synMatch[1].match(/<a[^>]*>([^<]+)<\/a>/g);
      if (synLinks) data.synonyms = synLinks.map(l => l.replace(/<[^>]+>/g, '').trim()).filter(Boolean);
    }

    const antMatch = synSection.match(/反义词：<\/h5>([^<]*(?:<[^>]+>[^<]*)*?)(?=<h5|$)/);
    if (antMatch) {
      const antLinks = antMatch[1].match(/<a[^>]*>([^<]+)<\/a>/g);
      if (antLinks) data.antonyms = antLinks.map(l => l.replace(/<[^>]+>/g, '').trim()).filter(Boolean);
    }

    const relMatch = synSection.match(/<div class="eudic_wordtype_cont">(.*?)<\/div>/s);
    if (relMatch) {
      const wordRegex = /<a[^>]*>([^<]+)<\/a><span>([^<]*)<\/span>/g;
      let wm;
      while ((wm = wordRegex.exec(relMatch[1])) !== null) {
        data.related_words.push({ word: unent(wm[1]), meaning: unent(wm[2]) });
      }
    }
  }

  // === Example sentences ===
  const ljSection = extractBetween(html, 'id="ExpLJchild"', 'class="explain-word-info"');
  if (ljSection) {
    const sentenceRegex = /<p class="line">(.*?)<\/p>\s*<p class="exp">(.*?)<\/p>/gs;
    let sm;
    while ((sm = sentenceRegex.exec(ljSection)) !== null) {
      const fr = unent(sm[1].replace(/<span[^>]*>/g, '').replace(/<\/span>/g, ''));
      const zh = unent(sm[2].replace(/<span[^>]*>/g, '').replace(/<\/span>/g, ''));
      if (fr && zh && data.sentences.length < 15) {
        data.sentences.push({ fr, zh });
      }
    }
  }

  return data;
}
