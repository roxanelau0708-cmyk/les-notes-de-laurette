#!/usr/bin/env python3
"""
fetch-rss.py — RSS 新闻聚合器
每天从法语媒体抓取资讯，自动翻译标题/摘要为中文，更新 articles.json
使用 Python 标准库，无外部依赖
"""

import gzip
import json
import os
import re
import sys
import unicodedata
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, date, timezone
from html import unescape

# ── 信源配置 ──
# 锁定 5 家指定信源，不再订阅杂源
SOURCES = [
    {"url": "https://www.lemonde.fr/rss/une.xml",       "region": "francophonie",  "tag": "Actualité", "label": "Le Monde"},
    {"url": "https://www.francetvinfo.fr/titres.rss",   "region": "francophonie",  "tag": "Actualité", "label": "France Info"},
    {"url": "https://www.rfi.fr/fr/rss",                "region": "international", "tag": "Actualité", "label": "RFI"},
    {"url": "https://www.latribune.fr/feed.xml",        "region": "francophonie",  "tag": "Économie",   "label": "La Tribune"},
    {"url": "https://www.slate.fr/rss.xml",             "region": "francophonie",  "tag": "Culture",    "label": "Slate.fr"},
]

# ── 路径 ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.dirname(SCRIPT_DIR)
ARTICLES_PATH = os.path.join(SITE_DIR, "articles.json")

# ── 正文目标 ──
TARGET_WORDS = 300      # 每篇正文目标词数
MIN_BODY_WORDS = 120    # 低于此词数视为缺乏实质内容，剔除

# ── RSS 抓取 ──

def fetch_url(url, timeout=20):
    """带超时、User-Agent、gzip 和 SSL 降级的 HTTP GET"""
    import ssl

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "Accept-Encoding": "gzip, deflate",
        }
    )
    for ctx in (ssl.create_default_context(), ssl._create_unverified_context()):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                if resp.status >= 400:
                    print(f"    HTTP {resp.status}")
                    continue
                raw = resp.read()
                # 手动解压 gzip/deflate（Python 3.9 urllib 不会自动解压）
                encoding = resp.headers.get("Content-Encoding", "")
                if "gzip" in encoding:
                    raw = gzip.decompress(raw)
                elif "deflate" in encoding:
                    import zlib
                    raw = zlib.decompress(raw)
                return raw
        except Exception as e:
            en = type(e).__name__
            msg = str(e).lower()
            if ("certificate" in en.lower() or "ssl" in en.lower()
                    or "ssl" in msg or "certificate" in msg or "eof" in msg
                    or "handshake" in msg):
                continue  # SSL 错误 → 降级重试
            print(f"    ⚠ {en}: {e}")
            return None
    print(f"    ⚠ SSL échoué (même après fallback)")
    return None


def parse_date_str(date_str):
    """将各种日期格式解析为 datetime"""
    if not date_str:
        return None
    date_str = date_str.strip()
    # RSS 标准格式: Mon, 01 Jan 2026 10:00:00 +0000
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    # Atom ISO 格式
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def parse_rss(xml_data):
    """解析 RSS 2.0 / Atom 格式，返回 item 列表（含分类标签）"""
    items = []
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        print(f"    XML parse error: {e}")
        return items

    # ── RSS 2.0 ──
    for item in root.iter("item"):
        title = _clean_html(unescape(item.findtext("title", "") or ""))
        desc = _clean_html(unescape(item.findtext("description", "") or ""))
        pub = item.findtext("pubDate", "") or ""
        link = item.findtext("link", "") or ""
        cats = [c.text.strip() for c in item.iter("category") if c.text]
        if title:
            items.append({
                "title": title.strip(),
                "desc": desc[:600].strip(),
                "pub_date": pub.strip(),
                "link": link.strip(),
                "categories": cats,
            })

    # ── Atom ──
    if not items:
        ns = "{http://www.w3.org/2005/Atom}"
        for entry in root.iter(f"{ns}entry"):
            title_el = entry.find(f"{ns}title")
            title = _clean_html(unescape(title_el.text or "")) if title_el is not None else ""
            desc = ""
            for tag in (f"{ns}content", f"{ns}summary"):
                el = entry.find(tag)
                if el is not None and el.text:
                    desc = _clean_html(unescape(el.text))
                    break
            pub = ""
            for tag in (f"{ns}published", f"{ns}updated"):
                el = entry.find(tag)
                if el is not None and el.text:
                    pub = el.text
                    break
            link = ""
            link_el = entry.find(f"{ns}link")
            if link_el is not None:
                link = link_el.get("href", "")
            cats = []
            for cat in entry.iter(f"{ns}category"):
                term = cat.get("term", "") or cat.get("label", "")
                if term:
                    cats.append(term.strip())
            if title:
                items.append({
                    "title": title.strip(),
                    "desc": desc[:600].strip(),
                    "pub_date": pub.strip(),
                    "link": link.strip(),
                    "categories": cats,
                })

    return items


