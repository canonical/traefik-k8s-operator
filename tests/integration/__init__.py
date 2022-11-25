import sys
import os
from pathlib import Path

charm_root = Path(__file__).parent.parent.parent
sys.path.append(str(charm_root.absolute()))
os.environ['TOX_ENV_DIR'] = str((charm_root / '.tox' / 'integration').absolute())
