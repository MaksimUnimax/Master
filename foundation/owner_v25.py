"""Apply tested guest calculator and SEO changes after v24."""
import subprocess
from pathlib import Path

def apply(root):
    subprocess.run(["patch","-p1","--fuzz=0","--batch","--forward","--no-backup-if-mismatch","-i",str(Path(__file__).with_name("owner_v25.patch"))],cwd=root,check=True)