def _clean_html(text):
    """去除 HTML 标签"""
    return re.sub(r"<[^>]+>", "", text).strip()


def first_clause_cn(text, max_len=45):
    """取中文文本第一个分句（句末/逗号前），用于提炼短标题"""
    text = (text or "").strip()
    for sep in "。！？；":
        i = text.find(sep)
        if i != -1:
            text = text[:i]
    if len(text) > max_len:
        i = text.find("，")
        if i != -1 and i <= max_len:
            text = text[:i]
    return text.strip()[:max_len]


def make_title_cn(fr_title, summary_cn):
    """中文标题：完整翻译原标题；原标题过长(句子式)则从中文正文首句提炼"""
    title_cn = translate(fr_title).strip() if fr_title else ""
    if title_cn and len(title_cn) <= 45:
        return title_cn
    if summary_cn:
        t = first_clause_cn(summary_cn, 45)
        if 8 <= len(t) <= 45:
            return t
    return title_cn[:45] if title_cn else ""


GEO_RULES = [
    # 国际冲突 / 重大国际事件（优先，避免被具体国家名抢走）
    (["moyen-orient", "iran", "israel", "gaza", "palestine",
      "hezbollah", "hamas", "teheran", "jordanie", "koweit",
      "irak", "syrie", "yemen",
      "ukraine", "russie", "moscou", "kiev", "crimee", "belgorod",
      "otan", "onu", "nations unies",
      "afghanistan", "coree du nord", "inde", "bresil",
      "japon", "tokyo", "birmanie", "soudan"], "international"),
    # 具体地区
    (["chine", "chinois", "pekin", "shanghai", "shenzhen",
      "xi jinping", "taiwan", "hong kong"], "chine"),
    (["etats-unis", "etats unis",
      "americain", "washington", "new york",
      "trump", "biden", "silicon valley",
      "maison-blanche", "pentagone", "usa"], "etats-unis"),
    (["europe", "europeen", "ue", "bruxelles",
      "union europeenne",
      "allemagne", "berlin", "royaume-uni", "londres",
      "italie", "rome", "espagne", "madrid",
      "pays-bas", "autriche", "suede", "norvege",
      "pologne", "grece"], "europe"),
]


def _unaccent(text):
    """去掉变音符号"""
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if not unicodedata.category(c).startswith("M"))


def detect_region(fr_title, fr_desc, source_region):
    """根据标题、摘要的内容判断实际地理区域，不再盲从来源标注"""
    text = _unaccent((fr_title + " " + fr_desc).lower())
    for keywords, region in GEO_RULES:
        for kw in keywords:
            if _unaccent(kw.lower()) in text:
                return region
    return source_region


# ── 内容过滤 & 多样性选择 ──

EXCLUDE_WAR = [
    "guerre", "conflit arm", "frappe", "bombarde",
    "offensive", "combat", "tir", "missile", "explosion",
    "attaque", "drone", "armée", "soldat", "tué", "blessé",
    "champ de bataille", "incursion", "escarmouche",
]

EXCLUDE_PERSON = [
    "condamné à", "prison", "emprisonné", "détention",
    "procès", "jugé", "peine de", "sanctionné", "incarcéré",
    "perpétuité", "isolement",
]

