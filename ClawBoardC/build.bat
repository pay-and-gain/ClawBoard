@echo off
setlocal
REM Build ClawBoardC with MSVC without vcvars (sets INCLUDE/LIB/PATH by hand)
set "VCT=C:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.51.36231"
set "SDK=C:\Program Files (x86)\Windows Kits\10"
set "SDKV=10.0.26100.0"

set "INCLUDE=%VCT%\include;%SDK%\Include\%SDKV%\shared;%SDK%\Include\%SDKV%\ucrt;%SDK%\Include\%SDKV%\um"
set "LIB=%VCT%\lib\x64;%SDK%\Lib\%SDKV%\ucrt\x64;%SDK%\Lib\%SDKV%\um\x64"
set "PATH=%VCT%\bin\Hostx64\x64;%PATH%"

cd /d "%~dp0"
echo [*] Compiling main.c with MSVC 14.51 ...
"%VCT%\bin\Hostx64\x64\cl.exe" /nologo /W3 /O2 /utf-8 /D _CRT_SECURE_NO_WARNINGS /Fe:ClawBoardC.exe main.c user32.lib gdi32.lib shell32.lib comctl32.lib advapi32.lib
echo [*] EXIT=%ERRORLEVEL%
if exist ClawBoardC.exe (
  echo [OK] Output: %~dp0ClawBoardC.exe
)
endlocal
