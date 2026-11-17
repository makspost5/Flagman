@echo off
rem fm for PowerShell and cmd on Windows: runs scripts\fm.py with Python 3.9+.
rem (bin\fm is the bash launcher; PowerShell cannot run an extensionless file.)
rem Each candidate must pass the version check: on a clean Windows `python` can be the
rem Microsoft Store alias, which fails it instead of running fm.
setlocal
set "FM_PY=%~dp0..\scripts\fm.py"
py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul && goto py
python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul && goto python
>&2 echo error: Python 3.9+ not found (tried py -3, python)
>&2 echo Install it from https://www.python.org/downloads/ and turn on "Add python.exe to PATH".
exit /b 127
:py
py -3 "%FM_PY%" %*
exit /b %ERRORLEVEL%
:python
python "%FM_PY%" %*
exit /b %ERRORLEVEL%
