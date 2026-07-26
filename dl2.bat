@echo off
setlocal
set "DL2_PY=%~dp0common\dlstudio\.venv\Scripts\python.exe"
if exist "%DL2_PY%" (
  "%DL2_PY%" -X utf8 -m dlstudio %*
) else (
  python -X utf8 -m dlstudio %*
)
