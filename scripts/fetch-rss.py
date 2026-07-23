#!/usr/bin/env python3
"""
fetch-rss.py — RSS 新闻聚合器
每天从法语媒体抓取资讯，自动翻译标题/摘要为中文，更新 articles.json
使用 Python 标准库，无外部依赖
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, date, timezone, timedelta
from html import unescape

# ── 信源配置 ──
# 全部为法语信源，覆盖法语区社会/经济/科技 + 法语视角的美国科技
SOURCES = [
    {
        "url": "https://www.lemonde.fr/rss/une.xml",
        "region": "francophonie",
        "tag": "Société",
        "label": "Le Monde",
    },
    {
        "url": "https://www.lesechos.fr/rss.xml",
        "region": "francophonie",
        "tag": "Économie",
        "label": "Les Echos",
    },
    {
        "url": "https://www.lefigaro.fr/rss/figaro_une.xml",
        "region": "francophonie",
        "tag": "Société",
        "label": "Le Figaro",
    },
    {
        "url": "https://www.france24.com/fr/rss",
        "region": "international",
        "tag": "International",
        "label": "France 24",
    },
    {
        "url": "https://www.rfi.fr/fr/rss",
        "region": "international",
        "tag": "International",
        "label": "RFI",
    },
    {
        "url": "https://www.01net.com/rss/actualites/",
        "region": "etats-unis",         # 01net 用法语视角报道美国科技
        "tag": "Technologie",
        "label": "01net",
    },
    {
        "url": "https://www.usine-digitale.fr/rss",
        "region": "etats-unis",
        "tag": "Technologie",
        "label": "Usine Digitale",
    },
    {
        "url": "https://www.lesnumeriques.com/rss/news.xml",
        "region": "etats-unis",
        "tag": "Technologie",
        "label": "Les Numériques",
    },
    {
        "url": "https://www.bfmtv.com/rss/economie/",
        "region": "francophonie",
        "tag": "Économie",
        "label": "BFM Eco",
    },
]

# ── 路径 ──
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.dirname(SCRIPT_DIR)
ARTICLES_PATH = os.path.join(SITE_DIR, "articles.json")

# ── RSS 抓取 ──

def fetch_url(url, timeout=15):
    """带超时和 User-Agent 的 HTTP GET"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"  ⚠ Échec: {url} — {e}")
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
    """解析 RSS 2.0 / Atom 格式，返回 item 列表"""
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
        if title:
            items.append({
                "title": title.strip(),
                "desc": desc[:500].strip(),
                "pub_date": pub.strip(),
                "link": link.strip(),
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

            if title:
                items.append({
                    "title": title.strip(),
                    "desc": desc[:500].strip(),
                    "pub_date": pub.strip(),
                    "link": link.strip(),
                })

    return items


def _clean_html(text):
    """去除 HTML 标签"""
    return re.sub(r"<[^>]+>", "", text).strip()


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
            item["tag"] = src["tag"]
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
        # 即使没有新文章也继续执行，确保保留最近内容
        return

    # 5. 翻译 & 构建 briefs（取前 12 条）
    today = date.today()
    today_str = today.isoformat()

    briefs = []
    for item in deduped[:12]:
        # 中文标题
        title_cn = translate(item["title"])
        if not title_cn:
            title_cn = f"[{item['source_label']}] {item['title']}"

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
            "body": item["desc"] or item["title"],
            "source": item["source_label"],
            "pub_date": pub_date_str,
            "auto": True,
            "link": item["link"],
        })

    # 6. 构建当日文章条目
    tags = list(dict.fromkeys(b["tag"] for b in briefs))  # 有序去重
    regions = list(dict.fromkeys(item["region"] for item in deduped[:12]))
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

    # 7. 合并到已有列表
    # 移除今天的 auto 旧版本（如果有）
    existing = [
        a for a in existing
        if not (a.get("auto") and a["date"] == today_str)
    ]

    # 保留手动文章（auto=false 或无 auto 字段）+ 最近 14 天的 auto 文章
    cutoff = (today - timedelta(days=14)).isoformat()
    kept = []
    for a in existing:
        if not a.get("auto"):
            kept.append(a)
        elif a["date"] >= cutoff:
            kept.append(a)
        else:
            print(f"  🗑 Supprimé: {a['date']} (auto, plus de 14 jours)")

    kept.insert(0, new_article)

    # 8. 写回
    with open(ARTICLES_PATH, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(kept)} articles écrits dans articles.json")
    print(f"   ➕ {len(briefs)} nouvelles dépêches — {today_str}")


if __name__ == "__main__":
    main()
