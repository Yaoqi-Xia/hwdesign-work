"""Build the two independent deliverables, preserving failures in their logs."""
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parent
failed=[]
for name,target in [("inclass","csim"),("takehome","cosim")]:
    p=subprocess.run([sys.executable,"build.py","--through",target],cwd=root/name)
    if p.returncode:
        failed.append(name)
print("Build failures:",failed,flush=True)
sys.exit(bool(failed))
