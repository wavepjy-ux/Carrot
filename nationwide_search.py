#!/usr/bin/env python3
"""당근마켓 전국 키워드 검색기 (CLI)."""

from __future__ import annotations

import argparse

from search_core import load_regions, run_search_sync, save_csv, save_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="전국 지역을 순회해 당근마켓 판매중 상품을 검색합니다.")
    parser.add_argument("keyword", help="검색 키워드")
    parser.add_argument("--regions", default="regions.txt", help="지역 목록 파일")
    parser.add_argument("--out", default="results.json", help="JSON 결과 파일")
    parser.add_argument("--csv", default="", help="CSV 결과 파일")
    parser.add_argument("--delay-ms", type=int, default=1200, help="지역 전환/검색 대기 시간(ms)")
    parser.add_argument("--headful", action="store_true", help="브라우저 UI 표시")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    regions = load_regions(args.regions)

    items = run_search_sync(
        keyword=args.keyword,
        regions=regions,
        delay_ms=args.delay_ms,
        headless=not args.headful,
        progress_callback=print,
    )

    save_json(args.out, items)
    if args.csv:
        save_csv(args.csv, items)

    print("\n=== 판매중 상품 목록 ===")
    if not items:
        print("판매중 결과가 없습니다.")
    for idx, item in enumerate(items, start=1):
        print(f"{idx:03d}. [{item.region}] {item.title} | {item.price}\n     {item.link}")

    print(f"\n저장 완료: {args.out}")
    if args.csv:
        print(f"CSV 저장 완료: {args.csv}")


if __name__ == "__main__":
    main()
