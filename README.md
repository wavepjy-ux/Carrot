# 당근마켓 전국 키워드 검색기

키워드를 1번 입력하면 `regions.txt`에 정의된 모든 지역을 자동으로 순회해서 검색하고,
**판매중 상품만 필터링**해서 한 번에 모아 보여주는 CLI 프로그램입니다.

## 주요 기능

- 지역 자동 변경 + 키워드 자동 검색
- 판매완료/거래완료/예약중 항목 제외
- 중복 상품 링크 제거
- 결과를 JSON/CSV로 저장
- 출력된 링크를 바로 클릭해 상품 페이지로 이동 가능

## 설치

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## 사용법

```bash
python nationwide_search.py "아이폰"
```

옵션:

- `--regions regions.txt` : 지역 목록 파일
- `--out results.json` : JSON 결과 파일
- `--csv results.csv` : CSV 결과 파일
- `--headful` : 브라우저 창을 띄워서 동작 확인
- `--delay-ms 1500` : 요청 사이 대기 시간

예시:

```bash
python nationwide_search.py "자전거" --csv results.csv --headful --delay-ms 1800
```

## 지역 파일 형식

`regions.txt`에서 줄 단위로 지역을 입력합니다.

```text
서울특별시 강남구
경기도 성남시 분당구
부산광역시 해운대구
```

## 주의사항

- 사이트 UI/DOM 구조가 바뀌면 선택자 수정이 필요할 수 있습니다.
- 너무 빠르게 요청하면 차단될 수 있으므로 `--delay-ms`를 충분히 늘리세요.
- 서비스 이용약관/robots 정책을 준수해서 사용하세요.
