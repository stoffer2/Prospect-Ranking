@echo off
echo ========================================
echo  Rankle Buzz Scraper - Setup Script
echo ========================================
echo.

echo Installing Python dependencies...
python -m pip install -r requirements.txt

echo.
echo Setup complete! 
echo.
echo Next steps:
echo 1. Go to https://www.reddit.com/prefs/apps
echo 2. Create a "script" type app 
echo 3. Edit the .env file with your credentials
echo 4. Run: python reddit-buzz-scraper.py
echo.
pause