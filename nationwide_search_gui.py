#!/usr/bin/env python3
"""당근마켓 전국 검색 GUI."""

from __future__ import annotations

import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from search_core import (
    Item,
    install_chromium,
    load_regions,
    run_search_sync,
    save_csv,
    save_json,
)


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("당근마켓 전국 검색기")
        self.root.geometry("980x700")

        self.keyword_var = tk.StringVar()
        self.region_file_var = tk.StringVar(value="regions.txt")
        self.delay_var = tk.IntVar(value=1200)
        self.headless_var = tk.BooleanVar(value=True)

        self.items: list[Item] = []
        self.running = False

        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="키워드").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.keyword_var, width=25).grid(row=0, column=1, sticky="we", padx=6)

        ttk.Label(top, text="지역 파일").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.region_file_var, width=35).grid(row=0, column=3, sticky="we", padx=6)
        ttk.Button(top, text="찾아보기", command=self.browse_region_file).grid(row=0, column=4, padx=4)

        ttk.Label(top, text="대기(ms)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(top, textvariable=self.delay_var, width=10).grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))

        ttk.Checkbutton(top, text="백그라운드 실행(브라우저 숨김)", variable=self.headless_var).grid(
            row=1, column=3, sticky="w", pady=(8, 0)
        )

        button_wrap = ttk.Frame(top)
        button_wrap.grid(row=1, column=4, padx=4, pady=(8, 0), sticky="e")

        self.install_btn = ttk.Button(button_wrap, text="브라우저 설치", command=self.install_browser)
        self.install_btn.pack(side="left", padx=(0, 4))

        self.search_btn = ttk.Button(button_wrap, text="전국 검색 시작", command=self.start_search)
        self.search_btn.pack(side="left")

        for c in (1, 3):
            top.columnconfigure(c, weight=1)

        mid = ttk.Frame(self.root, padding=(12, 0, 12, 0))
        mid.pack(fill="both", expand=True)

        columns = ("region", "title", "price", "link")
        self.tree = ttk.Treeview(mid, columns=columns, show="headings", height=20)
        self.tree.heading("region", text="지역")
        self.tree.heading("title", text="제목")
        self.tree.heading("price", text="가격")
        self.tree.heading("link", text="링크")

        self.tree.column("region", width=160, anchor="w")
        self.tree.column("title", width=360, anchor="w")
        self.tree.column("price", width=100, anchor="center")
        self.tree.column("link", width=320, anchor="w")

        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(mid, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=vsb.set, xscroll=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self.open_selected_link)

        bottom = ttk.Frame(self.root, padding=12)
        bottom.pack(fill="x")

        ttk.Button(bottom, text="선택 링크 열기", command=self.open_selected_link).pack(side="left")
        ttk.Button(bottom, text="JSON 저장", command=self.save_json_file).pack(side="left", padx=6)
        ttk.Button(bottom, text="CSV 저장", command=self.save_csv_file).pack(side="left")

        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(bottom, textvariable=self.status_var).pack(side="right")

        log_frame = ttk.LabelFrame(self.root, text="진행 로그", padding=8)
        log_frame.pack(fill="both", expand=False, padx=12, pady=(0, 12))
        self.log_text = tk.Text(log_frame, height=8, state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def browse_region_file(self) -> None:
        path = filedialog.askopenfilename(title="지역 파일 선택", filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if path:
            self.region_file_var.set(path)

    def log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


    def install_browser(self) -> None:
        if self.running:
            return

        self.running = True
        self.search_btn.configure(state="disabled")
        self.install_btn.configure(state="disabled")
        self.status_var.set("브라우저 설치 중...")
        self.log("브라우저 설치 시작 (최초 1회 필요)")

        thread = threading.Thread(target=self._install_browser_thread, daemon=True)
        thread.start()

    def _install_browser_thread(self) -> None:
        try:
            install_chromium(progress_callback=lambda msg: self.root.after(0, self.log, msg))
            self.root.after(0, self.on_browser_install_done, None)
        except Exception as exc:
            self.root.after(0, self.on_browser_install_done, exc)

    def on_browser_install_done(self, error: Exception | None) -> None:
        self.running = False
        self.search_btn.configure(state="normal")
        self.install_btn.configure(state="normal")

        if error is not None:
            self.status_var.set("브라우저 설치 실패")
            self.log(f"브라우저 설치 실패: {error}")
            messagebox.showerror(
                "브라우저 설치 실패",
                "Playwright 브라우저 설치에 실패했습니다.\n"
                "네트워크 상태를 확인한 뒤 다시 시도해 주세요.\n\n"
                f"상세: {error}",
            )
            return

        self.status_var.set("브라우저 설치 완료")
        self.log("브라우저 설치 완료")
        messagebox.showinfo("완료", "브라우저 설치가 완료되었습니다. 이제 검색을 시작하세요.")

    def start_search(self) -> None:
        if self.running:
            return

        keyword = self.keyword_var.get().strip()
        if not keyword:
            messagebox.showwarning("입력 필요", "키워드를 입력하세요.")
            return

        try:
            regions = load_regions(self.region_file_var.get().strip())
        except Exception as exc:
            messagebox.showerror("지역 파일 오류", str(exc))
            return

        self.running = True
        self.search_btn.configure(state="disabled")
        self.install_btn.configure(state="disabled")
        self.status_var.set("전국 검색 진행 중...")
        self.log(f"검색 시작: '{keyword}' / 지역 {len(regions)}개")

        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self.items = []

        thread = threading.Thread(target=self._run_search_thread, args=(keyword, regions), daemon=True)
        thread.start()

    def _run_search_thread(self, keyword: str, regions: list[str]) -> None:
        try:
            items = run_search_sync(
                keyword=keyword,
                regions=regions,
                delay_ms=self.delay_var.get(),
                headless=self.headless_var.get(),
                progress_callback=lambda msg: self.root.after(0, self.log, msg),
            )
            self.root.after(0, self.on_search_done, items, None)
        except Exception as exc:
            self.root.after(0, self.on_search_done, [], exc)

    def on_search_done(self, items: list[Item], error: Exception | None) -> None:
        self.running = False
        self.search_btn.configure(state="normal")
        self.install_btn.configure(state="normal")

        if error is not None:
            self.status_var.set("실패")
            self.log(f"실패: {error}")
            messagebox.showerror("검색 실패", str(error))
            return

        self.items = items
        for item in items:
            self.tree.insert("", "end", values=(item.region, item.title, item.price, item.link))

        self.status_var.set(f"완료: 판매중 {len(items)}개")
        self.log(f"검색 완료: 판매중 {len(items)}개")

    def get_selected_link(self) -> str | None:
        selection = self.tree.selection()
        if not selection:
            return None
        values = self.tree.item(selection[0], "values")
        return str(values[3]) if len(values) >= 4 else None

    def open_selected_link(self, _event: object | None = None) -> None:
        link = self.get_selected_link()
        if not link:
            messagebox.showinfo("선택 필요", "상품 하나를 선택하세요.")
            return
        webbrowser.open(link)

    def save_json_file(self) -> None:
        if not self.items:
            messagebox.showinfo("결과 없음", "저장할 검색 결과가 없습니다.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="results.json")
        if path:
            save_json(path, self.items)
            self.log(f"JSON 저장 완료: {Path(path).name}")

    def save_csv_file(self) -> None:
        if not self.items:
            messagebox.showinfo("결과 없음", "저장할 검색 결과가 없습니다.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="results.csv")
        if path:
            save_csv(path, self.items)
            self.log(f"CSV 저장 완료: {Path(path).name}")


def main() -> None:
    root = tk.Tk()
    ttk.Style().theme_use("clam")
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
