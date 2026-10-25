#!/bin/bash
set -euo pipefail
branch=$1
folder=$2
python - "$folder/forest-status.json" <<'PY'
import json,os,sys
from pathlib import Path
p=Path(sys.argv[1]);data=json.loads(p.read_text());data['source_run_id']=os.environ['GITHUB_RUN_ID'];p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
PY
cd "$folder"
git init -b output-snapshot
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git add .
git commit -m "GEE products $GITHUB_RUN_ID $branch"
cd ..
git fetch "./$folder" output-snapshot
git push --force origin "FETCH_HEAD:refs/heads/$branch"
