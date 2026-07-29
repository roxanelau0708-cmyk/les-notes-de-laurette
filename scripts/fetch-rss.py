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
# 全部为法语媒体，按经济/科技/文化三大类分频道订阅，不再抓综合RSS
SOURCES = [
    # ── 经济 ──
    {"url": "https://www.lemonde.fr/economie/rss_full.xml",          "region": "francophonie", "tag": "Économie",     "label": "Le Monde"},
    {"url": "https://www.lefigaro.fr/rss/figaro_economie.xml",       "region": "francophonie", "tag": "Économie",     "label": "Le Figaro"},
    {"url": "https://www.challenges.fr/rss.xml",                     "region": "francophonie", "tag": "Économie",     "label": "Challenges"},
    {"url": "https://www.bfmtv.com/rss/economie/",                  "region": "francophonie", "tag": "Économie",     "label": "BFM Eco"},
    {"url": "https://www.france24.com/fr/economie/rss",             "region": "international", "tag": "Économie",    "label": "France 24"},

    # ── 科技 ──
    {"url": "https://www.lemonde.fr/technologies/rss_full.xml",     "region": "francophonie", "tag": "Technologie",  "label": "Le Monde"},
    {"url": "https://www.lefigaro.fr/rss/figaro_secteur_high-tech.xml", "region": "francophonie", "tag": "Technologie",  "label": "Le Figaro"},
    {"url": "https://www.numerama.com/feed/",                       "region": "francophonie", "tag": "Technologie",  "label": "Numerama"},
    {"url": "https://siecledigital.fr/feed/",                       "region": "francophonie", "tag": "Technologie",  "label": "Siècle Digital"},
    {"url": "https://www.zdnet.fr/rss/",                            "region": "francophonie", "tag": "Technologie",  "label": "ZDNet"},

    # ── 文化 ──
    {"url": "https://www.lemonde.fr/culture/rss_full.xml",          "region": "francophonie", "tag": "Culture",      "label": "Le Monde"},
    {"url": "https://www.lefigaro.fr/rss/figaro_culture.xml",       "region": "francophonie", "tag": "Culture",      "label": "Le Figaro"},
    {"url": "https://www.france24.com/fr/culture/rss",              "region": "international", "tag": "Culture",     "label": "France 24"},
    {"url": "https://www.rfi.fr/fr/culture/rss",                    "region": "international", "tag": "Culture",     "label": "RFI"},
]

# ── 路径 ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.dirname(SCRIPT_DIR)
ARTICLES_PATH = os.path.join(SITE_DIR, "articles.json")

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


def clean_title_cn(title_cn):
    """加工中文标题：去掉省略号、句子类标题不超过15字"""
    if not title_cn:
        return ""
    # 去掉所有省略号
    title_cn = title_cn.replace("…", "").replace("...", "").strip().strip("，。！？、；：")
    if not title_cn:
        return ""
    # 标点靠前（前5字以内）视为格式符号而非句子标记，不截断
    # 例如 "巴西：..." 中的冒号不应触发截断
    punct_pos = None
    for p in "，。！？":
        idx = title_cn.find(p)
        if idx != -1:
            punct_pos = idx
            break
    if punct_pos is not None and punct_pos > 5:
        # 有句子标点且在合理位置，取标点前的内容
        t = title_cn[:punct_pos].strip()
        t = t[:15].rstrip("，。！？、；：").strip()
        return t if t else title_cn[:15]
    # 无标点或标点靠前的关键词/短语，超过15字才截
    if len(title_cn) > 15:
        return title_cn[:15].rstrip("，。！？、；：").strip()
    return title_cn


def shorten_french_title(title):
    """缩短法语新闻标题——去掉前缀、取冒号前的主干、超出 65 字截断"""
    if not title:
        return title
    t = title.strip()

    # 去掉常见前缀
    for p in ["EN DIRECT, ", "EN DIRECT : ", "EN DIRECT — ", "DIRECT, ", "DIRECT : ",
              "INFO ", "VIDEO - ", "VIDÉO - ", "EXCLUSIF - ", "EXCLUSIF : "]:
        if t.upper().startswith(p.upper()):
            t = t[len(p):]
            break

    # 取冒号或长破折号前的部分（核心主题）
    for sep in [" : ", " : ", " — ", " — "]:
        if sep in t:
            before = t.split(sep, 1)[0]
            if 8 <= len(before) <= 70:
                t = before
                break

    # 65 字截断（不加省略号，主页标题有省略号很难看）
    if len(t) > 65:
        truncated = t[:65]
        last_space = truncated.rfind(" ")
        if last_space > 30:
            truncated = truncated[:last_space]
        t = truncated.strip()

    return t.strip()


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
# Le Figaro 等媒体的细碎分类：宠物、园艺、装修、钟表、促销/广告、语言小测等
EXCLUDE_TAGS = {
    "Animaux", "Jardin", "Maison", "Horlogerie", "Bons plans",
    "Quiz français", "À l'Affiche !", "Outre-Mer",
    "Connaissances", "Météo",
}

