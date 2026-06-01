#!/usr/bin/env python3
"""
Daily scheduler for the Content Studio agent.
Run once with: python scheduler.py
Keeps running in the background and triggers agent.py every day at 08:00.
"""
import schedule
import time
import subprocess
from pathlib import Path
from datetime import datetime

AGENT = Path(__file__).parent / "agent.py"
PYTHON = Path(__file__).parent.parent.parent / "ana-job-app/env/Scripts/python.exe"

def run_agent():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Running agent...")
    result = subprocess.run([str(PYTHON), str(AGENT)], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"Agent error: {result.stderr}")

# Run immediately on start so you don't wait until tomorrow
run_agent()

# Then every day at 08:00
schedule.every().day.at("08:00").do(run_agent)

print("Scheduler running — agent will refresh daily at 08:00. Press Ctrl+C to stop.")
while True:
    schedule.run_pending()
    time.sleep(60)
