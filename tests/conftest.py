"""The scripts import each other by module name, as each puts scripts/ on its
own path. pytest loads this file first, so every test can do the same in any
order."""

import os
import sys

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
