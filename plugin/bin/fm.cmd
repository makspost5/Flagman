@echo off
rem fm for PowerShell and cmd on Windows: runs scripts\fm.py with Python directly.
rem (bin\fm is the bash launcher; PowerShell cannot run an extensionless file.)
setlocal
set "FM_PY=%~dp0..\scripts\fm.py"
where py >nul 2>nul && goto py
where python >nul 2>nul && goto python
echo error: Python 3.9+ not found (tried py -3, python) 1>&2
exit /b 127
:py
py -3 "%FM_PY%" %*
exit /b %ERRORLEVEL%
:python
python "%FM_PY%" %*
exit /b %ERRORLEVEL%
