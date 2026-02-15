#!/usr/bin/env python3
"""당근마켓 전국 검색 공통 로직."""

from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from urllib.parse import quote_plus

BASE_URL = "https://www.daangn.com/kr/buy-sell/"
SKIP_STATUS_KEYWORDS = ("판매완료", "거래완료", "예약중")


@dataclass(slots=True)
class Item:
    region: str
    title: str
    price: str
    link: str


def get_playwright_browser_path() -> Path:
    """브라우저 바이너리 저장 폴더를 고정해 EXE 임시폴더 이슈를 피합니다."""
    return Path.home() / ".daangn_playwright_browsers"


def _playwright_cli_candidates() -> list[list[str]]:
    """Playwright CLI 후보 명령 목록."""
    if not getattr(sys, "frozen", False):
        return [[sys.executable, "-m", "playwright"]]

    candidates = [
        ["py", "-m", "playwright"],
        ["python", "-m", "playwright"],
        ["python3", "-m", "playwright"],
    ]
    return [cmd for cmd in candidates if shutil.which(cmd[0])]


def _pip_cmd_from_playwright_cmd(playwright_cmd: Sequence[str]) -> list[str]:
    """playwright CLI 명령에 대응하는 pip 명령."""
    return [playwright_cmd[0], "-m", "pip", "install", "playwright"]


def _has_playwright_module(playwright_cmd: Sequence[str], env: dict[str, str]) -> bool:
    check_cmd = [*playwright_cmd, "--version"]
    proc = subprocess.run(check_cmd, env=env, capture_output=True, text=True)
    return proc.returncode == 0


def install_chromium(progress_callback: Callable[[str], None] | None = None) -> None:
    """Playwright Chromium 브라우저 설치."""
    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(get_playwright_browser_path())

    candidates = _playwright_cli_candidates()
    if not candidates:
        raise RuntimeError(
            "Python 실행 파일을 찾지 못했습니다. "
            "PowerShell에서 Python 설치 후 `python -m pip install playwright`를 실행해 주세요."
        )

    last_error: Exception | None = None
    for base_cmd in candidates:
        try:
            if progress_callback:
                progress_callback(f"Playwright 점검: {' '.join(base_cmd)}")

            if not _has_playwright_module(base_cmd, env):
                pip_cmd = _pip_cmd_from_playwright_cmd(base_cmd)
                if progress_callback:
                    progress_callback(f"Playwright 모듈 설치: {' '.join(pip_cmd)}")
                subprocess.run(pip_cmd, check=True, env=env)

            cmd = [*base_cmd, "install", "chromium"]
            if progress_callback:
                progress_callback(f"Playwright Chromium 설치 실행: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, env=env)
            if progress_callback:
                progress_callback("Playwright Chromium 설치 완료")
            return
        except Exception as exc:
            last_error = exc
            continue

    raise RuntimeError(
        "Chromium 설치에 실패했습니다. PowerShell에서 아래 명령을 순서대로 실행해 주세요.\n"
        "1) python -m pip install --upgrade pip\n"
        "2) python -m pip install playwright\n"
        "3) python -m playwright install chromium"
    ) from last_error


def resolve_default_regions_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.exists():
        return candidate

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        exe_candidate = exe_dir / path
        if exe_candidate.exists():
            return exe_candidate

        meipass = Path(getattr(sys, "_MEIPASS", ""))
        meipass_candidate = meipass / path
        if meipass_candidate.exists():
            return meipass_candidate

    return candidate


def load_regions(path: str) -> list[str]:
    file_path = resolve_default_regions_path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"지역 파일을 찾을 수 없습니다: {file_path}")

    regions = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            regions.append(value)

    if not regions:
        raise ValueError("지역 파일이 비어 있습니다.")
    return regions


