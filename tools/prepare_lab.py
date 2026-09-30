"""Copy the published synthetic fixtures into isolated runtime data."""
import shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
target = ROOT/'data/reliability_lab/fixtures'
target.mkdir(parents=True, exist_ok=True)
for source in (ROOT/'experiments/fixtures').glob('*.wav'):
    shutil.copy2(source,target/source.name)
print('Prepared fixed fixtures in',target)
