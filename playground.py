import os

pypath = os.path.abspath(os.path.dirname(__file__))
env = os.environ
env['PYTHONPATH'] = pypath
os.execvpe('jupyter', ['jupyter', 'notebook', '--notebook-dir=notes'], env)