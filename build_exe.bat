@echo off
setlocal

python build_exe.py
if %ERRORLEVEL% NEQ 0 (
  echo EXE 빌드 실패
  exit /b %ERRORLEVEL%
)

echo EXE 빌드 성공: dist\daangn_nationwide_search.exe
endlocal
