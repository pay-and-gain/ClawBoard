"""Opt-in synthetic Tk save/quit/restart regression; isolated explicit persistence only."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if __name__ == '__main__':
    sys.exit(subprocess.run([sys.executable, str(ROOT / 'tools/windows_final_acceptance.py'),
                            '--minutes', '0.02', '--automated'], cwd=ROOT).returncode)
