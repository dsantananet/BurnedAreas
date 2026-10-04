"""QNAP container scheduler: initial refresh, then daily at 04:30 UTC."""
from datetime import datetime, timedelta, timezone
import logging
import os
import subprocess
import time
import psycopg

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
while True:
    now = datetime.now(timezone.utc)
    year = now.year if now.month >= 5 else now.year-1
    already_done = False
    try:
        with psycopg.connect(os.environ['DATABASE_URL'],connect_timeout=15) as conn:
            last = conn.execute("SELECT max(finished_at) FROM runs WHERE year=%s AND status='completed'",(year,)).fetchone()[0]
            already_done = bool(last and last.astimezone(timezone.utc).date()==now.date())
    except Exception as exc:
        logging.error('Verificação inicial da base falhou: %s',type(exc).__name__)
    if already_done:
        returncode = 0
        logging.info('Base já atualizada hoje; evitar repetição do processamento.')
    else:
        result = subprocess.run(['python','-u','/app/update_season.py','--year',str(year),'--output','/outputs'])
        returncode = result.returncode
        logging.info('Atualização terminou com código %s',returncode)
    now = datetime.now(timezone.utc)
    if returncode:
        next_run = now+timedelta(hours=1)
    else:
        next_run = now.replace(hour=4,minute=30,second=0,microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
    logging.info('Próxima atualização UTC: %s',next_run.isoformat())
    time.sleep(max(1,(next_run-now).total_seconds()))
