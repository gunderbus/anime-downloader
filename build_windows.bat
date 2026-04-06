@echo off
setlocal

cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel% neq 0 (
    echo Python launcher "py" was not found. Install Python for Windows first.
    exit /b 1
)

if not exist ".venv" (
    echo Creating virtual environment...
    py -3 -m venv .venv
)

call ".venv\Scripts\activate.bat"
if %errorlevel% neq 0 (
    echo Could not activate the virtual environment.
    exit /b 1
)

echo Installing dependencies...
python -m pip install --upgrade pip
if %errorlevel% neq 0 exit /b 1

python -m pip install -r requirements.txt pyinstaller
if %errorlevel% neq 0 exit /b 1

echo Building Windows executable...
pyinstaller --noconfirm --clean anime_downloader.spec
if %errorlevel% neq 0 exit /b 1

echo.
echo Build complete.
echo Your Windows app is in dist\AnimeDownloader.exe
echo.
echo ffmpeg.exe must still be installed and available in PATH for video downloads to work.
