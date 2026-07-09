@echo off
title CalSteel Backend (port 8000)
cd /d "%~dp0backend"
".venv\Scripts\python.exe" run.py
pause
