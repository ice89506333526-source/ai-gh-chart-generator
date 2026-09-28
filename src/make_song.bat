@echo off
setlocal
REM ============================================================
REM  AI GH Chart Generator - MP3 -> Guitar Hero III package
REM
REM  Double-click: interactive mode. Drag your MP3 into the
REM  window and press Enter. Or run with arguments:
REM    make_song.bat "D:\music\song.mp3" mysong "Name" "Artist"
REM ============================================================
set PY=D:\ai-gh\ai-gh-stage3\.venv\Scripts\python.exe
set SCRIPT=D:\ai-gh\pipeline\make_song.py

if not "%~1"=="" goto args_mode

:interactive
echo ============================================================
echo   AI GH Chart Generator: MP3 -^> Guitar Hero III package
echo ============================================================
echo.
echo Drag your MP3 file into this window, then press Enter.
echo Then type a song id (latin letters/digits), e.g.:  mysong
echo Example line:   "D:\music\song.mp3" mysong
echo.
set "LINE="
set /p LINE=MP3 path and song id: 
if not defined LINE goto end_empty
echo.
echo Running the pipeline... this takes about a minute.
echo.
set "LASTID=%TEMP%\aigh_last_id.txt"
if exist "%LASTID%" del "%LASTID%" >nul 2>&1
"%PY%" "%SCRIPT%" %LINE% --last-id-file "%LASTID%"
echo.
echo ==============================
set "SID="
if exist "%LASTID%" for /f "usebackq tokens=2 delims==" %%I in ("%LASTID%") do set "SID=%%I"
if not defined SID goto end_fail
if exist "D:\ai-gh\pipeline\out\%SID%\notes.chart" goto success
:end_fail
echo Pipeline did not finish - read the messages above.
goto end

:success
echo DONE. Import folder:
echo   D:\ai-gh\pipeline\out\%SID%
echo Files: notes.chart + song.wav  -^> import in GHTCP as song id "%SID%"
echo.
echo Check by ear first:
echo   D:\ai-gh\pipeline\work\%SID%\grid_preview.wav
echo   D:\ai-gh\pipeline\work\%SID%\notes_preview.wav
start "" "D:\ai-gh\pipeline\out\%SID%"
goto end

:end_empty
echo Nothing entered.
goto end

:args_mode
"%PY%" "%SCRIPT%" "%~1" --id "%~2" %~3 %~4
echo.
if exist "D:\ai-gh\pipeline\out\%~2\notes.chart" (
  echo DONE. Import folder: D:\ai-gh\pipeline\out\%~2
) else (
  echo Pipeline did not finish - read the messages above.
)
pause
exit /b 0

:end
echo.
pause