CULTURAL = [
    "écrivain", "artiste", "musique", "cinéma", "livre",
    "roman", "poème", "peinture", "théâtre", "exposition",
    "culture", "patrimoine", "littérature", "photographie",
    "architecture", "sculpture", "danse", "concert",
    "festival", "musée", "bibliothèque",
]

# ── 不要的标签 ──
EXCLUDE_TAGS = {
    "Animaux", "Jardin", "Maison", "Horlogerie", "Bons plans",
    "Quiz français", "À l'Affiche !", "Outre-Mer",
    "Connaissances", "Météo",
}

# 游戏（用户要求排除）
EXCLUDE_GAMES = [
    "jeu vidéo", "jeux vidéo", "jeu video", "jeux video",
    "gaming", "esport", "e-sport", "esports",
    "playstation", "xbox", "nintendo", "steam",
    "console de jeu", "fortnite", "genshin", "minecraft",
    "jeu de société", "jeux de société",
]

# 体育（用户要求排除）
EXCLUDE_SPORTS = [
    "football", "tennis", "rugby", "basket", "handball",
    "cyclisme", "tour de france", "ligue 1", "ligue des champions",
    "championnat", "coupe du monde", "olympique", "olympiques",
    "match", "tournoi", "formule 1", "f1 ", "mercat", "transfert",
    "buteur", "entraîneur", "entraineur", "équipe de france",
    "golf", "natation", "athlétisme", "athletisme",
    "judo", "karaté", "karate", "escrime", "sport",
]

# 天气（用户要求排除）
EXCLUDE_WEATHER = [
    "météo", "meteo", "prévisions météo", "previsions meteo",
    "bulletin météo", "bulletin meteo", "vigilance météo",
]

# 寻物启事 / 二手 / 租房等分类信息
EXCLUDE_CLASSIFIED = [
    "petites annonces", "petite annonce",
    "à vendre", "a vendre", "à louer", "a louer",
    "objet trouvé", "objets trouvés", "perdu",
]

# 广告 / 促销
EXCLUDE_ADS = [
    "publicité", "publicite", "sponsorisé", "sponsorise",
    "offre spéciale", "offre speciale", "réduction", "reduction",
    "livraison gratuite", "partenariat commercial", "black friday",
    "promo", "code promo", "soldes", "bons plans", "amazon",
    "jeu concours", "concours", "horoscope", "astrologie",
    "quiz", "testez", "saurez-vous",
]

# 纯图片/视频类、无实质内容
EXCLUDE_MEDIA = [
    "diaporama", "en images", "en photos", "galerie photo",
    "photos du jour",
]


FRENCH_STOPS = {
    'le', 'la', 'les', 'de', 'des', 'du', 'et', 'est', 'un', 'une',
    'dans', 'sur', 'pour', 'avec', 'par', 'pas', 'plus', 'que', 'qui',
    'à', 'au', 'aux', 'en', 'ce', 'ces', 'son', 'sa', 'ses', 'il',
    'elle', 'nous', 'vous', 'ils', 'elles', 'mais', 'ou', 'donc',
    'car', 'ne', 'pas', 'se', 'sont', 'fait', 'très', 'tout', 'tous',
    'cette', 'leur', 'leurs', 'être', 'avoir', 'faire', 'comme',
    'dans', 'avec', 'sans', 'chez', 'entre',
}


def is_french_text(text):
    """法语检测：通过法语停用词判断文本是否为法语"""
    if not text:
        return True
    words = set(re.findall(r"\b[a-zàâçéèêëîïôûùüÿñ]\w+\b", text.lower()))
    if not words:
        return True
    french_count = len(words & FRENCH_STOPS)
    return french_count >= 2


def should_exclude(tag, title, desc):
    """过滤：边角料标签、游戏/体育/天气/寻物/广告、战争细节、纯人物新闻"""
    if tag in EXCLUDE_TAGS:
        return True
    text = (title + " " + (desc or "")).lower()
    if any(kw in text for kw in CULTURAL):
        return False
    for kw in (EXCLUDE_WAR + EXCLUDE_PERSON + EXCLUDE_GAMES + EXCLUDE_SPORTS
               + EXCLUDE_WEATHER + EXCLUDE_CLASSIFIED + EXCLUDE_ADS + EXCLUDE_MEDIA):
        if kw in text:
            return True
    return False


