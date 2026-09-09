"""Local runbook checks; uses temporary fixtures, never connects to ECS."""
from pathlib import Path
import hashlib,re,subprocess,tempfile,sqlite3
import os,shutil,sys

# The runbook tests Linux shell commands; run them together inside WSL on Windows.
if os.name == 'nt':
 if not shutil.which('wsl.exe'):
  raise SystemExit('These checks require WSL with Python 3, Bash and sha256sum.')
 mapped=subprocess.run(['wsl.exe','--exec','wslpath','-u',str(Path(__file__).resolve())],capture_output=True,text=True,encoding='utf-8')
 if mapped.returncode:
  raise SystemExit('Cannot access WSL. Open your WSL distribution and run: python3 check_drill_runbook.py')
 raise SystemExit(subprocess.call(['wsl.exe','--exec','python3',mapped.stdout.strip()]))

missing=[name for name in ('bash','sha256sum','python3') if not shutil.which(name)]
if missing:
 raise SystemExit('Missing required tools: '+', '.join(missing))

s=Path(__file__).with_name('PHASE2_BACKUP_RESTORE_DRILL.md').read_text(encoding='utf-8')
blocks=re.findall(r'~~~bash\n(.*?)~~~',s,re.S)
for b in blocks:
 subprocess.run(['bash','-n'],input=b,text=True,encoding='utf-8',check=True)
print('Bash syntax:',len(blocks),'blocks passed')
block=next(b for b in blocks if "PY_CHECK" in b)
check=block.split("python3 - <<'PY_CHECK'\n")[1].split('\nPY_CHECK')[0]
with tempfile.TemporaryDirectory() as d:
 root=Path(d); (root/'data').mkdir(); (root/'data/db.sqlite3').write_bytes(b'test-data');(root/'image.txt').write_text('image')
 (root/'manifest.sha256').write_text(''.join(hashlib.sha256((root/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in ['data/db.sqlite3','image.txt']))
 def run(expected):
  p=subprocess.run([sys.executable,'-c',check],cwd=d,text=True,encoding='utf-8',capture_output=True)
  assert (p.returncode==0)==expected,(p.stdout,p.stderr)
 run(False) # intact package is not a corruption-test PASS
 with (root/'data/db.sqlite3').open('ab') as f:f.write(b'corrupt')
 run(True)
 (root/'image.txt').unlink();run(False)
 (root/'manifest.sha256').unlink();run(False)
 print('Corruption validator: intact/corrupt/missing-file/missing-manifest passed')
 # Whole block must fail before mutation for wrong IDs/missing packages/existing bad directory.
 testblock=block.replace('/root/data/backups/vaultwarden-lab',d)
 for ident in ['REPLACE_WITH_EXACT_DRILL_ID','../escape','lab-20260101T000000Z']:
  p=subprocess.run(['bash','-c',testblock],input=ident+'\n',text=True,encoding='utf-8',capture_output=True)
  assert p.returncode!=0 and 'PASS:' not in p.stdout
 print('ID and missing-backup gates passed')
 valid=root/'valid.sqlite3';sqlite3.connect(valid).close()
 code=re.search(r"python3 -c '(import sqlite3,sys;.*?)'",s).group(1)
 assert subprocess.run([sys.executable,'-c',code,str(valid)],capture_output=True).returncode==0
 invalid=root/'invalid.sqlite3';invalid.write_bytes(b'not a database'*100)
 assert subprocess.run([sys.executable,'-c',code,str(invalid)],capture_output=True).returncode!=0
 print('SQLite valid/invalid exit status passed')

# Phase 3 reuses the cold-backup procedure; check its shell and .env-only gate.
phase3=Path(__file__).with_name('PHASE3_UPGRADE_COMPATIBILITY_DRILL.md').read_text(encoding='utf-8')
phase3_blocks=re.findall(r'~~~bash\n(.*?)~~~',phase3,re.S)
for b in phase3_blocks:
 subprocess.run(['bash','-n'],input=b,text=True,encoding='utf-8',check=True)
print('Phase 3 Bash syntax:',len(phase3_blocks),'blocks passed')
env_check=phase3.split("<<'PY_ENV'\n",1)[1].split('\nPY_ENV',1)[0]
with tempfile.TemporaryDirectory() as d:
 before=Path(d)/'before.env';after=Path(d)/'after.env'
 baseline='VW_LAB_IMAGE=old\nVW_LAB_DOMAIN=https://lab.example.test\n'
 before.write_text(baseline,encoding='utf-8')
 cases=[
  ('VW_LAB_IMAGE=new\nVW_LAB_DOMAIN=https://lab.example.test\n',True),
  ('VW_LAB_IMAGE=new\nVW_LAB_DOMAIN=https://other.example.test\n',False),
  ('VW_LAB_DOMAIN=https://lab.example.test\n',False),
  ('VW_LAB_IMAGE=new\nVW_LAB_IMAGE=extra\nVW_LAB_DOMAIN=https://lab.example.test\n',False),
  ('VW_LAB_IMAGE=new\nVW_LAB_DOMAIN=https://lab.example.test\nEXTRA=value\n',False),
 ]
 for value,expected in cases:
  after.write_text(value,encoding='utf-8')
  p=subprocess.run([sys.executable,'-c',env_check,str(before),str(after)],capture_output=True,text=True,encoding='utf-8')
  assert (p.returncode==0)==expected,(p.stdout,p.stderr)
 print('Phase 3 .env gate: image-only/domain-change/missing-image/duplicate-image/extra-setting passed')
