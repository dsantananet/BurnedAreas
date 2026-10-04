"""QNAP container scheduler: initial refresh, then daily at 04:30 UTC."""
from datetime import datetime, timedelta, timezone
import logging
import subprocess
import time

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
while True:
    now = datetime.now(timezone.utc)
    year = now.year if now.month >= 5 else now.year-1
    result = subprocess.run(['python','-u','/app/update_season.py','--year',str(year),'--output','/outputs'])
    logging.info('Atualização terminou com código %s',result.returncode)
    now = datetime.now(timezone.utc)
    if result.returncode:
        next_run = now+timedelta(hours=1)
    else:
        next_run = now.replace(hour=4,minute=30,second=0,microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
    logging.info('Próxima atualização UTC: %s',next_run.isoformat())
    time.sleep(max(1,(next_run-now).total_seconds()))
