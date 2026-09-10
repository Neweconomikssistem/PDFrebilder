@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo PDF OCR - build one-file EXE
echo ==========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo Python not found.
    echo Install Python 3.11-3.13 from python.org and run this again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -m venv .venv
)

call ".venv\Scripts\activate.bat"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if not exist "vendor\tesseract\tesseract.exe" (
    echo.
    echo Tesseract runtime was not found.
    echo.
    echo Install Tesseract OCR for Windows first, then copy its complete
    echo installation folder to:
    echo.
    echo     %CD%\vendor\tesseract
    echo.
    echo It should contain tesseract.exe and tessdata\.
    echo.
    echo Windows installers are referenced in the official Tesseract docs:
    echo https://tesseract-ocr.github.io/tessdoc/Downloads.html
    echo.
    pause
    exit /b 2
)

if not exist "vendor\tesseract\tessdata\rus.traineddata" (
    echo Missing rus.traineddata
    pause
    exit /b 3
)

if not exist "vendor\tesseract\tessdata\eng.traineddata" (
    echo Missing eng.traineddata
    pause
    exit /b 3
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo Building one-file EXE...
pyinstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name PDF_OCR ^
  --add-binary "vendor\tesseract\tesseract.exe;tesseract" ^
  --add-binary "vendor\tesseract\*.dll;tesseract" ^
  --add-data "vendor\tesseract\tessdata;tesseract\tessdata" ^
  main.py

echo.
echo ==========================================
echo DONE
echo EXE: dist\PDF_OCR.exe
echo ==========================================
pause
