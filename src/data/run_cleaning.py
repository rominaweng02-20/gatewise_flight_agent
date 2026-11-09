"""Run the cleaning scripts in dependency-independent sequence."""
import subprocess
import sys

MODULES = [
    "src.data.clean_security",
    "src.data.clean_flights",
    "src.data.clean_noaa",
    "src.data.clean_faa",
]

for module in MODULES:
    print(f"\n{'=' * 20} {module} {'=' * 20}", flush=True)
    subprocess.run([sys.executable, "-m", module], check=True)
