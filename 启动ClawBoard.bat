@echo off
chcp 65001 >nul
setlocal
set "PY="
for %%P in (
  "%USERPROFILE%\AppData\Local\Programs\Python\Python313\pythonw.exe"
  "%USERPROFILE%\AppData\Local\Programs\Python\Python312\pythonw.exe"
  "%USERPROFILE%\AppData\Local\Python\bin\pythonw.exe"
  "C:\Python314\pythonw.exe"
  "C:\Python313\pythonw.exe"
) do (
  if exist %%P if not defined PY set "PY=%%~P"
)
if not defined PY (
  for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PY set "PY=%%i"
)
if not defined PY (
  echo Cannot find pythonw.exe
  pause
  exit /b 1
)
start "" "%PY%" "%~dp0ClawBoard.py"
endlocal
