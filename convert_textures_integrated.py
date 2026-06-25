"""
convert_textures_integrated.py

Integration launcher: runs the existing DDS ↔ PNG Texture Converter with the
DirectXTex tool panels (Texconv, Texassemble, Texdiag) wired in as extra Notebook
tabs.

Import, don't copy: imports the main app's `App` and the panels from
directx_texture_tools.py. The main file stays the single source of truth; adding
more options later means editing the panels, not this launcher.

Layout: the main app hosts its Notebook and a shared bottom pane (action bar +
log) in a vertical PanedWindow. Each DirectXTex panel builds CONTROLS-ONLY into
the Notebook (framed like the built-in tabs) and its own action bar + log into a
sibling frame in that bottom pane. Selecting a tab shows that tab's bottom strip,
so every tab looks and resizes identically.

Run this file for the combined app. The DirectXTex suite can also run on its own:
    python directx_texture_tools.py
"""

from __future__ import annotations

import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tkinter import ttk                                # noqa: E402
import convert_textures_gui                            # noqa: E402
import directx_texture_tools                           # noqa: E402
from convert_textures_gui import App, ToolTip          # noqa: E402
from nvtt_tools import (                               # noqa: E402
    NvttExportPanel, NvddsinfoPanel, NvimgdiffPanel,
)
from directx_texture_tools import (                    # noqa: E402
    TexconvPanel, TexassemblePanel, TexdiagPanel,
)

# Make the converter and the whole suite share ONE concurrency budget, so running
# several tabs at once can't oversubscribe the GPU/CPU. nvtt_tools already runs its
# subprocesses through directx_texture_tools.run_proc, so pointing the main app's
# semaphore at the suite's covers every pool in the process.
convert_textures_gui.GLOBAL_JOB_SEMAPHORE = directx_texture_tools.GLOBAL_JOB_SEMAPHORE

log = logging.getLogger(__name__)

SUITE_TABS = [
    (NvttExportPanel,  "  Nvtt Export  "),
    (NvddsinfoPanel,   "  DDS Info  "),
    (NvimgdiffPanel,   "  Image Diff  "),
    (TexconvPanel,     "  Texconv  "),
    (TexassemblePanel, "  Texassemble  "),
    (TexdiagPanel,     "  Texdiag  "),
]


class IntegratedApp(App):
    """The existing App plus the DirectXTex tool tabs."""

    def __init__(self) -> None:
        super().__init__()

        # Each suite panel: controls into the Notebook, action bar + log into a
        # sibling frame inside the shared bottom pane. tab index -> (panel, bottom)
        self._suite: dict[int, tuple] = {}
        for cls, title in SUITE_TABS:
            bottom = ttk.Frame(self._bottom_pane)
            panel = cls(self._notebook, bottom_host=bottom)
            self._notebook.add(panel, text=title)
            self._suite[self._notebook.index(panel)] = (panel, bottom)

        self.minsize(1000, 860)
        self._integrated_ready = True
        self._apply_tab_layout()
        log.debug("IntegratedApp ready — %d suite tab(s): %s",
                  len(self._suite), ", ".join(t.strip() for _c, t in SUITE_TABS))

    # ── helpers ────────────────────────────────────────────────────────────
    def _cur(self) -> int:
        try:
            return self._notebook.index("current")
        except Exception:
            return -1

    def _apply_tab_layout(self) -> None:
        """Show the active tab's bottom strip in the shared bottom pane."""
        shared = getattr(self, "_shared_bottom", None)
        suite = getattr(self, "_suite", None)
        if shared is None or suite is None:
            return
        if shared.winfo_manager():
            shared.pack_forget()
        for _idx, (_p, b) in suite.items():
            if b.winfo_manager():
                b.pack_forget()
        cur = self._cur()
        if cur in suite:
            suite[cur][1].pack(fill="both", expand=True)
        else:
            shared.pack(fill="both", expand=True)

    # ── overrides ──────────────────────────────────────────────────────────
    def _on_tab_changed(self, event=None) -> None:
        if not getattr(self, "_integrated_ready", False):
            return super()._on_tab_changed(event)
        self._apply_tab_layout()
        if self._cur() in self._suite:
            ToolTip.hide_all()
        else:
            super()._on_tab_changed(event)

    def _start(self) -> None:
        if self._cur() in getattr(self, "_suite", {}):
            return  # suite tabs drive themselves
        super()._start()

    def _on_global_window_drop(self, event=None) -> None:
        # The App's window-level drop handler only understands the built-in
        # PNG↔DDS tabs; suite tabs handle their own drops, so ignore here.
        if self._cur() in getattr(self, "_suite", {}):
            return
        super()._on_global_window_drop(event)

    def _on_close(self) -> None:
        log.debug("IntegratedApp closing — cancelling %d suite panel(s)", len(getattr(self, "_suite", {})))
        for panel, _b in getattr(self, "_suite", {}).values():
            try:
                panel._cancel_run()
            except Exception as e:
                log.debug("error cancelling panel %s on close: %s", getattr(panel, "TOOL", "?"), e)
        super()._on_close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("DDSCONVERTER_LOGLEVEL", "WARNING").upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    app = IntegratedApp()
    app.mainloop()


if __name__ == "__main__":
    main()
