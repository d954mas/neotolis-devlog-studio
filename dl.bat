@echo off
setlocal
set "PYTHONPATH=%~dp0common;%~dp0"
python -m devlog %*