def select_balanced(items, total=6):
    """按信源均衡选文：每源最多 2 条，轮询凑够 total（5~6 篇）"""
    from collections import defaultdict
    by_src = defaultdict(list)
    for item in items:
        by_src[item.get("source_label", "Autre")].append(item)

    selected = []
    idx = defaultdict(int)
    for round_ in range(2):  # 每源最多 2 条
        for label in by_src:
            if len(selected) >= total:
                break
            if idx[label] < len(by_src[label]):
                selected.append(by_src[label][idx[label]])
                idx[label] += 1
    return selected[:total]


# ── 翻译 ──

def translate(text, src="fr", dst="zh-CN"):
    """用 Google Translate 免费接口翻译（不需要 API key）"""
    if not text or len(text) < 2:
        return ""
    # 限制长度避免被拒
    q = text[:800]
    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl={src}&tl={dst}&dt=t&q={urllib.parse.quote(q)}"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and len(data) > 0:
                parts = []
                for chunk in data[0]:
                    if isinstance(chunk, list) and len(chunk) > 0 and chunk[0]:
                        parts.append(chunk[0])
                return "".join(parts)
    except Exception as e:
        print(f"    ⚠ Traduction échouée: {e}")
    return ""


def translate_long(text, dst="zh-CN", chunk=750):
    """分段翻译长文本（300词法文超过单次800字符限制）"""
    if not text:
        return ""
    sents = split_sentences(text)
    parts, cur = [], ""
    for s in sents:
        if cur and len((cur + " " + s).encode("utf-8")) > chunk:
            parts.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        parts.append(cur)
    out = []
    for p in parts:
        t = translate(p, "fr", dst)
        if t:
            out.append(t)
    return "".join(out)


# ── 正文抓取 & 压缩 ──

def split_sentences(text):
    """按句界切分法语文本（. ! ? 后接大写/引号/数字）"""
    if not text:
        return []
    parts = re.split(r'(?<=[.!?])\s+(?=[«"\'“”A-Z0-9])', text)
    out = []
    for i, p in enumerate(parts):
        p = p.strip()
        if not p:
            continue
        # 短缩写残片（M. / Mme. / St. 等）并入下一句，避免把名字切断
        if len(p) <= 4 and p.endswith(".") and i + 1 < len(parts):
            parts[i + 1] = p + " " + parts[i + 1].strip()
            continue
        out.append(p)
    return out


def clean_body_text(text):
    """清洗抓取的正文：去标签、压缩空白、去常见残留行"""
    text = unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    for junk in ("Publicité", "S'abonner", "Abonnez-vous", "Accéder à la suite",
                 "Lire plus", "Lire la suite", "Newsletter", "Recevez les alertes"):
        text = text.replace(junk, "")
    return text.strip()


def _jsonld_article_body(html):
    """从 JSON-LD 中提取 articleBody（质量最高）"""
    m = re.search(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.S | re.I)
    if not m:
        return ""
    try:
        data = json.loads(m.group(1))
    except Exception:
        return ""
    if isinstance(data, list):
        data = data[0] if data else {}
    if isinstance(data, dict):
        ab = data.get("articleBody")
        if isinstance(ab, str) and len(ab) > 100:
            return ab
    return ""


def _article_paragraphs(html):
    """从 <article> 中提取 <p> 段落"""
    m = re.search(r"<article[^>]*>(.*?)</article>", html, re.S | re.I)
    scope = m.group(1) if m else html
    paras = re.findall(r"<p[^>]*>(.*?)</p>", scope, re.S | re.I)
    out = []
    for p in paras:
        t = _clean_html(unescape(p)).strip()
        t = re.sub(r"\s+", " ", t)
        if len(t) >= 40:
            out.append(t)
    return "\n\n".join(out)


