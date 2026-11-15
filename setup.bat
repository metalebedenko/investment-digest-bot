@echo off
cd /d "%~dp0"
chcp 65001 > nul
echo ==========================================
echo  Investment Digest Bot — Настройка
echo ==========================================
echo.

REM Проверяем Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ОШИБКА: Python не найден. Установи Python 3.12 с python.org
    pause
    exit /b 1
)

REM Создаём venv если не существует
if not exist "venv\" (
    echo [1/3] Создаём виртуальное окружение...
    python -m venv venv
    if errorlevel 1 (
        echo ОШИБКА: не удалось создать venv
        pause
        exit /b 1
    )
    echo       OK
) else (
    echo [1/3] Виртуальное окружение уже существует, пропускаем
)

REM Устанавливаем зависимости
echo [2/3] Устанавливаем зависимости...
call venv\Scripts\pip install --only-binary=:all: --require-hashes -r requirements.lock -q
if errorlevel 1 (
    echo ОШИБКА: не удалось установить зависимости
    pause
    exit /b 1
)
echo       OK

REM Создаём .env если не существует
if not exist ".env" (
    echo [3/3] Создаём .env из шаблона...
    copy .env.example .env >nul
    echo       OK — заполни .env своими токенами!
) else (
    echo [3/3] .env уже существует, пропускаем
)

echo.
echo ==========================================
echo  Готово! Дальнейшие шаги:
echo  1. Для демо ключи и настройки не нужны
echo  2. Запусти: venv\Scripts\python run_bot.py --demo
echo  3. Для панели и локального таймера: venv\Scripts\python admin_panel.py
echo ==========================================
echo.
pause
