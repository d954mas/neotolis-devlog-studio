@echo off
REM Trolley devlog server — статика + upload API + /api/project + /api/feedback
REM Записи сохраняются в data/recordings/ через POST /api/save/<name>
cd /d "%~dp0"
echo Trolley Devlog Server
echo =====================
echo.
echo  Studio:    http://localhost:8080/devlog/studio.html
echo  Recorder:  http://localhost:8080/devlog/recorder.html
echo  API:       http://localhost:8080/api/project
echo.
echo Stop: Ctrl+C
echo.
call "%~dp0..\dl.bat" serve trolley.edits.youtube
