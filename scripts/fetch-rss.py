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
import time
import unicodedata
import urllib.error
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, date, timezone
from html import unescape

# ── 信源配置 ──
# 锁定 5 家指定信源，不再订阅杂源
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
# RFI 会 403 浏览器 UA（WAF 拦截），需要用简单 UA
SIMPLE_UA = "Mozilla/5.0 (compatible; RSSBot/1.0)"

SOURCES = [
    {"url": "https://www.lemonde.fr/rss/une.xml",       "region": "francophonie",  "tag": "Actualité", "label": "Le Monde"},
    {"url": "https://www.francetvinfo.fr/titres.rss",   "region": "francophonie",  "tag": "Actualité", "label": "France Info"},
    {"url": "https://www.rfi.fr/fr/rss",                "region": "international", "tag": "Actualité", "label": "RFI", "ua": SIMPLE_UA},
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

def fetch_url(url, timeout=20, ua=None):
    """带超时、User-Agent、gzip 和 SSL 降级的 HTTP GET"""
    import ssl

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": ua or BROWSER_UA,
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
            if _kw_hit(kw, text):
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

# 党派 / 选举（用户要求排除：党派斗争、选举造势不关心）
# 只匹配标题，避免正文顺带提及误伤；保留法国国家级重大政治（政府/预算/法案）
EXCLUDE_POLITICS = [
    # 选举造势
    "élection", "élections", "électoral", "électorale", "électorales",
    "scrutin", "urnes", "législative", "législatives",
    # municipale 单数会误杀 "piscine/bibliothèque municipale"，只留复数
    "municipales", "présidentielle",
    # primaire 单用会误杀 "école primaire"，只留选举语境的说法
    "la primaire", "primaire du", "primaire de la", "primaire socialiste",
    "primaire à", "élection primaire",
    "candidat", "candidats", "candidature", "sondage", "sondages",
    "premier tour", "second tour", "ballottage", "abstention",
    "électeur", "électeurs", "votants",
    "campagne électorale", "campagne présidentielle",
    # 党派 / 党派斗争
    "parti politique", "partis politiques", "du parti", "au parti",
    "chef du parti", "direction du parti", "au sein du parti",
    "rassemblement national", "front national",
    "france insoumise", "parti socialiste", "parti communiste",
    "nouveau front populaire", "nupes",
    "majorité présidentielle", "l'opposition", "coalition",
    "front républicain", "cordon sanitaire", "dissidence", "dissidents",
    "guerre des chefs",
]

# ── DELF B2 主题（theme.png 高亮话题，选文时优先）──
# 两组高亮同等优先：经济/环境/交通/消费 + 工作/教育/住房/科技互联网
THEMES = [
    ("Économie", [
        "économie", "économique", "inflation", "croissance", "pib",
        "budget", "déficit", "dette", "fiscalité", "impôt", "impôts",
        "taxe", "taxes", "pouvoir d'achat", "bourse", "marché",
        "marchés", "taux", "banque", "banques", "commerce", "industrie",
        "investissement", "exportations", "concurrence", "euro",
        "crise économique", "restrictions budgétaires",
    ]),
    ("Environnement", [
        "environnement", "écologie", "écologique", "climat", "climatique",
        "réchauffement", "biodiversité", "pollution", "carbone", "co2",
        "énergie", "énergies", "renouvelable", "renouvelables", "solaire",
        "éolien", "éoliennes", "nucléaire", "déchets", "recyclage",
        "forêt", "forêts", "océan", "sécheresse", "inondations",
        "canicule", "transition énergétique", "agriculture", "agricole",
        "pesticides", "gaz à effet de serre",
    ]),
    ("Transports", [
        "transport", "transports", "train", "trains", "sncf", "métro",
        "bus", "tramway", "vélo", "vélos", "piste cyclable",
        "pistes cyclables", "cyclable", "voiture", "voitures",
        "automobile", "embouteillages", "circulation", "route", "routes",
        "autoroute", "avion", "aérien", "aéroport", "gare", "gares",
        "ferroviaire", "tgv", "covoiturage", "mobilité", "péage",
        "scooter", "trottinette", "maritime", "portuaire", "camions",
        "transport en commun", "zones à faibles émissions",
    ]),
    ("Consommation", [
        "consommation", "consommateur", "consommateurs", "achat",
        "achats", "supermarché", "supermarchés", "hypermarché",
        "grande distribution", "alimentation", "alimentaire",
        "obsolescence", "étiquette", "étiquettes", "ticket de caisse",
        "e-commerce", "achat en ligne",
    ]),
    ("Travail", [
        "travail", "emploi", "chômage", "chômeurs", "salarié",
        "salariés", "salaire", "salaires", "entreprise", "entreprises",
        "patron", "patronat", "syndicat", "syndicats", "grève", "grèves",
        "grévistes", "licenciement", "licenciements", "embauche",
        "recrutement", "cdd", "cdi", "télétravail", "retraite",
        "retraites", "congés", "temps de travail", "intérim",
        "apprentissage", "burn-out", "conditions de travail",
    ]),
    ("Éducation", [
        "école", "écoles", "éducation", "élève", "élèves", "étudiant",
        "étudiants", "université", "universités", "bac",
        "baccalauréat", "professeur", "professeurs", "enseignant",
        "enseignants", "enseignement", "lycée", "collège", "classe",
        "rentrée scolaire", "parcoursup", "études", "diplôme",
        "scolarité", "harcèlement scolaire", "cantine",
    ]),
    ("Logement", [
        "logement", "logements", "immobilier", "loyer", "loyers",
        "locataire", "locataires", "propriétaire", "propriétaires",
        "hlm", "habitat", "copropriété", "expulsion",
        "logements sociaux", "passoire thermique", "urbanisme",
        "foncier", "accession à la propriété",
    ]),
    ("Technologies", [
        "technologie", "technologies", "numérique", "internet",
        "intelligence artificielle", "ia", "algorithme",
        "données personnelles", "cyber", "cybersécurité", "piratage",
        "smartphone", "application", "réseaux sociaux", "cloud",
        "logiciel", "start-up", "startup", "innovation",
        "robot", "robotique", "5g", "fibre", "ordinateur",
        "puce", "semi-conducteurs", "satellite", "spatial", "spatiale",
        "quantique", "rgpd", "deepfake", "hacker",
        # 企业与产品名（标题里最常见的形式）
        "apple", "iphone", "ipad", "mac", "google", "microsoft",
        "amazon", "samsung", "android", "windows", "huawei", "nvidia",
        "openai", "chatgpt", "tiktok", "instagram", "facebook",
        "youtube", "bitcoin", "crypto", "blockchain", "métavers",
    ]),
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


def _kw_hit(kw, text):
    """关键词整词匹配（自动兼容复数 -s），text 需已 _unaccent + lower"""
    return re.search(r"\b" + re.escape(_unaccent(kw)) + r"s?\b", text) is not None


def match_themes(title):
    """返回标题命中的 DELF B2 主题名（theme.png 高亮话题），无命中返回 []
    只看标题：摘要里的顺带提及常造成误判（如 11-Septembre 被判成 Transports）"""
    text = _unaccent((title or "").lower())
    hits = []
    for name, kws in THEMES:
        for kw in kws:
            if _kw_hit(kw, text):
                hits.append(name)
                break
    return hits


def should_exclude(tag, title, desc):
    """过滤：边角料标签、党派/选举、游戏/体育/天气/寻物/广告、战争细节、纯人物新闻"""
    if tag in EXCLUDE_TAGS:
        return True
    title_text = _unaccent((title or "").lower())
    # 党派 / 选举只看标题：正文顺带提及不算
    for kw in EXCLUDE_POLITICS:
        if _kw_hit(kw, title_text):
            return True
    text = (title + " " + (desc or "")).lower()
    if any(kw in text for kw in CULTURAL):
        return False
    for kw in (EXCLUDE_WAR + EXCLUDE_PERSON + EXCLUDE_GAMES + EXCLUDE_SPORTS
               + EXCLUDE_WEATHER + EXCLUDE_CLASSIFIED + EXCLUDE_ADS + EXCLUDE_MEDIA):
        if kw in text:
            return True
    return False


def select_themed(items, total=2):
    """优先选命中 DELF 主题的文章（theme.png），同一信源最多 1 条；
    主题不够时用其余文章补齐。"""
    from collections import defaultdict
    themed = [i for i in items if i.get("themes")]
    others = [i for i in items if not i.get("themes")]

    chosen = []

    def take(pool, limit):
        per_src = defaultdict(int)
        for c in chosen:
            per_src[c["source_label"]] += 1
        for it in pool:
            if len(chosen) >= limit:
                break
            if per_src[it["source_label"]] >= 1:
                continue
            per_src[it["source_label"]] += 1
            chosen.append(it)

    take(themed, total)
    if len(chosen) < total:
        take(others, total)          # 放宽：允许与已有重复信源之外补
    if len(chosen) < total:
        for it in themed + others:   # 最后兜底：不再限制信源
            if len(chosen) >= total:
                break
            if it not in chosen:
                chosen.append(it)
    return chosen[:total]


# ── 翻译 ──

# client=gtx 自 2026-08-23 起被限流(429)，改用 at/dict-chrome-ex
TRANSLATE_CLIENTS = ["at", "dict-chrome-ex", "gtx"]


def _mymemory(text, dst="zh-CN", timeout=12):
    """Google 免费接口全挂时的兜底：MyMemory 免费 API（带邮箱提升配额）"""
    langpair = "fr|zh-CN" if dst == "zh-CN" else f"fr|{dst}"
    url = (
        "https://api.mymemory.translated.net/get"
        f"?q={urllib.parse.quote(text[:400])}&langpair={langpair}"
        "&de=lesnotesdelaurette@gmail.com"
    )
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            d = json.loads(resp.read().decode("utf-8"))
            if d.get("responseStatus") != 200:
                return ""
            return d.get("responseData", {}).get("translatedText", "") or ""
    except Exception as e:
        print(f"    ⚠ MyMemory échoué: {e}")
        return ""


def _is_chinese(text):
    """目标为中文时校验结果确实含汉字，避免偶发返回英文"""
    return bool(text and re.search(r"[一-鿿]", text))


def translate(text, src="fr", dst="zh-CN"):
    """用 Google Translate 免费接口翻译（client=at，规避 gtx 的 429）
    结果必须含汉字才算成功，否则换下一个接口 / 兜底。"""
    if not text or len(text) < 2:
        return ""
    q = text[:4000]
    for attempt in range(2):
        for client in TRANSLATE_CLIENTS:
            time.sleep(0.8)  # 限速，避免触发 429
            url = (
                "https://translate.googleapis.com/translate_a/single"
                f"?client={client}&sl={src}&tl={dst}&dt=t&q={urllib.parse.quote(q)}"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(data, list) and len(data) > 0:
                        parts = []
                        for chunk in data[0]:
                            if isinstance(chunk, list) and len(chunk) > 0 and chunk[0]:
                                parts.append(chunk[0])
                        result = "".join(parts)
                        if _is_chinese(result):
                            return result
                        print(f"    ⚠ Traduction sans chinois (client={client})")
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(2)  # 限流 → 等 2s 换下一个 client
                    continue
                print(f"    ⚠ Traduction HTTP {e.code}")
            except Exception as e:
                print(f"    ⚠ Traduction échouée: {e}")
        time.sleep(1)
    result = _mymemory(q, dst)
    return result if _is_chinese(result) else ""


def translate_long(text, dst="zh-CN", chunk=2500):
    """分段翻译长文本（单次请求放宽到约2500字节，300词法文通常1次搞定）"""
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
    # France Info 正文开头常带 "Article rédigé par … Publié le …" 元数据，去掉
    text = re.sub(
        r"Article rédigé par .*?(?:Publié le |Mis à jour le )?\d{1,2}/\d{1,2}/\d{4} \d{2}:\d{2}",
        " ", text)
    text = re.sub(r"(?:Publié le |Mis à jour le )\d{1,2}/\d{1,2}/\d{4} \d{2}:\d{2}", " ", text)
    text = re.sub(r"^\s*\d{1,2}/\d{1,2}/\d{4} \d{2}:\d{2}", " ", text)
    for junk in ("Publicité", "S'abonner", "Abonnez-vous", "Accéder à la suite",
                 "Lire plus", "Lire la suite", "Newsletter", "Recevez les alertes"):
        text = text.replace(junk, "")
    text = re.sub(r"\s+", " ", text)
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


def extract_readable(html):
    """段落密度法提取正文：去掉导航/脚本后，取连续 <p> 段落里最长的一块。
    Le Monde / La Tribune 的正文不在 <article><p> 里，需要这种通用抽取。"""
    for tag in ("script", "style", "noscript", "nav", "header", "footer",
                "aside", "iframe", "form", "button", "select"):
        html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    paras = []
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", html, flags=re.S | re.I):
        t = _clean_html(unescape(m.group(1)))
        t = re.sub(r"\s+", " ", t)
        if len(t) >= 40:
            paras.append((m.start(), m.end(), t))
    if not paras:
        return ""
    groups, cur = [], [paras[0]]
    for i in range(1, len(paras)):
        if paras[i][0] - paras[i - 1][1] > 400:
            groups.append(cur)
            cur = []
        cur.append(paras[i])
    if cur:
        groups.append(cur)
    best = max(groups, key=lambda g: sum(len(t) for _, _, t in g))
    # 去掉开头导航残留（如 "Retour à la page d'accueil"、"Les lives en cours"）
    while best and (len(best[0][2]) < 100
                    or re.match(r"^(retour|accueil|les lives|l'actualité|menu)", best[0][2].lower())):
        best = best[1:]
    return " ".join(t for _, _, t in best)


def _og_description(html):
    """回退：og:description 摘要"""
    m = re.search(
        r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\'](.*?)["\']',
        html, re.S | re.I)
    if not m:
        return ""
    return _clean_html(unescape(m.group(1))).strip()


def fetch_article_body(url, timeout=15, ua=None):
    """抓文章页正文：JSON-LD → 段落密度抽取 → og:description，返回清洗后的正文"""
    raw = fetch_url(url, timeout=timeout, ua=ua)
    if not raw:
        return ""
    html = raw.decode("utf-8", errors="replace")
    body = _jsonld_article_body(html)
    if body:
        body = clean_body_text(body)
        if len(body.split()) >= 60:
            return body
    body = extract_readable(html)
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
        raw = fetch_url(src["url"], ua=src.get("ua"))
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
            item["source_ua"] = src.get("ua")
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

    # 5. 过滤（党派/选举、游戏/体育/天气/寻物/广告、无实质）
    candidates = [item for item in french_only
                  if not should_exclude(item.get("tag", ""), item["title"], item.get("desc", ""))]
    print(f"📋 {len(candidates)} candidats après filtrage")
    if not candidates:
        print("ℹ️  Aucun candidat.")
        return

    # 5b. 标记 DELF B2 主题，命中主题的排在前面
    #（每源只抓 6 条正文，先抓主题文，否则抓不到）
    for item in candidates:
        item["themes"] = match_themes(item["title"])
    candidates.sort(key=lambda it: 0 if it["themes"] else 1)
    themed_n = sum(1 for it in candidates if it["themes"])
    print(f"🎯 {themed_n} candidats sur un thème DELF B2")

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
        body = fetch_article_body(item["link"], ua=item.get("source_ua"))
        if not body:
            body = item.get("desc", "")  # 回退 RSS 摘要
        wc = len(body.split())
        if wc < MIN_BODY_WORDS:
            print(f"    ⏭️  Corps trop court ({wc} mots)")
            continue
        item["body"] = condense_fr(body, target=TARGET_WORDS)
        item["word_count"] = len(item["body"].split())
        ready.append(item)

    # 7. 选 2 篇：优先 DELF 主题（theme.png），信源不重复
    selected = select_themed(ready, total=2)
    print(f"\n📋 {len(selected)} articles retenus")
    for it in selected:
        print(f"    · [{it['source_label']}] {'/'.join(it['themes']) or 'hors-thème'} — {it['title'][:50]}")
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
