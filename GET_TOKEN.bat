@echo off
REM One-time: get the Xero REFRESH TOKEN for the dashboard.
REM Needs Python installed (python.org). Double-click me in this folder.
cd /d "%~dp0"
set /p XERO_CLIENT_ID=Paste Client ID and press Enter: 
set /p XERO_CLIENT_SECRET=Paste Client Secret and press Enter: 
pip install requests
python authorize.py
pause
