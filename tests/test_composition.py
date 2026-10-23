"""Construct the real composition root with native/UI ports replaced in a child.

This is an import/wiring contract, not a Windows ABI or rendered-desktop test.
The child redirects paths before importing the application and enables NO_SAVE.
"""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CompositionTests(unittest.TestCase):
    def test_real_application_can_wire_and_close_with_isolated_ports(self):
        script = r'''
import ctypes, pathlib, sys, tempfile, types
from unittest.mock import patch
root=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
from test_windows_boundaries import NativeLibrary
libraries={}
def library(name,**kwargs):return libraries.setdefault(name,NativeLibrary())
ctypes.WinDLL=library
ctypes.WINFUNCTYPE=ctypes.CFUNCTYPE
ctypes.get_last_error=lambda:0
ctypes.windll=types.SimpleNamespace(**{n:library(n) for n in ('user32','gdi32','dwmapi','shcore')})
sys.modules['winreg']=types.SimpleNamespace(HKEY_CURRENT_USER=0,KEY_SET_VALUE=2,REG_SZ=1)
with tempfile.TemporaryDirectory(prefix='clawboard-composition-') as directory:
 import clawboard.config as config
 config.BASE_DIR=directory
 config.DATA_FILE=str(pathlib.Path(directory)/'data.json')
 config.CRASH_LOG=str(pathlib.Path(directory)/'crash.log')
 from clawboard import runtime
 runtime.NO_SAVE=True
 import ClawBoard as C
 class Variable:
  def __init__(self,*args,**kwargs):self.value=''
  def get(self):return self.value
  def set(self,value):self.value=value
 class Root:
  def __init__(self):self.jobs={};self.counter=0
  def winfo_id(self):return 42
  def after(self,delay,callback):
   self.counter+=1;token=str(self.counter);self.jobs[token]=(delay,callback);return token
  def after_cancel(self,token):self.jobs.pop(token,None)
  def __getattr__(self,name):return lambda *args,**kwargs:None
 shell=Root()
 cls=C.ClawBoard
 methods=('build_ui','apply_geometry','apply_effects','apply_ui_scale_init',
          'setup_update_check','render','poll_bg')
 with patch('tkinter.StringVar',Variable):
  with __import__('contextlib').ExitStack() as stack:
   for name in methods:stack.enter_context(patch.object(cls,name,lambda self:None))
   stack.enter_context(patch.object(cls,'setup_system',lambda self:setattr(self,'hw',types.SimpleNamespace(clipboard_listener=False))))
   app=cls(shell)
   assert app.application.data is app.data
   assert app.application.history.data is app.data
   assert app.bridge.application is app.application
   assert app._projection.project(app.data['clip'],'clip',app.st)==[]
   app.bridge.close()
   assert app.application.closed
 assert list(pathlib.Path(directory).iterdir())==[], 'NO_SAVE composition wrote user-like data'
 print('composition and NO_SAVE wiring passed')
'''
        result = subprocess.run([sys.executable, '-c', script, str(ROOT)],
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('composition and NO_SAVE wiring passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
