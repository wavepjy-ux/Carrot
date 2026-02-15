# 당근마켓 전국 검색기 (GUI)

터미널 CLI가 아닌 **일반 프로그램 UI**로, 키워드 1회 입력 후 지역 목록 전체를 자동 순회해서
판매중 매물을 한 화면에서 모아 보는 도구입니다.

## 핵심 기능

- 전국(지역 파일 전체) 자동 순회 검색
- 판매중만 필터링 (`판매완료/거래완료/예약중` 명시 항목만 제외)
- 중복 링크 제거 후 통합 목록 표시
- 더블클릭/버튼으로 상품 링크 바로 열기
- JSON/CSV 저장

## 프로그램 실행 (Python)

```bash
python nationwide_search_gui.py
```

## Windows EXE 만들기

### 1) 프로젝트 폴더 이동

```powershell
cd C:\Users\wavep\Downloads\Carrot-codex-add-nationwide-keyword-search-functionality-hs3529\Carrot-codex-add-nationwide-keyword-search-functionality-hs3529
```

### 2) 가상환경

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3) 의존성 설치 (`pip` 대신 `python -m pip` 사용)

```powershell
python -m ensurepip --upgrade
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4) EXE 빌드

```powershell
python build_exe.py
```

생성 파일:

- `dist\daangn_nationwide_search.exe`

## EXE 실행

```powershell
.\dist\daangn_nationwide_search.exe
```

실행 후 UI에서:
1. 키워드 입력
2. 지역 파일(`regions.txt`) 선택/확인
3. (최초 1회) `브라우저 설치` 버튼 클릭
4. `전국 검색 시작` 클릭
5. 결과 목록에서 상품 더블클릭하여 링크 열기

## 지역 파일

`regions.txt`의 모든 줄을 순회하므로, 이 파일을 넓게 구성할수록 더 많은 지역을 한 번에 검색합니다.

```text
서울특별시 강남구
부산광역시 해운대구
제주특별자치도 제주시
```

## 문제 해결

- `pip ... 인식되지 않음` → `python -m pip ...` 사용
- `No module named playwright` → `python -m pip install -r requirements.txt` 먼저 실행
- `PyInstaller가 설치되어 있지 않습니다` → 위와 동일하게 requirements 설치
- `브라우저 설치`를 눌렀는데 GUI가 하나 더 뜸
  - 원인: EXE에서 `sys.executable -m playwright`를 호출하면 자기 자신(GUI EXE)이 다시 실행될 수 있음
  - 해결: 최신 버전으로 업데이트 후 다시 시도 (수정됨)
- `브라우저 설치 실패: Command ['py', ...] returned non-zero exit status 1.`
  - 원인: `py` 기본 파이썬에 playwright 모듈이 없거나 환경이 다른 경우
  - 해결: 최신 버전에서는 자동으로 `python/py` 후보를 순차 시도하고 playwright 설치를 보완합니다.
    그래도 실패하면 PowerShell에서 아래를 직접 실행하세요.
    `python -m pip install playwright`
    `python -m playwright install chromium`
- `지역 ... 선택 실패`가 반복됨
  - 원인: 당근 지역 검색창은 `서울특별시 강남구` 같은 전체 행정명보다 `강남구` 형태를 우선 노출하는 경우가 있음
  - 최신 버전에서는 자동으로 `전체명 → 뒤 2단어 → 마지막 단어` 순으로 재시도하고,
    목록 첫 항목/키보드 선택까지 fallback 처리합니다.
  - 그래도 실패하면 `regions.txt`를 `강남구`, `서초구`, `해운대구`처럼 짧게 바꿔 테스트해 주세요.
- `BrowserType.launch: Executable doesn't exist ...`
  - 원인: Playwright Chromium 브라우저가 설치되지 않았거나 경로가 꼬인 상태
  - 해결 1: GUI에서 `브라우저 설치` 버튼 클릭
  - 해결 2: PowerShell에서 `python -m playwright install chromium`
- 지역이 실제로 바뀌지 않는 것 같음
  - 최신 버전은 지역 선택 후 헤더 라벨을 읽어 적용 여부를 확인하고 로그에 `지역 적용 확인: ...`을 출력합니다.
  - 또한 지역마다 새 브라우저 컨텍스트를 열어 이전 지역 상태가 다음 검색에 섞이지 않게 처리합니다.
- 판매중 매물이 있는데 0건으로 나옴
  - 최신 버전에서는 수집 셀렉터를 `a[href*='/articles/'], a[href*='/kr/buy-sell/']`로 확장하고,
    텍스트가 비어 있으면 상위 `article` 텍스트로 재파싱합니다.
  - 검색 후 무한스크롤 로딩(여러 번 스크롤) + JS 전체 링크 fallback 수집까지 수행합니다.

## 주의사항

- 사이트 DOM/UI 변경 시 선택자 업데이트가 필요할 수 있습니다.
- 너무 빠른 요청은 차단될 수 있어 `대기(ms)`를 늘려 사용하세요.
- 서비스 이용약관/robots 정책 준수 필수.
