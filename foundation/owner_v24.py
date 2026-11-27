"""Apply guest payment and restore-menu delta after v23."""
import subprocess
from pathlib import Path

def apply(root):
    subprocess.run(["patch","-p1","--fuzz=0","--batch","--forward","--no-backup-if-mismatch","-i",str(Path(__file__).with_name("owner_v24.patch"))],cwd=root,check=True)
