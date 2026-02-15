#!/usr/bin/env python3
"""당근마켓 전국 키워드 검색기.

동네를 자동으로 순회하며 키워드 검색 결과를 모아,
"판매중" 상품만 필터링해 링크를 출력/저장합니다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from playwright.async_api import Browser, BrowserContext, Error, Page, async_playwright

BASE_URL = "https://www.daangn.com/kr/buy-sell/"
SKIP_STATUS_KEYWORDS = ("판매완료", "거래완료", "예약중", "예약", "완료")


@dataclass(slots=True)
class Item:
    region: str
    title: str
    price: str
    link: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="모든 지역을 순회하며 당근마켓 판매중 물품을 검색합니다."
    )
    parser.add_argument("keyword", help="검색 키워드")
    parser.add_argument(
        "--regions",
        default="regions.txt",
        help="검색할 지역 목록 텍스트 파일 (기본: regions.txt)",
    )
    parser.add_argument(
        "--out",
        default="results.json",
        help="결과 JSON 파일 경로 (기본: results.json)",
    )
    parser.add_argument(
        "--csv",
        default="",
        help="추가로 CSV 저장할 경로 (선택)",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="브라우저를 눈에 보이게 실행",
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=1200,
        help="지역 전환 후 대기 시간(ms). 차단 회피용으로 크게 설정 가능",
    )
    return parser.parse_args()


def load_regions(path: str) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(
            f"지역 파일을 찾을 수 없습니다: {file_path}. regions.txt를 생성해 주세요."
        )

    regions: list[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            regions.append(value)

    if not regions:
        raise ValueError("지역 파일이 비어 있습니다. 최소 1개 이상 지역을 입력하세요.")
    return regions


async def safe_click(page: Page, selectors: Iterable[str], timeout_ms: int = 4_000) -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        if await locator.count() == 0:
            continue
        try:
            await locator.click(timeout=timeout_ms)
            return True
        except Error:
            continue
    return False


async def change_region(page: Page, region: str, delay_ms: int) -> None:
    # 헤더의 지역 변경 버튼 클릭
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
        raise RuntimeError("지역 선택 모달/드롭다운을 열지 못했습니다.")

    input_candidates = (
        "input[placeholder*='동네']",
        "input[placeholder*='지역']",
        "input[placeholder*='검색']",
        "input[type='search']",
        "input",
    )

    text_input = None
    for selector in input_candidates:
        locator = page.locator(selector).first
        if await locator.count() == 0:
            continue
        text_input = locator
        break

    if text_input is None:
        raise RuntimeError("지역 검색 입력창을 찾지 못했습니다.")

    await text_input.fill("")
    await text_input.fill(region)
    await page.wait_for_timeout(max(delay_ms, 800))

    clicked_region = await safe_click(
        page,
        selectors=(
            f"[role='option']:has-text('{region}')",
            f"li:has-text('{region}')",
            f"button:has-text('{region}')",
            f"a:has-text('{region}')",
        ),
    )
    if not clicked_region:
        raise RuntimeError(f"지역 '{region}' 선택에 실패했습니다.")

    await page.wait_for_timeout(delay_ms)


async def search_keyword(page: Page, keyword: str, delay_ms: int) -> None:
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


async def collect_items(page: Page, region: str) -> list[Item]:
    # 검색 카드 후보 셀렉터들 (페이지 변경에 대비)
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

        title_match = re.split(r"\n+", full_text)
        title = title_match[0].strip() if title_match else "(제목 없음)"
        price_match = re.search(r"([\d,]+\s*원|나눔|무료)", full_text)
        price = price_match.group(1) if price_match else "가격 정보 없음"

        items.append(Item(region=region, title=title, price=price, link=link))

    return items


async def run(keyword: str, regions: list[str], headful: bool, delay_ms: int) -> list[Item]:
    all_items: list[Item] = []
    seen_links: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headful)
        context = await browser.new_context(locale="ko-KR")
        page = await context.new_page()

        for idx, region in enumerate(regions, start=1):
            print(f"[{idx}/{len(regions)}] 지역 검색 중: {region}")
            try:
                await page.goto(BASE_URL, wait_until="domcontentloaded")
                await page.wait_for_timeout(delay_ms)

                await change_region(page, region, delay_ms)
                await search_keyword(page, keyword, delay_ms)
                items = await collect_items(page, region)

                new_count = 0
                for item in items:
                    if item.link in seen_links:
                        continue
                    seen_links.add(item.link)
                    all_items.append(item)
                    new_count += 1

                print(f"  -> 판매중 {new_count}개 추가")
            except Exception as exc:  # noqa: BLE001
                print(f"  !! 실패: {region} ({exc})")
                continue

        await context.close()
        await browser.close()

    return all_items


def save_json(path: str, items: list[Item]) -> None:
    Path(path).write_text(
        json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_csv(path: str, items: list[Item]) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["region", "title", "price", "link"])
        writer.writeheader()
        for item in items:
            writer.writerow(asdict(item))


def print_items(items: list[Item]) -> None:
    if not items:
        print("판매중 결과가 없습니다.")
        return

    print("\n=== 판매중 상품 목록 ===")
    for idx, item in enumerate(items, start=1):
        print(f"{idx:03d}. [{item.region}] {item.title} | {item.price}")
        print(f"     {item.link}")


def main() -> None:
    args = parse_args()
    regions = load_regions(args.regions)

    items = asyncio.run(
        run(
            keyword=args.keyword,
            regions=regions,
            headful=args.headful,
            delay_ms=args.delay_ms,
        )
    )

    save_json(args.out, items)
    if args.csv:
        save_csv(args.csv, items)

    print_items(items)
    print(f"\n저장 완료: {args.out}")
    if args.csv:
        print(f"CSV 저장 완료: {args.csv}")


if __name__ == "__main__":
    main()