def _og_description(html):
    """回退：og:description 摘要"""
    m = re.search(
        r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\'](.*?)["\']',
        html, re.S | re.I)
    if not m:
        return ""
    return _clean_html(unescape(m.group(1))).strip()


def fetch_article_body(url, timeout=15):
    """抓文章页正文：JSON-LD → <article> → og:description，返回清洗后的正文"""
    raw = fetch_url(url, timeout=timeout)
    if not raw:
        return ""
    html = raw.decode("utf-8", errors="replace")
    body = _jsonld_article_body(html)
    if body:
        body = clean_body_text(body)
        if len(body.split()) >= 60:
            return body
    body = _article_paragraphs(html)
    if body:
        return clean_body_text(body)
    return clean_body_text(_og_description(html))


def condense_fr(text, target=300):
    """压缩长文到 target 词左右（浮动 ±80）。
    新闻倒金字塔：保开头要点，超长时按句界截尾。"""
    if not text:
        return ""
    total = len(text.split())
    if total <= target + 80:
        return text.strip()
    sents = split_sentences(text)
    out, n = [], 0
    for s in sents:
        w = len(s.split())
        if n >= target and n + w > target + 60:
            break
        out.append(s)
        n += w
    res = " ".join(out)
    if len(res.split()) > target + 80:
        res = " ".join(res.split()[:target + 60]).rstrip(".,;:") + "."
    return res.strip()


# ── 主流程 ──

