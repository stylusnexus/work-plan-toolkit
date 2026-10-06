#!/usr/bin/env python3
"""Offline checks for the static GitHub Pages site in site/.

Stdlib only and Python 3.9-safe. Run from the repo root:

    python3 scripts/check_site.py

It checks, for every HTML page under site/:
  - exactly one <h1>, an html lang attribute and a viewport meta tag;
  - <title> of at most 60 characters and a meta description of at most 155;
  - a canonical URL under the site base (404.html must be noindex instead);
  - every JSON-LD block parses, and no block claims ratings, reviews or user counts;
  - a FAQPage block matches the visible FAQ (<dl class="faq">) question for question;
  - every local href/src (relative, root-relative or absolute on the site base)
    resolves to a file in site/, and same-site #fragments resolve to an id.

And for the site-level files:
  - sitemap.xml URLs map to real pages;
  - llms.txt and llms-full.txt links on the site base resolve to real files;
  - robots.txt has a Sitemap line pointing at sitemap.xml.

Exits 1 with a list of problems, 0 when everything passes.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
BASE = "https://stylusnexus.github.io/work-plan-toolkit/"
BASE_PATH = "/work-plan-toolkit/"
TITLE_MAX = 60
DESC_MAX = 155
FORBIDDEN_LD_KEYS = ("aggregateRating", "review", "reviewRating", "ratingValue", "userCount", "interactionStatistic")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang: Optional[str] = None
        self.h1_count = 0
        self.title = ""
        self.meta: Dict[str, str] = {}
        self.canonical: Optional[str] = None
        self.links: List[str] = []
        self.ids: List[str] = []
        self.jsonld: List[str] = []
        self.faq: List[Tuple[str, str]] = []
        self._in_title = False
        self._in_ld = False
        self._ld_buf: List[str] = []
        self._faq_depth = 0
        self._faq_field: Optional[str] = None
        self._faq_buf: List[str] = []
        self._dl_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = a.get("name") or a.get("property")
            if key:
                self.meta[key] = a.get("content", "")
        elif tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld = True
            self._ld_buf = []
        elif tag == "dl":
            self._dl_depth += 1
            if "faq" in a.get("class", "").split():
                self._faq_depth = self._dl_depth
        elif tag in ("dt", "dd") and self._faq_depth:
            self._faq_field = tag
            self._faq_buf = []
        if tag in ("a", "link") and a.get("href"):
            self.links.append(a["href"])
        if tag in ("img", "script", "source") and a.get("src"):
            self.links.append(a["src"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_ld:
            self._in_ld = False
            self.jsonld.append("".join(self._ld_buf))
        elif tag in ("dt", "dd") and self._faq_field == tag:
            text = norm("".join(self._faq_buf))
            if tag == "dt":
                self.faq.append((text, ""))
            elif self.faq:
                self.faq[-1] = (self.faq[-1][0], text)
            self._faq_field = None
        elif tag == "dl":
            if self._dl_depth == self._faq_depth:
                self._faq_depth = 0
            self._dl_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_ld:
            self._ld_buf.append(data)
        if self._faq_field:
            self._faq_buf.append(data)


def url_to_file(url: str) -> Optional[Path]:
    """Map a site URL path (absolute on BASE or root-relative) to a file in site/."""
    parts = urlsplit(url)
    path = unquote(parts.path)
    if not path.startswith(BASE_PATH):
        return None
    rel = path[len(BASE_PATH):]
    target = SITE / rel
    if rel == "" or rel.endswith("/"):
        target = target / "index.html"
    return target


def resolve_local(page: Path, ref: str) -> Tuple[Optional[Path], str]:
    """Return (file, fragment) for a local reference, or (None, '') if external."""
    parts = urlsplit(ref)
    if parts.scheme in ("mailto", "tel", "data", "javascript"):
        return None, ""
    if parts.scheme or parts.netloc:
        full = ref if parts.scheme else "https:" + ref
        if not full.startswith(BASE):
            return None, ""
        return url_to_file(full), parts.fragment
    if parts.path.startswith("/"):
        return url_to_file(parts.path), parts.fragment
    if parts.path == "":
        return page, parts.fragment
    target = (page.parent / unquote(parts.path)).resolve()
    if parts.path.endswith("/") or target.is_dir():
        target = target / "index.html"
    return target, parts.fragment


def walk_keys(obj: object) -> List[str]:
    keys: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.append(k)
            keys.extend(walk_keys(v))
    elif isinstance(obj, list):
        for v in obj:
            keys.extend(walk_keys(v))
    return keys


def find_type(obj: object, type_name: str) -> List[dict]:
    found: List[dict] = []
    if isinstance(obj, dict):
        if obj.get("@type") == type_name:
            found.append(obj)
        for v in obj.values():
            found.extend(find_type(v, type_name))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(find_type(v, type_name))
    return found


def ids_of(path: Path, cache: Dict[Path, List[str]]) -> List[str]:
    if path not in cache:
        p = PageParser()
        p.feed(path.read_text(encoding="utf-8"))
        cache[path] = p.ids
    return cache[path]


def check_page(page: Path, errors: List[str], id_cache: Dict[Path, List[str]]) -> int:
    rel = page.relative_to(SITE).as_posix()
    p = PageParser()
    p.feed(page.read_text(encoding="utf-8"))
    id_cache[page.resolve()] = p.ids

    def err(msg: str) -> None:
        errors.append(f"{rel}: {msg}")

    if p.h1_count != 1:
        err(f"expected exactly one <h1>, found {p.h1_count}")
    if not p.lang:
        err("missing <html lang>")
    if "viewport" not in p.meta:
        err("missing viewport meta")
    title = norm(p.title)
    if not title:
        err("missing <title>")
    elif len(title) > TITLE_MAX:
        err(f"<title> is {len(title)} chars (max {TITLE_MAX}): {title!r}")
    desc = p.meta.get("description", "")
    if not desc:
        err("missing meta description")
    elif len(desc) > DESC_MAX:
        err(f"meta description is {len(desc)} chars (max {DESC_MAX})")

    is_404 = page.name == "404.html"
    if is_404:
        if "noindex" not in p.meta.get("robots", ""):
            err("404 page must be noindex")
    elif not p.canonical:
        err("missing canonical link")
    elif not p.canonical.startswith(BASE):
        err(f"canonical {p.canonical!r} is not under {BASE}")
    else:
        target = url_to_file(p.canonical)
        if target is None or target.resolve() != page.resolve():
            err(f"canonical {p.canonical!r} does not point at this page")

    faq_blocks: List[dict] = []
    for i, raw in enumerate(p.jsonld, 1):
        try:
            data = json.loads(raw)
        except ValueError as exc:
            err(f"JSON-LD block {i} does not parse: {exc}")
            continue
        bad = sorted(set(walk_keys(data)) & set(FORBIDDEN_LD_KEYS))
        if bad:
            err(f"JSON-LD block {i} contains unverifiable claim keys: {', '.join(bad)}")
        faq_blocks.extend(find_type(data, "FAQPage"))

    if faq_blocks or p.faq:
        if len(faq_blocks) != 1:
            err(f"expected one FAQPage block to match the visible FAQ, found {len(faq_blocks)}")
        else:
            ld_faq = [
                (norm(q.get("name", "")), norm(q.get("acceptedAnswer", {}).get("text", "")))
                for q in faq_blocks[0].get("mainEntity", [])
            ]
            if ld_faq != p.faq:
                if len(ld_faq) != len(p.faq):
                    err(f"FAQPage has {len(ld_faq)} questions, visible FAQ has {len(p.faq)}")
                for (lq, la), (vq, va) in zip(ld_faq, p.faq):
                    if lq != vq:
                        err(f"FAQ question differs: JSON-LD {lq!r} vs visible {vq!r}")
                    elif la != va:
                        err(f"FAQ answer differs for {vq!r}")
            for q, a in p.faq:
                if not q or not a:
                    err(f"FAQ entry missing question or answer: {q!r}")

    for ref in p.links:
        target, frag = resolve_local(page, ref)
        if target is None:
            continue
        if not target.is_file():
            err(f"broken local link {ref!r}")
            continue
        try:
            target.resolve().relative_to(SITE.resolve())
        except ValueError:
            err(f"link {ref!r} escapes site/")
            continue
        if frag and target.suffix == ".html" and frag not in ids_of(target.resolve(), id_cache):
            err(f"link {ref!r} points at missing #{frag}")
    return len(p.faq)


def check_sitemap(errors: List[str]) -> List[str]:
    path = SITE / "sitemap.xml"
    if not path.is_file():
        errors.append("sitemap.xml: missing")
        return []
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    try:
        root = ET.parse(str(path)).getroot()
    except ET.ParseError as exc:
        errors.append(f"sitemap.xml: does not parse: {exc}")
        return []
    locs = [el.text or "" for el in root.findall("s:url/s:loc", ns)]
    if not locs:
        errors.append("sitemap.xml: no <loc> entries")
    for loc in locs:
        target = url_to_file(loc) if loc.startswith(BASE) else None
        if target is None or not target.is_file():
            errors.append(f"sitemap.xml: {loc} does not map to a page in site/")
    for el in root.findall("s:url/s:lastmod", ns):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", (el.text or "").strip()):
            errors.append(f"sitemap.xml: lastmod {el.text!r} is not YYYY-MM-DD")
    return locs


def check_llms(name: str, errors: List[str], require_h1: bool) -> int:
    path = SITE / name
    if not path.is_file():
        errors.append(f"{name}: missing")
        return 0
    text = path.read_text(encoding="utf-8")
    if require_h1:
        lines = text.splitlines()
        if not lines or not lines[0].startswith("# "):
            errors.append(f"{name}: first line must be an H1 ('# Title')")
        if not any(line.startswith("> ") for line in lines):
            errors.append(f"{name}: missing blockquote summary")
    links = re.findall(r"\]\((https?://[^)\s]+)\)", text) + re.findall(r"(?<![(\w])(https://stylusnexus\.github\.io/[^\s)]+)", text)
    count = 0
    for url in links:
        count += 1
        if url.startswith(BASE):
            target = url_to_file(url)
            if target is None or not target.is_file():
                errors.append(f"{name}: link {url} does not resolve to a file in site/")
        elif not url.startswith("https://"):
            errors.append(f"{name}: link {url} is not https")
    return count


def check_robots(errors: List[str]) -> None:
    path = SITE / "robots.txt"
    if not path.is_file():
        errors.append("robots.txt: missing")
        return
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    sitemaps = [line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("sitemap:")]
    if not sitemaps:
        errors.append("robots.txt: no Sitemap: line")
    for url in sitemaps:
        target = url_to_file(url)
        if target is None or not target.is_file() or target.name != "sitemap.xml":
            errors.append(f"robots.txt: Sitemap {url} does not point at site/sitemap.xml")
    if any(line.lower().startswith("disallow: /") and line.strip().lower() == "disallow: /" for line in lines):
        errors.append("robots.txt: a Disallow: / rule blocks crawlers")


def main() -> int:
    if not SITE.is_dir():
        print(f"site/ not found at {SITE}")
        return 1
    errors: List[str] = []
    id_cache: Dict[Path, List[str]] = {}
    pages = sorted(SITE.rglob("*.html"))
    faq_total = 0
    for page in pages:
        faq_total += check_page(page, errors, id_cache)
    locs = check_sitemap(errors)
    llms_links = check_llms("llms.txt", errors, require_h1=True)
    full_links = check_llms("llms-full.txt", errors, require_h1=True)
    check_robots(errors)

    print(f"pages checked: {len(pages)} ({', '.join(p.relative_to(SITE).as_posix() for p in pages)})")
    print(f"visible FAQ entries matched to FAQPage: {faq_total}")
    print(f"sitemap URLs: {len(locs)}; llms.txt links: {llms_links}; llms-full.txt links: {full_links}")
    if errors:
        print(f"\nFAILED with {len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("site check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
