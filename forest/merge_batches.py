"""Merge disjoint GEE batches by event attempt time; preserve missing batches."""
import json
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone


def merge(source, target):
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    base = source/'forest-base'
    report = json.loads((base/'forest-status.json').read_text())
    errors = list(report.get('errors', []))
    events = {}
    for folder in [base]+sorted(source.glob('forest-shard-*')):
        for file in folder.glob('*'):
            if file.is_file() and file.name not in ('events.json','forest-status.json'):
                shutil.copy2(file, target/file.name)
        if (folder/'events.json').exists():
            rows = json.loads((folder/'events.json').read_text())
            for key, event in rows.items():
                if key not in events or event.get('last_attempt','') > events[key].get('last_attempt',''):
                    events[key] = event
        if folder != base and (folder/'forest-status.json').exists():
            state = json.loads((folder/'forest-status.json').read_text())
            errors.extend(state.get('errors', []))
            if state.get('status')=='authentication_failed':
                errors.append(folder.name+':authentication')
    for shard in range(8):
        if not (source/f'forest-shard-{shard}'/'forest-status.json').exists():
            errors.append(f'missing_batch:{shard}')
    active = [e for e in events.values() if e.get('active') is not False]
    report.update(generated_at=datetime.now(timezone.utc).isoformat(), events_count=len(active),
                  completed=sum(e.get('status')=='processed' for e in active),
                  partial=sum(e.get('status')=='partial' for e in active),
                  queue_remaining=sum(e.get('status') not in ('processed','partial') for e in active),
                  errors=sorted(set(errors)), status='partial_failure' if errors else 'processed')
    for name, data in [('events.json',events),('forest-status.json',report)]:
        (target/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['status','events_count','completed','partial','queue_remaining','errors']}))


if __name__=='__main__':
    merge(sys.argv[1],sys.argv[2])
