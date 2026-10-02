import time
T0=time.time()
def mark(s): print('[%.2f] %s' % (time.time()-T0, s), flush=True)
mark('start')
import ClawBoard as C
mark('import ClawBoard ok')
import tkinter as tk
mark('import tkinter ok')
C.NO_SAVE = True
r = tk.Tk()
mark('Tk ok')
r.geometry('349x424+80+80')
app = C.ClawBoard(r)
mark('app ok')
r.update()
mark('update ok')
import os; os._exit(0)
