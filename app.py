import csv
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
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, W, Button, Entry, Frame, Label, StringVar, Tk, ttk, messagebox


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
}


@dataclass
class Listing:
    title: str
    price: str
    location: str
    url: str
    image_url: str = ""


class DaangnCrawler:
    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def search(self, keyword: str, max_pages: int = 3):
        dedupe = set()
        results = []
        for page in range(1, max_pages + 1):
            html = self._fetch_page(keyword, page)
            parsed = self._parse_from_json_ld(html)
            if not parsed:
                parsed = self._parse_from_next_data(html)
            if not parsed:
                parsed = self._parse_with_regex(html)

            if not parsed:
                break

            new_items = 0
            for item in parsed:
                if item.url in dedupe:
                    continue
                dedupe.add(item.url)
                results.append(item)
                new_items += 1

            if new_items == 0:
                break

        return results

    def _fetch_page(self, keyword: str, page: int) -> str:
        query = urllib.parse.urlencode({"in": "all", "search": keyword, "page": page})
        url = f"{BASE_URL}?{query}"
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _parse_from_json_ld(self, html: str):
        results = []
        blocks = re.findall(
            r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        for block in blocks:
            cleaned = block.strip()
            if not cleaned:
                continue
            try:
                data = json.loads(cleaned)
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
                url = str(item.get("url", "")).strip()
                if url.startswith("/"):
                    url = f"https://www.daangn.com{url}"
                if not url:
                    continue

                offers = item.get("offers") if isinstance(item.get("offers"), dict) else {}
                price = str(offers.get("price", "가격 정보 없음")).strip()

                location = "지역 정보 없음"
                area = item.get("areaServed")
                if isinstance(area, dict):
                    location = str(area.get("name", location)).strip() or location

                image_url = self._extract_image(item)
                results.append(Listing(title=title, price=price, location=location, url=url, image_url=image_url))

        return results

    def _parse_from_next_data(self, html: str):
        match = re.search(
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not match:
            return []

        try:
            payload = json.loads(match.group(1).strip())
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
                if raw_url:
                    if raw_url.startswith("/"):
                        raw_url = f"https://www.daangn.com{raw_url}"
                    if "/buy-sell/articles/" in raw_url:
                        title = str(obj.get("title") or obj.get("name") or "(제목 없음)").strip()
                        price = (
                            str(obj.get("priceString") or obj.get("price") or obj.get("priceText") or "가격 정보 없음")
                            .strip()
                        )
                        location = (
                            str(obj.get("regionName") or obj.get("dong") or obj.get("address") or "지역 정보 없음")
                            .strip()
                        )
                        image_url = self._extract_image(obj)
                        output.append(Listing(title=title, price=price, location=location, url=raw_url, image_url=image_url))

            for value in obj.values():
                self._collect_listings_from_obj(value, output)
        elif isinstance(obj, list):
            for item in obj:
                self._collect_listings_from_obj(item, output)

    def _parse_with_regex(self, html: str):
        results = []
        pattern = re.compile(
            r'<a[^>]+href="(?P<href>/kr/buy-sell/articles/\d+)"[^>]*>(?P<body>.*?)</a>',
            re.DOTALL | re.IGNORECASE,
        )
        for match in pattern.finditer(html):
            href = match.group("href")
            body = match.group("body")

            title_match = re.search(r"<h2[^>]*>(.*?)</h2>", body, re.DOTALL | re.IGNORECASE)
            price_match = re.search(r"<div[^>]*class=\"[^\"]*price[^\"]*\"[^>]*>(.*?)</div>", body, re.DOTALL | re.IGNORECASE)
            location_match = re.search(r"<div[^>]*class=\"[^\"]*region[^\"]*\"[^>]*>(.*?)</div>", body, re.DOTALL | re.IGNORECASE)
            image_match = re.search(r"<img[^>]+src=\"([^\"]+)\"", body, re.DOTALL | re.IGNORECASE)

            title = self._strip_html(title_match.group(1)) if title_match else "(제목 없음)"
            price = self._strip_html(price_match.group(1)) if price_match else "가격 정보 없음"
            location = self._strip_html(location_match.group(1)) if location_match else "지역 정보 없음"
            image_url = image_match.group(1).strip() if image_match else ""

            url = f"https://www.daangn.com{href}"
            results.append(Listing(title=title, price=price, location=location, url=url, image_url=image_url))

        return results

    @staticmethod
    def _strip_html(text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", text)
        return unescape(re.sub(r"\s+", " ", text)).strip()

    @staticmethod
    def _extract_image(obj) -> str:
        for key in ("image", "imageUrl", "thumbnail", "thumbnailUrl", "imageURL", "thumbUrl"):
            value = obj.get(key) if isinstance(obj, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        return item.strip()
                    if isinstance(item, dict):
                        nested = item.get("url") or item.get("src")
                        if isinstance(nested, str) and nested.strip():
                            return nested.strip()
            if isinstance(value, dict):
                nested = value.get("url") or value.get("src")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()

        files = obj.get("images") if isinstance(obj, dict) else None
        if isinstance(files, list):
            for item in files:
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
        self.root.geometry("1200x700")

        self.keyword_var = StringVar()
        self.max_pages_var = StringVar(value="5")
        self.preview_var = StringVar(value="사진 URL: (선택된 항목 없음)")

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
        Entry(top, textvariable=self.keyword_var, width=28).pack(side=LEFT, padx=8)

        Label(top, text="최대 페이지").pack(side=LEFT)
        Entry(top, textvariable=self.max_pages_var, width=6).pack(side=LEFT, padx=8)

        Button(top, text="검색 시작", command=self.on_search).pack(side=LEFT, padx=4)
        Button(top, text="선택 상품 열기", command=self.on_open_selected).pack(side=LEFT, padx=4)
        Button(top, text="선택 사진 열기", command=self.on_open_selected_image).pack(side=LEFT, padx=4)
        Button(top, text="CSV 저장", command=self.on_export).pack(side=LEFT, padx=4)

        self.status_label = Label(top, text="대기 중", anchor=W)
        self.status_label.pack(side=RIGHT)

        table_frame = Frame(self.root)
        table_frame.pack(fill=BOTH, expand=True, padx=12, pady=(0, 6))

        cols = ("title", "price", "location", "url", "image")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        self.tree.heading("title", text="제목")
        self.tree.heading("price", text="가격")
        self.tree.heading("location", text="지역")
        self.tree.heading("url", text="URL")
        self.tree.heading("image", text="사진")

        self.tree.column("title", width=280, anchor=W)
        self.tree.column("price", width=120, anchor=W)
        self.tree.column("location", width=160, anchor=W)
        self.tree.column("url", width=350, anchor=W)
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
            messagebox.showwarning("입력 오류", "최대 페이지는 1~50 사이 숫자여야 합니다.")
            return

        self.status_label.config(text="검색 중...")
        self.results = []
        self.url_to_listing = {}
        self.preview_var.set("사진 URL: (선택된 항목 없음)")
        self.tree.delete(*self.tree.get_children())

        thread = threading.Thread(
            target=self._search_worker,
            args=(keyword, max_pages),
            daemon=True,
        )
        thread.start()

    def _search_worker(self, keyword: str, max_pages: int):
        try:
            results = self.crawler.search(keyword=keyword, max_pages=max_pages)
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
                        image_cell = item.image_url if item.image_url else "(사진 없음)"
                        self.tree.insert("", END, values=(item.title, item.price, item.location, item.url, image_cell))
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
        if len(values) < 4:
            return None
        return self.url_to_listing.get(values[3])

    def on_open_selected(self):
        listing = self._get_selected_listing()
        if not listing:
            messagebox.showinfo("상품 열기", "먼저 목록에서 상품 1개를 선택해주세요.")
            return
        webbrowser.open(listing.url)

    def on_open_selected_image(self):
        listing = self._get_selected_listing()
        if not listing:
            messagebox.showinfo("사진 열기", "먼저 목록에서 상품 1개를 선택해주세요.")
            return
        if not listing.image_url:
            messagebox.showinfo("사진 열기", "해당 상품은 사진 URL을 찾지 못했습니다.")
            return
        webbrowser.open(listing.image_url)

    def on_row_double_click(self, _event):
        self.on_open_selected()

    def on_selection_changed(self, _event):
        listing = self._get_selected_listing()
        if not listing:
            self.preview_var.set("사진 URL: (선택된 항목 없음)")
            return
        if listing.image_url:
            self.preview_var.set(f"사진 URL: {listing.image_url}")
        else:
            self.preview_var.set("사진 URL: (이 상품은 사진 URL이 없습니다)")

    def on_export(self):
        if not self.results:
            messagebox.showinfo("내보내기", "먼저 검색을 실행해주세요.")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"daangn_search_{ts}.csv"
        with open(filename, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["title", "price", "location", "url", "image_url"])
            for row in self.results:
                writer.writerow([row.title, row.price, row.location, row.url, row.image_url])

        messagebox.showinfo("저장 완료", f"{filename} 파일로 저장했습니다.")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
