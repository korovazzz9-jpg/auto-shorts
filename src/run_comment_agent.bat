@echo off
REM Обёртка для Планировщика заданий Windows — comment_agent.py теперь работает локально,
REM не в GitHub Actions (см. README, "Ответы на комментарии зрителей").
REM cd /d ЯВНО задаём — иначе load_dotenv() ищет .env от рабочей директории Планировщика
REM (часто System32), а не от репозитория, и скрипт падает на старте без переменных окружения.
cd /d "%~dp0"
"C:\Users\Ivan\AppData\Local\Programs\Python\Python312\python.exe" comment_agent.py >> "..\comment_agent.log" 2>&1
