"""Compatibility entry point for the real-data local service smoke check."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('verify_real_site.py')),run_name='__main__')