async def safe_click(page: Any, selectors: Iterable[str], timeout_ms: int = 4_000) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        if await locator.count() == 0:
            continue
        try:
            await locator.click(timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False




async def read_current_region_label(page: Any) -> str:
    """헤더/상단에서 현재 선택된 지역 텍스트를 최대한 읽어냅니다."""
    selectors = (
        "header button:has-text('동네')",
        "header [aria-label*='동네']",
        "header [aria-label*='지역']",
        "header button",
        "header a",
    )
    for selector in selectors:
        locator = page.locator(selector).first
        if await locator.count() == 0:
            continue
        text = (await locator.inner_text()).strip()
        if text:
            return text
    return ""
async def change_region(page: Any, region: str, delay_ms: int) -> str:
    opened = await safe_click(
        page,
        selectors=(
            "button:has-text('동네')",
            "button:has-text('내 동네')",
            "button[aria-label*='동네']",
            "button[aria-label*='지역']",
            "header button:has(svg)",
        ),
    )
    if not opened:
        raise RuntimeError("지역 선택창을 열지 못했습니다.")

    text_input = None
    for selector in (
        "input[placeholder*='동네']",
        "input[placeholder*='지역']",
        "input[placeholder*='검색']",
        "input[type='search']",
        "input",
    ):
        locator = page.locator(selector).first
        if await locator.count() == 0:
            continue
        text_input = locator
        break

    if text_input is None:
        raise RuntimeError("지역 검색 입력창을 찾지 못했습니다.")

    tokens = [t for t in region.split() if t]
    candidates: list[str] = [region]
    if len(tokens) >= 2:
        candidates.append(" ".join(tokens[-2:]))
    if tokens:
        candidates.append(tokens[-1])

    seen: set[str] = set()
    query_candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    for query in query_candidates:
        await text_input.fill("")
        await text_input.fill(query)
        await page.wait_for_timeout(max(delay_ms, 900))

        clicked = await safe_click(
            page,
            selectors=(
                f"[role='option']:has-text('{region}')",
                f"li:has-text('{region}')",
                f"button:has-text('{region}')",
                f"a:has-text('{region}')",
                f"[role='option']:has-text('{query}')",
                f"li:has-text('{query}')",
                f"button:has-text('{query}')",
                f"a:has-text('{query}')",
                "[role='dialog'] [role='option']",
                "[role='listbox'] [role='option']",
                "[role='dialog'] li",
                "[aria-modal='true'] li",
            ),
            timeout_ms=2_000,
        )
        if not clicked:
            try:
                await text_input.press("ArrowDown")
                await text_input.press("Enter")
                clicked = True
            except Exception:
                clicked = False

        if not clicked:
            continue

        # 적용/확인 버튼이 있는 UI 대응
        await safe_click(
            page,
            selectors=(
                "button:has-text('적용')",
                "button:has-text('완료')",
                "button:has-text('확인')",
                "button:has-text('선택')",
            ),
            timeout_ms=1_200,
        )
        await page.wait_for_timeout(delay_ms)

        current = await read_current_region_label(page)
        if any(token in current for token in (region, query, tokens[-1] if tokens else query)):
            return current

        # 모달 닫기 후 다시 확인
        await safe_click(
            page,
            selectors=(
                "button[aria-label*='닫기']",
                "button:has-text('닫기')",
                "button:has-text('취소')",
            ),
            timeout_ms=800,
        )
        await page.wait_for_timeout(500)
        current = await read_current_region_label(page)
        if any(token in current for token in (region, query, tokens[-1] if tokens else query)):
            return current

    raise RuntimeError(f"지역 '{region}' 선택 실패")


async def search_keyword(page: Any, keyword: str, delay_ms: int) -> None:
    search_input = None
    for selector in (
        "input[placeholder*='검색']",
        "input[type='search']",
        "header input",
    ):
        locator = page.locator(selector).first
        if await locator.count() == 0:
            continue
        search_input = locator
        break

    if search_input is not None:
        await search_input.fill("")
        await search_input.fill(keyword)
        await search_input.press("Enter")
        await page.wait_for_timeout(delay_ms)
        return

    # 입력창 탐색 실패 시 URL 파라미터 검색 fallback
    encoded = quote_plus(keyword)
    await page.goto(f"{BASE_URL}?search={encoded}", wait_until="domcontentloaded")
    await page.wait_for_timeout(delay_ms)


def is_selling(text: str) -> bool:
    return not any(token in text for token in SKIP_STATUS_KEYWORDS)


async def collect_items(page: Any, region: str) -> list[Item]:
    items: list[Item] = []
    seen_links_local: set[str] = set()

    # 1) 우선 CSS locator 기반 수집
    anchors = page.locator("a[href*='/articles/'], a[href*='/kr/buy-sell/']")
    count = await anchors.count()

    async def add_item_from_anchor(anchor: Any, href: str | None = None) -> None:
        nonlocal items
        raw_href = href or await anchor.get_attribute("href")
        if not raw_href:
            return
        if "/articles/" not in raw_href and "/kr/buy-sell/" not in raw_href:
            return
        if "/kr/buy-sell/" in raw_href and raw_href.rstrip('/').endswith('/kr/buy-sell'):
            return

        link = f"https://www.daangn.com{raw_href}" if raw_href.startswith("/") else raw_href
        if link in seen_links_local:
            return
        seen_links_local.add(link)

        full_text = (await anchor.inner_text()).strip()
        if not full_text:
            # 앵커 안쪽 텍스트가 없으면 가까운 article 텍스트 사용
            article = anchor.locator("xpath=ancestor::article[1]").first
            if await article.count() > 0:
                full_text = (await article.inner_text()).strip()

        if not full_text:
            return
        if not is_selling(full_text):
            return

        title = re.split(r"\n+", full_text)[0].strip() or "(제목 없음)"
        price_match = re.search(r"([\d,]+\s*원|나눔|무료)", full_text)
        price = price_match.group(1) if price_match else "가격 정보 없음"
        items.append(Item(region=region, title=title, price=price, link=link))

    for i in range(count):
        await add_item_from_anchor(anchors.nth(i))

    if items:
        return items

    # 2) locator로 0건이면 JS로 페이지 전체 링크 fallback 수집
    fallback_links: list[str] = await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href]'))
          .map(a => a.getAttribute('href'))
          .filter(Boolean)
        """
    )

    for href in fallback_links:
        if '/articles/' not in href and '/kr/buy-sell/' not in href:
            continue
        # href 매칭 앵커 중 첫 번째 텍스트 활용
        anchor = page.locator(f"a[href='{href}']").first
        await add_item_from_anchor(anchor, href=href)

    return items


async def run_search(
    keyword: str,
    regions: list[str],
    delay_ms: int,
    headless: bool,
    progress_callback: Callable[[str], None] | None = None,
) -> list[Item]:
    from playwright.async_api import async_playwright

    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(get_playwright_browser_path())

    all_items: list[Item] = []
    seen_links: set[str] = set()

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=headless)
        except Exception as exc:
            message = str(exc)
            if "Executable doesn't exist" in message or "Please run the following command" in message:
                raise RuntimeError(
                    "Playwright Chromium 브라우저가 설치되지 않았습니다. "
                    "GUI에서 '브라우저 설치' 버튼을 눌러 설치하거나, `python -m playwright install chromium`를 실행해 주세요."
                ) from exc
            raise

        for idx, region in enumerate(regions, start=1):
            if progress_callback:
                progress_callback(f"[{idx}/{len(regions)}] {region} 검색 중...")
            context = await browser.new_context(locale="ko-KR")
            page = await context.new_page()
            try:
                await page.goto(BASE_URL, wait_until="domcontentloaded")
                await page.wait_for_timeout(delay_ms)
                selected_label = await change_region(page, region, delay_ms)
                if progress_callback:
                    progress_callback(f"[{idx}/{len(regions)}] 지역 적용 확인: {selected_label}")

                await search_keyword(page, keyword, delay_ms)
                for _ in range(3):
                    await page.mouse.wheel(0, 2200)
                    await page.wait_for_timeout(500)
                items = await collect_items(page, region)
                add_count = 0
                for item in items:
                    if item.link in seen_links:
                        continue
                    seen_links.add(item.link)
                    all_items.append(item)
                    add_count += 1
                if progress_callback:
                    progress_callback(f"[{idx}/{len(regions)}] {region}: 판매중 {add_count}개 추가")
            except Exception as exc:
                if progress_callback:
                    progress_callback(f"[{idx}/{len(regions)}] {region}: 실패 ({exc})")
            finally:
                await context.close()

        await browser.close()

    return all_items


def save_json(path: str, items: list[Item]) -> None:
    Path(path).write_text(json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=2), encoding="utf-8")


def save_csv(path: str, items: list[Item]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["region", "title", "price", "link"])
        writer.writeheader()
        for item in items:
            writer.writerow(asdict(item))


def run_search_sync(
    keyword: str,
    regions: list[str],
    delay_ms: int,
    headless: bool,
    progress_callback: Callable[[str], None] | None = None,
) -> list[Item]:
    return asyncio.run(run_search(keyword, regions, delay_ms, headless, progress_callback))
