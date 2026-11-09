@echo off
rem Inbox entry point for PowerShell / cmd. Claude Code puts bin\ on PATH when the plugin is enabled.
rem python3 on Windows is often the Microsoft Store stub, so try python first, then the py launcher.
python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1 && goto :python
py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1 && goto :py
echo inbox: no runnable Python 3.9+ found (tried python, py -3) 1>&2
exit /b 127
:python
python "%~dp0..\inbox\inbox.py" %*
exit /b %errorlevel%
:py
py -3 "%~dp0..\inbox\inbox.py" %*
exit /b %errorlevel%
