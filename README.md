# 당근마켓 전국 키워드 검색기

키워드를 1번 입력하면 `regions.txt`에 정의된 모든 지역을 자동으로 순회해서 검색하고,
**판매중 상품만 필터링**해서 한 번에 모아 보여주는 CLI 프로그램입니다.

## 주요 기능

- 지역 자동 변경 + 키워드 자동 검색
- 판매완료/거래완료/예약중 항목 제외
- 중복 상품 링크 제거
- 결과를 JSON/CSV로 저장
- 출력된 링크를 바로 클릭해 상품 페이지로 이동 가능

---

## Windows 사용자용 (PowerShell) 빠른 시작

> 핵심: Windows에서는 `pip ...` 대신 **항상** `python -m pip ...`를 쓰면 됩니다.

### 1) 프로젝트 폴더로 이동

```powershell
cd C:\Users\wavep\Downloads\Carrot-codex-add-nationwide-keyword-search-functionality-hs3529\Carrot-codex-add-nationwide-keyword-search-functionality-hs3529
```

### 2) 가상환경 생성 + 활성화

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> 만약 실행 정책 오류가 나오면 1회만 아래 실행:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 3) pip/의존성 설치

```powershell
python -m ensurepip --upgrade
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4) Playwright 브라우저 설치

```powershell
python -m playwright install chromium
```

### 5) EXE 빌드

```powershell
python build_exe.py
```

성공 시 결과물:

- `dist\nationwide_search.exe`

### 6) EXE 실행

```powershell
.\dist\nationwide_search.exe "아이폰" --csv results.csv --delay-ms 1800
```

`regions.txt`는 EXE와 같은 폴더에 두고 수정하면 지역 목록을 쉽게 변경할 수 있습니다.

---

## 일반 Python 실행 (EXE 없이)

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

## 문제 해결 (질문 주신 로그 기준)

- `pip : ... 인식되지 않습니다`  
  → PowerShell에서 `pip` 명령이 PATH에 없다는 뜻입니다. `python -m pip ...`로 실행하세요.
- `No module named playwright`  
  → Playwright가 설치되지 않은 상태입니다. 먼저 `python -m pip install -r requirements.txt` 실행 후 다시 시도하세요.
- `PyInstaller가 설치되어 있지 않습니다`  
  → 같은 이유로 의존성 설치가 안 된 상태입니다. 위 3단계 명령을 먼저 실행하세요.
- `cd pip install ...` 오류  
  → `cd`는 폴더 이동 명령입니다. 설치 명령은 `cd` 없이 별도로 실행해야 합니다.

## 주의사항

- 사이트 UI/DOM 구조가 바뀌면 선택자 수정이 필요할 수 있습니다.
- 너무 빠르게 요청하면 차단될 수 있으므로 `--delay-ms`를 충분히 늘리세요.
- 서비스 이용약관/robots 정책을 준수해서 사용하세요.
