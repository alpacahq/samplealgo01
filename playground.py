import os
import subprocess

pypath = os.path.abspath(os.path.dirname(__file__))
subprocess.run(f"PYTHONPATH={pypath} jupyter notebook --notebook-dir=notes", shell=True, check=True)