EXCLUDE_FLUFF_TITLE = [
    "quiz", "testez", "saurez-vous",
    "bons plans", "promo", "code promo",
    "soldes", "amazon",
    "jeu concours", "concours",
    "horoscope", "astrologie",
    "meteo", "météo",
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
    """过滤：边角料标签、宠物/装修/促销等软内容、战争细节、纯人物新闻"""
    if tag in EXCLUDE_TAGS:
        return True
    text = (title + " " + (desc or "")).lower()
    if any(kw in text for kw in CULTURAL):
        return False
    if any(kw in text for kw in EXCLUDE_WAR):
        return True
    if any(kw in text for kw in EXCLUDE_PERSON):
        return True
    if any(kw in text for kw in EXCLUDE_FLUFF_TITLE):
        return True
    return False


def select_diverse(items, total=12):
    """轮询各 tag 取文章，保证 topic 丰富度，每 tag 最多 4 条"""
    from collections import defaultdict
    by_tag = defaultdict(list)
    for item in items:
        by_tag[item.get("tag", "Autre")].append(item)

    sorted_tags = sorted(by_tag, key=lambda t: len(by_tag[t]))
    counts = defaultdict(int)
    selected = []

    while len(selected) < total:
        picked = False
        for t in sorted_tags:
            if len(selected) >= total:
                break
            if counts[t] >= 4 or counts[t] >= len(by_tag[t]):
                continue
            selected.append(by_tag[t][counts[t]])
            counts[t] += 1
            picked = True
        if not picked:
            break  # 没更多可取了

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

    # 5. 过滤 + 多样性选文
    candidates = [item for item in french_only
                  if not should_exclude(item.get("tag", ""), item["title"], item.get("desc", ""))]
    selected = select_diverse(candidates, total=12)
    print(f"📋 {len(selected)} articles retenus ({len(candidates)} candidats après filtrage)")

    # 6. 翻译 & 构建 briefs
    today = date.today()
    today_str = today.isoformat()

    briefs = []
    for item in selected:
        # 缩短标题 + 检测实际地区
        item["title"] = shorten_french_title(item["title"])
        item["region"] = detect_region(
            item["title"], item.get("desc", ""), item.get("region", "francophonie")
        )

        # 中文标题
        title_cn = translate(item["title"])
        if not title_cn:
            title_cn = f"[{item['source_label']}] {item['title']}"

        # 中文标题（加工处理：去省略号、句子类不超过15字）
        title_cn = clean_title_cn(title_cn)

        # 跳过正文少于 30 词的短资讯
        body = item["desc"] or item["title"]
        if len(body.split()) < 30:
            print(f"    ⏭️  Corps trop court ({len(body.split())} mots) : {item['title'][:40]}")
            continue

        # 中文摘要
        summary_cn = ""
        if item["desc"]:
            summary_cn = translate(item["desc"])
        if not summary_cn:
            summary_cn = ""

        # 解析发布时间
        dt = parse_date_str(item["pub_date"])
        pub_date_str = (
            dt.strftime("%d %B %Y").lstrip("0") if dt else today_str
        )

        briefs.append({
            "tag": item["tag"],
            "title_cn": title_cn or "",
            "title": item["title"],
            "body": body,
            "source": item["source_label"],
            "pub_date": pub_date_str,
            "auto": True,
            "link": item["link"],
            "region": item["region"],
        })

    # 7. 构建当日文章条目
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

    # 8. 合并到已有列表
    # 移除今天的 auto 旧版本（如果有）
    existing = [
        a for a in existing
        if not (a.get("auto") and a["date"] == today_str)
    ]

    # 保留全部文章，不做自动删除（用户看完后手动清理）
    kept = list(existing)

    kept.insert(0, new_article)

    # 9. 写回
    with open(ARTICLES_PATH, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(kept)} articles écrits dans articles.json")
    print(f"   ➕ {len(briefs)} nouvelles dépêches — {today_str}")


if __name__ == "__main__":
    main()
