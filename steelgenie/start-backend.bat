@echo off
title CalSteel Backend (port 8000)
cd /d "%~dp0backend"
py -3.14 run.py || python run.py
pause
