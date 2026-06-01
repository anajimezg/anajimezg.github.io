@echo off
cd C:\Users\frase\git\ana
call C:\Users\frase\ana-job-app\env\Scripts\activate.bat
start "Content Studio" python server.py
start "Agent Scheduler" python scheduler.py
timeout /t 2
start http://localhost:5001
