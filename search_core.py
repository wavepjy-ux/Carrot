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

BASE_URL = "https://www.daangn.com/kr/buy-sell/"
SKIP_STATUS_KEYWORDS = ("판매완료", "거래완료", "예약중", "예약", "완료")


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


async def change_region(page: Any, region: str, delay_ms: int) -> None:
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

    # 중복 제거
    seen: set[str] = set()
    query_candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    for query in query_candidates:
        await text_input.fill("")
        await text_input.fill(query)
        await page.wait_for_timeout(max(delay_ms, 900))

        # 1) 원본 지역명 정확 매칭
        clicked_region = await safe_click(
            page,
            selectors=(
                f"[role='option']:has-text('{region}')",
                f"li:has-text('{region}')",
                f"button:has-text('{region}')",
                f"a:has-text('{region}')",
            ),
            timeout_ms=1_800,
        )
        if clicked_region:
            await page.wait_for_timeout(delay_ms)
            return

        # 2) 현재 검색어로 매칭
        clicked_query = await safe_click(
            page,
            selectors=(
                f"[role='option']:has-text('{query}')",
                f"li:has-text('{query}')",
                f"button:has-text('{query}')",
                f"a:has-text('{query}')",
            ),
            timeout_ms=1_800,
        )
        if clicked_query:
            await page.wait_for_timeout(delay_ms)
            return

        # 3) 검색 결과의 첫 번째 후보 선택
        first_option = None
        for selector in (
            "[role='dialog'] [role='option']",
            "[role='listbox'] [role='option']",
            "[role='dialog'] li",
            "[aria-modal='true'] li",
        ):
            locator = page.locator(selector).first
            if await locator.count() > 0:
                first_option = locator
                break

        if first_option is not None:
            try:
                await first_option.click(timeout=1_800)
                await page.wait_for_timeout(delay_ms)
                return
            except Exception:
                pass

        # 4) 키보드 선택 fallback
        try:
            await text_input.press("ArrowDown")
            await text_input.press("Enter")
            await page.wait_for_timeout(delay_ms)
            return
        except Exception:
            continue

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

    if search_input is None:
        raise RuntimeError("검색 입력창을 찾지 못했습니다.")

    await search_input.fill("")
    await search_input.fill(keyword)
    await search_input.press("Enter")
    await page.wait_for_timeout(delay_ms)


def is_selling(text: str) -> bool:
    return not any(token in text for token in SKIP_STATUS_KEYWORDS)


async def collect_items(page: Any, region: str) -> list[Item]:
    card_selectors = (
        "article",
        "li article",
        "a[data-gtm*='search']",
        "main a[href*='/articles/']",
    )

    cards = []
    for selector in card_selectors:
        locator = page.locator(selector)
        count = await locator.count()
        if count > 0:
            cards = [locator.nth(i) for i in range(count)]
            break

    items: list[Item] = []
    for card in cards:
        full_text = (await card.inner_text()).strip()
        if not full_text or not is_selling(full_text):
            continue

        link = await card.locator("a").first.get_attribute("href") if await card.locator("a").count() else None
        if not link:
            link = await card.get_attribute("href")
        if not link:
            continue
        if link.startswith("/"):
            link = f"https://www.daangn.com{link}"

        title = re.split(r"\n+", full_text)[0].strip()
        price_match = re.search(r"([\d,]+\s*원|나눔|무료)", full_text)
        price = price_match.group(1) if price_match else "가격 정보 없음"
        items.append(Item(region=region, title=title, price=price, link=link))

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
        context = await browser.new_context(locale="ko-KR")
        page = await context.new_page()

        for idx, region in enumerate(regions, start=1):
            if progress_callback:
                progress_callback(f"[{idx}/{len(regions)}] {region} 검색 중...")
            try:
                await page.goto(BASE_URL, wait_until="domcontentloaded")
                await page.wait_for_timeout(delay_ms)
                await change_region(page, region, delay_ms)
                await search_keyword(page, keyword, delay_ms)
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