def main():
    print(f"=== 📡 Fetch RSS @ {datetime.now().isoformat()} ===\n")

    # 1. 加载已有文章
    existing = []
    if os.path.exists(ARTICLES_PATH):
        with open(ARTICLES_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
        print(f"📦 {len(existing)} articles existants chargés")
    else:
        print("📦 Aucun articles.json trouvé, création d'un nouveau")

    # 2. 收集已有标题用于去重
    existing_titles = set()
    for article in existing:
        for brief in article.get("briefs", []):
            t = (brief.get("title", "") or "").lower().strip()
            if t:
                existing_titles.add(t)

    # 3. 抓取所有 RSS
    all_new = []
    for src in SOURCES:
        print(f"\n🌐 {src['label']} — {src['url']}")
        raw = fetch_url(src["url"])
        if not raw:
            continue
        items = parse_rss(raw)
        print(f"   → {len(items)} articles")
        for item in items:
            item["region"] = src["region"]
            # 频道级 RSS，信源自带的 tag 是准确的
            # 仅在 RSS 分类明确指向另一目标分类时重映射
            tag = src["tag"]
            TARGET_TAGS = {"Économie", "Technologie", "Culture"}
            if item.get("categories"):
                cat = item["categories"][0].lower()
                # 注意：按完整词匹配，避免短词（"art", "ia"）误伤无关单词
                words = set(re.findall(r"[a-zéèêëàâîïôûùüÿç]+", cat))
                mapping = {
                    "Technologie": {"tech", "numérique", "numériques", "informatique",
                                    "science", "sciences", "espace", "innovation",
                                    "high-tech", "cybersécurité", "ia", "start-up",
                                    "startups", "startup"},
                    "Économie":    {"économie", "économique", "finances", "finance",
                                    "entreprise", "entreprises", "bourse", "marchés",
                                    "marché", "industrie", "conso", "consommation",
                                    "immobilier"},
                    "Culture":     {"culture", "cinéma", "livre", "musique",
                                    "exposition", "théâtre", "spectacle",
                                    "arts", "artistique"},
                }
                for mapped_tag, kws in mapping.items():
                    if mapped_tag in TARGET_TAGS and words & kws:
                        tag = mapped_tag
                        break
            item["tag"] = tag
            item["source_label"] = src["label"]
        all_new.extend(items)

    # 4. 去重
    deduped = []
    seen = set(existing_titles)
    for item in all_new:
        key = item["title"].lower().strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    print(f"\n✅ {len(deduped)} nouveaux articles (après déduplication)")

    if not deduped:
        print("ℹ️  Aucun nouvel article à ajouter.")
        return

    # 过滤非法语内容
    french_only = [item for item in deduped
                   if is_french_text(item["title"] + " " + item.get("desc", ""))]
    eng_count = len(deduped) - len(french_only)
    if eng_count:
        print(f"🗑️  {eng_count} articles non-français exclus")

    # 5. 过滤（游戏/体育/天气/寻物/广告/无实质）
    candidates = [item for item in french_only
                  if not should_exclude(item.get("tag", ""), item["title"], item.get("desc", ""))]
    print(f"📋 {len(candidates)} candidats après filtrage")
    if not candidates:
        print("ℹ️  Aucun candidat.")
        return

    # 6. 抓取正文 & 压缩（每源最多抓 6 条页面，避免请求过多）
    from collections import defaultdict
    per_src = defaultdict(int)
    ready = []
    print("\n📄 Récupération des articles complets…")
    for item in candidates:
        if per_src[item["source_label"]] >= 6:
            continue
        per_src[item["source_label"]] += 1
        print(f"  → {item['source_label']}: {item['title'][:45]}")
        body = fetch_article_body(item["link"])
        if not body:
            body = item.get("desc", "")  # 回退 RSS 摘要
        wc = len(body.split())
        if wc < MIN_BODY_WORDS:
            print(f"    ⏭️  Corps trop court ({wc} mots)")
            continue
        item["body"] = condense_fr(body, target=TARGET_WORDS)
        item["word_count"] = len(item["body"].split())
        ready.append(item)

    # 7. 按信源均衡选 5~6 篇
    selected = select_balanced(ready, total=6)
    print(f"\n📋 {len(selected)} articles retenus")
    if not selected:
        print("ℹ️  Aucun article valable.")
        return

    # 8. 翻译 & 构建 briefs
    today = date.today()
    today_str = today.isoformat()

    briefs = []
    for item in selected:
        # 完整原标题（不截断）+ 检测实际地区
        item["title"] = re.sub(r"\s+", " ", item["title"]).strip()
        item["region"] = detect_region(
            item["title"], item.get("desc", ""), item.get("region", "francophonie")
        )

        # 中文正文（分段翻译长文）
        summary_cn = translate_long(item["body"])

        # 中文标题：完整翻译原标题；原标题过长则从正文提炼
        title_cn = make_title_cn(item["title"], summary_cn)
        if not title_cn:
            title_cn = f"[{item['source_label']}] {item['title']}"

        # 解析发布时间
        dt = parse_date_str(item["pub_date"])
        pub_date_str = (
            dt.strftime("%d %B %Y").lstrip("0") if dt else today_str
        )

        briefs.append({
            "tag": item["tag"],
            "title_cn": title_cn or "",
            "title": item["title"],
            "body": item["body"],
            "summary_cn": summary_cn,
            "source": item["source_label"],
            "pub_date": pub_date_str,
            "auto": True,
            "link": item["link"],
            "region": item["region"],
        })

    # 9. 构建当日文章条目
    tags = list(dict.fromkeys(b["tag"] for b in briefs))  # 有序去重
    regions = list(dict.fromkeys(item["region"] for item in selected))
    summaries_cn = [b["title_cn"] for b in briefs if b["title_cn"]]
    summary_line = " | ".join(summaries_cn[:5]) if summaries_cn else ""

    new_article = {
        "date": today_str,
        "tags": tags,
        "regions": regions,
        "summary_cn": summary_line,
        "briefs": briefs,
        "vocab": [],
        "word_count": sum(len(b["body"].split()) for b in briefs),
        "auto": True,
    }

    # 10. 合并到已有列表
    # 移除今天的 auto 旧版本（如果有）
    existing = [
        a for a in existing
        if not (a.get("auto") and a["date"] == today_str)
    ]

    # 保留全部文章，不做自动删除（用户看完后手动清理）
    kept = list(existing)

    kept.insert(0, new_article)

    # 11. 写回
    with open(ARTICLES_PATH, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(kept)} articles écrits dans articles.json")
    print(f"   ➕ {len(briefs)} nouvelles dépêches — {today_str}")


if __name__ == "__main__":
    main()
