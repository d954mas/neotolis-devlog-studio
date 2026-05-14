@echo off
REM Devlog CLI wrapper for Windows — sets PYTHONPATH then runs `python -m devlog`.
REM Usage:  dl render trolley.edits.youtube
REM         dl compose trolley.edits.youtube a0-1
setlocal
set PYTHONPATH=%~dp0common;%~dp0
python -m devlog %*
