"""Shared paper-style controls retain native Tk focus and activation behavior."""
import tkinter as tk

from clawboard.config import FONT_SM, scaled
from clawboard.theme import T
from clawboard.ui_icons import get_icon


class UIActionButton(tk.Button):
    """A real Tk Button, optionally a fixed logical-pixel icon target.

    Keeping `text` even when the image is shown preserves action labels for
    accessibility inspection and existing command dictionaries. The Return and
    Space bindings stop propagation to the panel's paste-selected shortcut.
    """
    def __init__(self, master, text='', icon=None, command=None, tooltip=None,
                 size=24, icon_size=16, **kwargs):
        self._icon_name = icon
        self._icon_pixels = scaled(icon_size)
        self._hovered = self._focused = False
        self._ready = False
        self._tip = None
        self._normal_bg = kwargs.pop('bg', kwargs.pop('background', master.cget('bg')))
        self._normal_fg = kwargs.pop('fg', kwargs.pop('foreground', T['fg2']))
        self._hover_bg = kwargs.pop('activebackground', T['card_h'])
        self._hover_fg = kwargs.pop('activeforeground', T['fg'])
        self._image = (get_icon(master, icon, self._icon_pixels, self._normal_fg)
                       if icon else tk.PhotoImage(master=master, width=1, height=1))
        options = dict(text=text, image=self._image, compound='none' if icon else 'center',
                       command=command, bg=self._normal_bg, fg=self._normal_fg,
                       activebackground=self._hover_bg, activeforeground=self._hover_fg,
                       relief='flat', overrelief='flat', bd=0, takefocus=True, font=FONT_SM,
                       highlightthickness=1, highlightbackground=self._normal_bg,
                       highlightcolor=T.get('focus', T['acc']), cursor='hand2',
                       disabledforeground=T.get('disabled', T['fg2']))
        if size is None:
            options.update(width=0, height=0, padx=scaled(8), pady=scaled(5))
        else:
            # With an image attached, Tk width/height are pixels, not characters.
            options.update(width=max(1, scaled(size)-2), height=max(1, scaled(size)-2), padx=0, pady=0)
        options.update(kwargs)
        super().__init__(master, **options)
        self._ready = True
        self.bind('<Enter>', self._enter)
        self.bind('<Leave>', self._leave)
        self.bind('<FocusIn>', lambda e: self._focus(True))
        self.bind('<FocusOut>', lambda e: self._focus(False))
        self.bind('<ButtonPress-1>', lambda e: self.focus_set(), add='+')
        self.bind('<Return>', self._activate)
        self.bind('<KP_Enter>', self._activate)
        self.bind('<KeyPress-space>', self._activate)
        self.bind('<KeyRelease-space>', lambda e: 'break')
        if tooltip:
            # Lazy import avoids a module cycle when ordinary dialogs also use
            # UIActionButton. Tooltip geometry never affects the button's size.
            from clawboard.widgets import Tip
            self._tip = Tip(self.winfo_toplevel())
            self._tooltip_text = tooltip
            self.bind('<Destroy>', self._destroyed, add='+')

    def configure(self, cnf=None, **kwargs):
        if isinstance(cnf, dict):
            kwargs = {**cnf, **kwargs}
            cnf = None
        if self._ready:
            if 'fg' in kwargs or 'foreground' in kwargs:
                self._normal_fg = kwargs.get('fg', kwargs.get('foreground'))
            if 'bg' in kwargs or 'background' in kwargs:
                self._normal_bg = kwargs.get('bg', kwargs.get('background'))
        result = super().configure(cnf, **kwargs)
        if self._ready and any(key in kwargs for key in ('fg', 'foreground', 'bg', 'background', 'state')):
            self._paint()
        return result

    config = configure

    def _activate(self, _event=None):
        self.invoke()
        return 'break'

    def _paint(self):
        if str(self.cget('state')) == 'disabled':
            fg, bg = T.get('disabled', T['fg2']), self._normal_bg
        else:
            fg = T['acc'] if self._focused else self._hover_fg if self._hovered else self._normal_fg
            bg = self._hover_bg if self._hovered else self._normal_bg
        super().configure(bg=bg, fg=fg)
        if self._icon_name:
            self._image = get_icon(self, self._icon_name, self._icon_pixels, fg)
            super().configure(image=self._image)

    def _enter(self, _event=None):
        self._hovered = True
        self._paint()
        if self._tip:
            self._tip.show(self._tooltip_text, self.winfo_rootx(), self.winfo_rooty()+self.winfo_height())

    def _leave(self, _event=None):
        self._hovered = False
        self._paint()
        if self._tip:
            self._tip.hide()

    def _focus(self, focused):
        self._focused = focused
        self._paint()

    def _destroyed(self, event):
        if event.widget is self and self._tip:
            self._tip.hide()
