import csv
import gzip
import json
import queue
import re
import threading
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, W, Button, Checkbutton, Entry, Frame, IntVar, Label, StringVar, Tk, ttk, messagebox

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
BASE_URL = "https://www.daangn.com/kr/buy-sell/"
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Accept-Encoding": "gzip, deflate",
}


@dataclass
class Listing:
    title: str
    price: str
    location: str
    url: str
    image_url: str = ""
    source: str = "daangn"


class DaangnCrawler:
    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def search(self, keyword: str, max_pages: int = 3, include_sitemap_boost: bool = True, sitemap_only: bool = False, region_expand: bool = True):
        dedupe = set()
        results = []

        if not sitemap_only:
            for item in self._search_from_daangn(keyword, max_pages, region_expand=region_expand):
                if item.url in dedupe:
                    continue
                dedupe.add(item.url)
                results.append(item)

        if include_sitemap_boost or sitemap_only:
            sitemap_results = self._search_from_sitemap(keyword, max_pages)
            for item in sitemap_results:
                if item.url in dedupe:
                    continue
                dedupe.add(item.url)
                results.append(item)

            # 전국만 모드인데 사이트맵 수집이 0건이면, 완전 0건 방지를 위해 지역확장 검색으로 폴백
            if sitemap_only and not sitemap_results:
                for item in self._search_from_daangn(keyword, max_pages, region_expand=True):
                    if item.url in dedupe:
                        continue
                    item.source = "daangn-fallback"
                    dedupe.add(item.url)
                    results.append(item)

        return results

    def _search_from_daangn(self, keyword: str, max_pages: int, region_expand: bool = True):
        results = []
        seen = set()

        queries = self._build_region_queries(keyword) if region_expand else [keyword]
        max_queries = min(len(queries), 12)
        per_query_pages = max(1, max_pages // max_queries)

        for q in queries[:max_queries]:
            for page in range(1, per_query_pages + 1):
                html = self._fetch_search_page(q, page)
                parsed = self._parse_from_json_ld(html)
                if not parsed:
                    parsed = self._parse_from_next_data(html)
                if not parsed:
                    parsed = self._parse_with_regex(html)
                if not parsed:
                    break

                new_count = 0
                for item in parsed:
                    if item.url in seen:
                        continue
                    seen.add(item.url)
                    results.append(item)
                    new_count += 1
                if new_count == 0:
                    break

        return results

    @staticmethod
    def _build_region_queries(keyword: str):
        keyword = keyword.strip()
        regions = [
            "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
            "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
        ]
        queries = [keyword]
        for r in regions:
            queries.append(f"{r} {keyword}")
        return queries

    def _search_from_sitemap(self, keyword: str, max_pages: int):
        keyword_norm = keyword.lower().strip()
        results = []
        article_urls = self._collect_article_urls_from_sitemaps(max_pages=max_pages)

        # 느리지 않도록 상한
        scan_limit = min(len(article_urls), max_pages * 300)
        for article_url in article_urls[:scan_limit]:
            try:
                html = self._fetch_url_text(article_url)
                listing = self._parse_listing_page(article_url, html)
            except Exception:
                continue

            hay = f"{listing.title} {listing.location}".lower()
            if keyword_norm and keyword_norm not in hay:
                # 제목/지역 외 본문 텍스트도 얕게 확인
                if keyword_norm not in self._strip_html(html).lower():
                    continue

            listing.source = "sitemap"
            results.append(listing)

        return results

    def _collect_article_urls_from_sitemaps(self, max_pages: int):
        sitemap_urls = self._discover_sitemap_urls()
        article_urls = []
        seen = set()

        # 최신 사이트맵 일부만 사용 (속도/부하 고려)
        use_count = min(len(sitemap_urls), max_pages)
        for sitemap_url in sitemap_urls[:use_count]:
            try:
                xml_text = self._fetch_url_text(sitemap_url)
            except Exception:
                continue

            for loc in re.findall(r"<loc>(.*?)</loc>", xml_text, flags=re.IGNORECASE):
                u = unescape(loc.strip())
                if "/kr/buy-sell/articles/" not in u:
                    continue
                nu = self._normalize_article_url(u)
                if nu in seen:
                    continue
                seen.add(nu)
                article_urls.append(nu)

        return article_urls

    def _discover_sitemap_urls(self):
        candidates = [
            "https://www.daangn.com/robots.txt",
            "https://www.daangn.com/sitemap.xml",
            "https://www.daangn.com/sitemap_index.xml",
            "https://www.daangn.com/sitemaps/sitemap-index.xml",
        ]

        discovered = []

        # 1) robots.txt의 Sitemap 항목 우선 활용
        try:
            robots = self._fetch_url_text("https://www.daangn.com/robots.txt")
            for line in robots.splitlines():
                if line.lower().startswith("sitemap:"):
                    u = line.split(":", 1)[1].strip()
                    if u:
                        discovered.append(u)
        except Exception:
            pass

        # 2) 후보 sitemap index 파싱
        for url in candidates:
            if not url.endswith(".xml"):
                continue
            try:
                xml_text = self._fetch_url_text(url)
            except Exception:
                continue

            locs = [unescape(x.strip()) for x in re.findall(r"<loc>(.*?)</loc>", xml_text, flags=re.IGNORECASE)]
            # index가 아니라 urlset(게시글 loc 직접 포함)일 수도 있으므로 원본 url도 유지
            if "/kr/buy-sell/articles/" in xml_text:
                discovered.append(url)

            article_first = [x for x in locs if "sitemap" in x.lower() and ("buy-sell" in x or "article" in x)]
            all_sitemaps = [x for x in locs if "sitemap" in x.lower()]

            discovered.extend(article_first)
            discovered.extend([x for x in all_sitemaps if x not in article_first])

        # fallback: 최소 후보 보장
        discovered.extend([
            "https://www.daangn.com/sitemap.xml",
            "https://www.daangn.com/sitemap_index.xml",
        ])

        uniq = []
        seen = set()
        for u in discovered:
            if u in seen:
                continue
            seen.add(u)
            uniq.append(u)
        uniq.reverse()
        return uniq

    def _fetch_search_page(self, keyword: str, page: int) -> str:
        query = urllib.parse.urlencode({"in": "all", "search": keyword, "page": page})
        return self._fetch_url_text(f"{BASE_URL}?{query}")

    def _fetch_url_text(self, url: str) -> str:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read()
            encoding = (resp.headers.get("Content-Encoding") or "").lower()

        if raw[:2] == b"\x1f\x8b" or "gzip" in encoding or url.endswith(".gz"):
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass

        return raw.decode("utf-8", errors="ignore")

    def _parse_from_json_ld(self, html: str):
        results = []
        blocks = re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, flags=re.DOTALL | re.IGNORECASE)
        for block in blocks:
            try:
                data = json.loads(block.strip())
            except json.JSONDecodeError:
                continue

            items = []
            if isinstance(data, dict) and "itemListElement" in data:
                items = data.get("itemListElement", [])
            elif isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict) and "itemListElement" in entry:
                        items.extend(entry.get("itemListElement", []))

            for raw in items:
                item = raw.get("item") if isinstance(raw, dict) else None
                if not isinstance(item, dict):
                    continue

                title = str(item.get("name", "")).strip() or "(제목 없음)"
                raw_url = str(item.get("url", "")).strip()
                if raw_url.startswith("/"):
                    raw_url = f"https://www.daangn.com{raw_url}"
                if not raw_url:
                    continue

                offers = item.get("offers") if isinstance(item.get("offers"), dict) else {}
                price = str(offers.get("price", "가격 정보 없음")).strip()
                area = item.get("areaServed") if isinstance(item.get("areaServed"), dict) else {}
                location = str(area.get("name", "지역 정보 없음")).strip() or "지역 정보 없음"

                results.append(
                    Listing(
                        title=title,
                        price=price,
                        location=location,
                        url=self._normalize_article_url(raw_url),
                        image_url=self._extract_image(item),
                        source="daangn",
                    )
                )
        return results

    def _parse_from_next_data(self, html: str):
        m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, flags=re.DOTALL | re.IGNORECASE)
        if not m:
            return []
        try:
            payload = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            return []

        results = []
        self._collect_listings_from_obj(payload, results)
        return results

    def _collect_listings_from_obj(self, obj, output):
        if isinstance(obj, dict):
            has_title = any(k in obj for k in ("title", "name"))
            has_url = any(k in obj for k in ("url", "path", "link"))
            if has_title and has_url:
                raw_url = str(obj.get("url") or obj.get("path") or obj.get("link") or "").strip()
                if raw_url.startswith("/"):
                    raw_url = f"https://www.daangn.com{raw_url}"
                if "/buy-sell/articles/" in raw_url:
                    output.append(
                        Listing(
                            title=str(obj.get("title") or obj.get("name") or "(제목 없음)").strip(),
                            price=str(obj.get("priceString") or obj.get("price") or obj.get("priceText") or "가격 정보 없음").strip(),
                            location=str(obj.get("regionName") or obj.get("dong") or obj.get("address") or "지역 정보 없음").strip(),
                            url=self._normalize_article_url(raw_url),
                            image_url=self._extract_image(obj),
                            source="daangn",
                        )
                    )

            for v in obj.values():
                self._collect_listings_from_obj(v, output)
        elif isinstance(obj, list):
            for x in obj:
                self._collect_listings_from_obj(x, output)

    def _parse_with_regex(self, html: str):
        results = []
        pattern = re.compile(r'<a[^>]+href="(?P<href>/kr/buy-sell/articles/\d+)"[^>]*>(?P<body>.*?)</a>', re.DOTALL | re.IGNORECASE)
        for match in pattern.finditer(html):
            body = match.group("body")
            href = match.group("href")
            title_match = re.search(r"<h2[^>]*>(.*?)</h2>", body, re.DOTALL | re.IGNORECASE)
            price_match = re.search(r"<div[^>]*class=\"[^\"]*price[^\"]*\"[^>]*>(.*?)</div>", body, re.DOTALL | re.IGNORECASE)
            location_match = re.search(r"<div[^>]*class=\"[^\"]*region[^\"]*\"[^>]*>(.*?)</div>", body, re.DOTALL | re.IGNORECASE)
            image_match = re.search(r"<img[^>]+src=\"([^\"]+)\"", body, re.IGNORECASE)

            results.append(
                Listing(
                    title=self._strip_html(title_match.group(1)) if title_match else "(제목 없음)",
                    price=self._strip_html(price_match.group(1)) if price_match else "가격 정보 없음",
                    location=self._strip_html(location_match.group(1)) if location_match else "지역 정보 없음",
                    url=self._normalize_article_url(f"https://www.daangn.com{href}"),
                    image_url=image_match.group(1).strip() if image_match else "",
                    source="daangn",
                )
            )
        return results

    def _parse_listing_page(self, url: str, html: str):
        title = self._extract_meta(html, "property", "og:title") or self._extract_title(html) or "(제목 없음)"
        image_url = self._extract_meta(html, "property", "og:image")
        price = "가격 정보 없음"
        location = "지역 정보 없음"

        for block in re.findall(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, flags=re.DOTALL | re.IGNORECASE):
            try:
                data = json.loads(block.strip())
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                offers = data.get("offers") if isinstance(data.get("offers"), dict) else {}
                if offers.get("price"):
                    price = str(offers.get("price"))
                area = data.get("areaServed") if isinstance(data.get("areaServed"), dict) else {}
                if area.get("name"):
                    location = str(area.get("name"))

        return Listing(
            title=self._strip_html(title),
            price=self._strip_html(price),
            location=self._strip_html(location),
            url=self._normalize_article_url(url),
            image_url=image_url,
            source="sitemap",
        )

    @staticmethod
    def _extract_meta(html: str, attr: str, attr_value: str) -> str:
        m = re.search(rf'<meta[^>]+{attr}="{re.escape(attr_value)}"[^>]+content="([^"]+)"', html, flags=re.IGNORECASE)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _extract_title(html: str) -> str:
        m = re.search(r"<title>(.*?)</title>", html, flags=re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _normalize_article_url(url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        if "/kr/buy-sell/articles/" in parsed.path:
            return f"https://www.daangn.com{parsed.path}"
        return url.split("?")[0]

    @staticmethod
    def _strip_html(text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", text)
        return unescape(re.sub(r"\s+", " ", text)).strip()

    @staticmethod
    def _extract_image(obj) -> str:
        if not isinstance(obj, dict):
            return ""
        for key in ("image", "imageUrl", "thumbnail", "thumbnailUrl", "imageURL", "thumbUrl", "images"):
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = value.get("url") or value.get("src")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        return item.strip()
                    if isinstance(item, dict):
                        nested = item.get("url") or item.get("src")
                        if isinstance(nested, str) and nested.strip():
                            return nested.strip()
        return ""


class App:
    def __init__(self):
        self.root = Tk()
        self.root.title("당근 전국 통합 검색기 (비공식)")
        self.root.geometry("1280x720")

        self.keyword_var = StringVar()
        self.max_pages_var = StringVar(value="5")
        self.preview_var = StringVar(value="사진 URL: (선택된 항목 없음)")
        self.include_sitemap_boost_var = IntVar(value=1)
        self.sitemap_only_var = IntVar(value=0)
        self.region_expand_var = IntVar(value=1)

        self.crawler = DaangnCrawler()
        self.queue = queue.Queue()
        self.results = []
        self.url_to_listing = {}

        self._build_ui()
        self.root.after(200, self._poll_queue)

    def _build_ui(self):
        top = Frame(self.root)
        top.pack(fill="x", padx=12, pady=10)

        Label(top, text="키워드").pack(side=LEFT)
        Entry(top, textvariable=self.keyword_var, width=22).pack(side=LEFT, padx=8)

        Label(top, text="최대 페이지").pack(side=LEFT)
        Entry(top, textvariable=self.max_pages_var, width=6).pack(side=LEFT, padx=8)

        Checkbutton(top, text="전국 보강(사이트맵 스캔)", variable=self.include_sitemap_boost_var).pack(side=LEFT, padx=(6, 8))
        Checkbutton(top, text="전국만(로컬검색 제외)", variable=self.sitemap_only_var).pack(side=LEFT, padx=(0, 8))
        Checkbutton(top, text="시/도 확장 검색", variable=self.region_expand_var).pack(side=LEFT, padx=(0, 14))

        Button(top, text="검색 시작", command=self.on_search).pack(side=LEFT, padx=4)
        Button(top, text="선택 상품 열기", command=self.on_open_selected).pack(side=LEFT, padx=4)
        Button(top, text="선택 사진 열기", command=self.on_open_selected_image).pack(side=LEFT, padx=4)
        Button(top, text="CSV 저장", command=self.on_export).pack(side=LEFT, padx=4)

        self.status_label = Label(top, text="대기 중", anchor=W)
        self.status_label.pack(side=RIGHT)

        table_frame = Frame(self.root)
        table_frame.pack(fill=BOTH, expand=True, padx=12, pady=(0, 6))

        cols = ("title", "price", "location", "source", "url", "image")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        for col, text in (
            ("title", "제목"),
            ("price", "가격"),
            ("location", "지역"),
            ("source", "수집경로"),
            ("url", "URL"),
            ("image", "사진"),
        ):
            self.tree.heading(col, text=text)

        self.tree.column("title", width=250, anchor=W)
        self.tree.column("price", width=100, anchor=W)
        self.tree.column("location", width=140, anchor=W)
        self.tree.column("source", width=80, anchor=W)
        self.tree.column("url", width=380, anchor=W)
        self.tree.column("image", width=260, anchor=W)

        scrollbar = ttk.Scrollbar(table_frame, orient=VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill="y")

        self.tree.bind("<Double-1>", self.on_row_double_click)
        self.tree.bind("<<TreeviewSelect>>", self.on_selection_changed)

        preview = Frame(self.root)
        preview.pack(fill="x", padx=12, pady=(0, 12))
        Label(preview, textvariable=self.preview_var, anchor=W).pack(fill="x")

    def on_search(self):
        keyword = self.keyword_var.get().strip()
        if not keyword:
            messagebox.showwarning("입력 필요", "검색할 키워드를 입력해주세요.")
            return

        try:
            max_pages = int(self.max_pages_var.get())
            if max_pages < 1 or max_pages > 50:
                raise ValueError
        except ValueError:
            messagebox.showwarning("입력 오류", "최대 페이지는 1~50 숫자여야 합니다.")
            return

        include_sitemap_boost = bool(self.include_sitemap_boost_var.get())
        sitemap_only = bool(self.sitemap_only_var.get())
        region_expand = bool(self.region_expand_var.get())

        self.status_label.config(text="검색 중...")
        self.results = []
        self.url_to_listing = {}
        self.preview_var.set("사진 URL: (선택된 항목 없음)")
        self.tree.delete(*self.tree.get_children())

        th = threading.Thread(target=self._search_worker, args=(keyword, max_pages, include_sitemap_boost, sitemap_only, region_expand), daemon=True)
        th.start()

    def _search_worker(self, keyword: str, max_pages: int, include_sitemap_boost: bool, sitemap_only: bool, region_expand: bool):
        try:
            results = self.crawler.search(
                keyword,
                max_pages=max_pages,
                include_sitemap_boost=include_sitemap_boost,
                sitemap_only=sitemap_only,
                region_expand=region_expand,
            )
            self.queue.put(("success", results))
        except Exception as exc:  # noqa: BLE001
            self.queue.put(("error", str(exc)))

    def _poll_queue(self):
        try:
            while True:
                status, payload = self.queue.get_nowait()
                if status == "success":
                    self.results = payload
                    self.url_to_listing = {item.url: item for item in payload}
                    for item in payload:
                        img = item.image_url if item.image_url else "(사진 없음)"
                        self.tree.insert("", END, values=(item.title, item.price, item.location, item.source, item.url, img))
                    fallback_count = sum(1 for x in payload if x.source == "daangn-fallback")
                    if fallback_count:
                        self.status_label.config(text=f"완료: {len(payload)}건 (전국만 폴백 {fallback_count}건)")
                    else:
                        self.status_label.config(text=f"완료: {len(payload)}건")
                else:
                    self.status_label.config(text="오류 발생")
                    messagebox.showerror("검색 실패", payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(200, self._poll_queue)

    def _get_selected_listing(self):
        selected = self.tree.selection()
        if not selected:
            return None
        values = self.tree.item(selected[0], "values")
        if len(values) < 5:
            return None
        return self.url_to_listing.get(values[4])

    def on_open_selected(self):
        item = self._get_selected_listing()
        if not item:
            messagebox.showinfo("상품 열기", "먼저 목록에서 상품을 선택해주세요.")
            return
        webbrowser.open(item.url)

    def on_open_selected_image(self):
        item = self._get_selected_listing()
        if not item:
            messagebox.showinfo("사진 열기", "먼저 목록에서 상품을 선택해주세요.")
            return
        if not item.image_url:
            messagebox.showinfo("사진 열기", "해당 상품은 사진 URL이 없습니다.")
            return
        webbrowser.open(item.image_url)

    def on_row_double_click(self, _event):
        self.on_open_selected()

    def on_selection_changed(self, _event):
        item = self._get_selected_listing()
        if not item:
            self.preview_var.set("사진 URL: (선택된 항목 없음)")
            return
        self.preview_var.set(f"사진 URL: {item.image_url or '(이 상품은 사진 URL이 없습니다)'}")

    def on_export(self):
        if not self.results:
            messagebox.showinfo("내보내기", "먼저 검색을 실행해주세요.")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"daangn_search_{ts}.csv"
        with open(filename, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["title", "price", "location", "source", "url", "image_url"])
            for row in self.results:
                writer.writerow([row.title, row.price, row.location, row.source, row.url, row.image_url])

        messagebox.showinfo("저장 완료", f"{filename} 파일로 저장했습니다.")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
