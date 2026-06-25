"""
directx_texture_tools.py  –  DirectXTex GUI toolset

A standalone, runnable set of panels that front-end Microsoft's DirectXTex CLI
tools, sharing the look and architecture of convert_textures_gui.py:

  • Texconv     – full PNG/image → DDS converter (every texconv flag exposed)
  • Texassemble – build cubemaps / arrays / volumes / merges from images
  • Texdiag     – inspect / analyze / compare DDS & image files

Each panel is a ttk.Frame: run this file for the standalone 3-tab suite, or embed
the panels as Notebook tabs (convert_textures_integrated.py does that). Controls
live in the panel (framed by the Notebook); the action bar + log are built into a
`bottom_host` so an embedding app can place them in its shared bottom pane.

The official CLI tools are Windows-only; cross-platform builds exist
(matyalatte/Texconv-Custom-DLL) or run the .exe under Wine. Point each path field
at the binary you have.

Requires: Python 3.10+, tkinter (tkinterdnd2 optional).
"""

from __future__ import annotations

import os
import json
import shutil
import signal
import logging
import platform
import threading
import subprocess
import time
from pathlib import Path
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _HAS_DND = True
except Exception:                       # pragma: no cover
    TkinterDnD = None
    DND_FILES = None
    _HAS_DND = False

# Module logger. Silent by default; set DXTEX_LOGLEVEL=DEBUG (standalone) or
# DDSCONVERTER_LOGLEVEL=DEBUG (integrated app) to get a full execution trace.
log = logging.getLogger(__name__)

# Global cap on simultaneously-running subprocesses, shared across every tab/pool
# in the integrated app (the launcher points the main app's reference at this one
# too). Stops the converter plus several suite tabs from together oversubscribing
# the GPU/CPU. A pool may still queue more workers; each waits here for a slot.
GLOBAL_JOB_LIMIT = max(1, min(16, os.cpu_count() or 2))
GLOBAL_JOB_SEMAPHORE = threading.BoundedSemaphore(GLOBAL_JOB_LIMIT)

# ── Palette / fonts (matched to convert_textures_gui.py) ──────────────────────
BG, BG2, BG3, BG4 = "#181818", "#232323", "#2e2e2e", "#3a3a3a"
FG, FG_DIM, ACCENT = "#e0e0e0", "#777777", "#5c9cf5"
SUCCESS, ERROR, WARN, BORDER = "#6abf69", "#e57373", "#ffb74d", "#404040"
_WIN = platform.system() == "Windows"
_MAC = platform.system() == "Darwin"
FONT      = ("Segoe UI", 10) if _WIN else ("SF Pro Text", 10) if _MAC else ("DejaVu Sans", 10)
FONT_BOLD = ("Segoe UI", 10, "bold") if _WIN else ("SF Pro Text", 10, "bold") if _MAC else ("DejaVu Sans", 10, "bold")
FONT_TITLE = ("Segoe UI", 13, "bold") if _WIN else ("SF Pro Text", 13, "bold") if _MAC else ("DejaVu Sans", 13, "bold")
FONT_MONO = ("Consolas", 9) if _WIN else ("Menlo", 9) if _MAC else ("DejaVu Sans Mono", 9)

# ── Metadata from the DirectXTex --help output ────────────────────────────────
TEXCONV_FORMATS = [
    "BC1_UNORM", "BC1_UNORM_SRGB", "BC2_UNORM", "BC2_UNORM_SRGB",
    "BC3_UNORM", "BC3_UNORM_SRGB", "BC4_UNORM", "BC4_SNORM",
    "BC5_UNORM", "BC5_SNORM", "BC6H_UF16", "BC6H_SF16",
    "BC7_UNORM", "BC7_UNORM_SRGB", "BC3n", "DXT5nm", "RXGB",
    "R8G8B8A8_UNORM", "R8G8B8A8_UNORM_SRGB", "R8G8B8A8_SNORM",
    "B8G8R8A8_UNORM", "B8G8R8A8_UNORM_SRGB", "B8G8R8X8_UNORM",
    "R16G16B16A16_FLOAT", "R16G16B16A16_UNORM", "R32G32B32A32_FLOAT",
    "R10G10B10A2_UNORM", "R11G11B10_FLOAT", "R9G9B9E5_SHAREDEXP",
    "B5G6R5_UNORM", "B5G5R5A1_UNORM", "B4G4R4A4_UNORM",
    "R8_UNORM", "R8G8_UNORM", "A8_UNORM",
    "DXT1", "DXT3", "DXT5", "RGBA", "BGRA", "BGR", "FP16", "FP32", "BPTC", "BPTC_FLOAT", "RGB24",
]
ASSEMBLE_FORMATS = [
    "R8G8B8A8_UNORM", "R8G8B8A8_UNORM_SRGB", "B8G8R8A8_UNORM", "B8G8R8A8_UNORM_SRGB",
    "R16G16B16A16_FLOAT", "R32G32B32A32_FLOAT", "R10G10B10A2_UNORM", "R11G11B10_FLOAT",
    "B5G6R5_UNORM", "B5G5R5A1_UNORM", "B4G4R4A4_UNORM", "RGBA", "BGRA", "FP16", "FP32",
]
FILTERS = [
    "FANT", "CUBIC", "TRIANGLE", "LINEAR", "POINT", "BOX",
    "FANT_DITHER", "CUBIC_DITHER", "TRIANGLE_DITHER", "BOX_DITHER", "POINT_DITHER", "LINEAR_DITHER",
    "FANT_DITHER_DIFFUSION", "CUBIC_DITHER_DIFFUSION", "BOX_DITHER_DIFFUSION",
    "TRIANGLE_DITHER_DIFFUSION", "POINT_DITHER_DIFFUSION", "LINEAR_DITHER_DIFFUSION",
]
FEATURE_LEVELS = ["Default", "9.1", "9.2", "9.3", "10.0", "10.1", "11.0", "11.1", "12.0", "12.1", "12.2"]
ROTATE_OPTS = ["", "709to2020", "2020to709", "709toHDR10", "HDR10to709",
               "P3D65to2020", "P3D65toHDR10", "709toP3D65", "P3D65to709"]
# Output file types. `exr` is offered by the matyalatte cross-platform build;
# the rest are common to both. texconv ignores types it doesn't support.
FILETYPES = ["dds", "png", "tga", "bmp", "jpg", "jpeg", "tif", "tiff",
             "hdr", "exr", "ppm", "pfm", "jxr", "wdp", "hdp", "ddx", "heif"]
COLORSPACE_MAP = {"Linear": "", "sRGB": "-srgb", "sRGB in": "-srgbi", "sRGB out": "-srgbo"}
ADDRESSING_MAP = {"clamp": "", "wrap": "-wrap", "mirror": "-mirror"}
HEADER_MAP = {"Default": "", "DX10": "-dx10", "DX9": "-dx9"}
IMAGE_EXTS = (".png", ".tga", ".bmp", ".jpg", ".jpeg", ".tif", ".tiff", ".hdr", ".dds")


def _cfg_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming")))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")))
    d = base / "DDSConverter"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        return Path(__file__).parent
    return d


# ── Subprocess helpers ─────────────────────────────────────────────────────────
def _hidden_startupinfo():
    if os.name != "nt":
        return None, 0
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si, subprocess.CREATE_NO_WINDOW


def _run_capture(cmd, timeout=8):
    si, flags = _hidden_startupinfo()
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, startupinfo=si, creationflags=flags)


def _kill(proc):
    log.debug("_kill: terminating pid %s", getattr(proc, "pid", "?"))
    try:
        if os.name == "nt":
            si, flags = _hidden_startupinfo()
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, startupinfo=si, creationflags=flags)
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                proc.kill()
    except Exception as e:
        log.debug("_kill: failed for pid %s: %s", getattr(proc, "pid", "?"), e)


def find_tool(explicit, base, probe_args=None):
    """Resolve a tool path and confirm it's the right CLI by capturing its output.

    probe_args is what to pass when probing (default: no args). Some tools (e.g.
    nvtt_export) launch a GUI when run with no args, so pass ["--help"] for those;
    others (nvddsinfo) treat --help as a filename, so they probe with no args.
    """
    cands = []
    if explicit and explicit != base:
        cands.append(explicit)
    cands += [base, base + ".exe"]
    args = list(probe_args or [])
    log.debug("find_tool(%s): probing %s with args %s", base, cands, args)
    for name in cands:
        path = shutil.which(name) or (name if os.path.isfile(name) else None)
        if not path:
            log.debug("find_tool(%s): candidate %r not on PATH/disk", base, name)
            continue
        try:
            res = _run_capture([path] + args, timeout=5)
            out = ((res.stdout or b"") + (res.stderr or b"")).lower()
            if base.encode() in out or b"directxtex" in out or b"nvidia texture tools" in out:
                log.debug("find_tool(%s): resolved to %s", base, path)
                return path
            log.debug("find_tool(%s): %s ran but signature not matched", base, path)
        except Exception as e:
            log.debug("find_tool(%s): probe of %s failed: %s", base, path, e)
            continue
    log.debug("find_tool(%s): no working executable found", base)
    return None


def run_proc(cmd, active, lock, cancel):
    """Run one subprocess with cancellation; return (returncode, output)."""
    proc = None
    log.debug("run_proc: exec %s", " ".join(map(str, cmd)))
    # Wait for a global job slot, staying responsive to cancellation.
    while not GLOBAL_JOB_SEMAPHORE.acquire(timeout=0.1):
        if cancel.is_set():
            return None, "[aborted]"
    try:
        si, flags = _hidden_startupinfo()
        if os.name == "nt":
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, creationflags=flags, startupinfo=si,
                                start_new_session=(os.name != "nt"))
        with lock:
            active.add(proc)
            if cancel.is_set():
                log.debug("run_proc: cancelled before drain, killing pid %s", proc.pid)
                _kill(proc)
                return None, "[aborted]"
        log.debug("run_proc: started pid %s", proc.pid)
        out = err = ""
        while True:
            if cancel.is_set():
                log.debug("run_proc: cancel signalled, killing pid %s", proc.pid)
                _kill(proc)
                return None, "[aborted]"
            try:
                out, err = proc.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
        log.debug("run_proc: pid %s exited rc=%s", proc.pid, proc.returncode)
        return proc.returncode, (err or out or "")
    except FileNotFoundError:
        log.debug("run_proc: executable not found: %s", cmd[0] if cmd else "?")
        return None, "[executable not found]"
    except Exception as e:
        log.debug("run_proc: execution error: %s", e, exc_info=True)
        return None, f"[execution error] {e}"
    finally:
        GLOBAL_JOB_SEMAPHORE.release()
        if proc is not None:
            with lock:
                active.discard(proc)


# ── Tooltip + styles ───────────────────────────────────────────────────────────
class ToolTip:
    active: list["ToolTip"] = []

    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)
        widget.bind("<Button-1>", self.hide)
        if isinstance(widget, ttk.Combobox):
            widget.bind("<<ComboboxSelected>>", self.hide, add=True)

    def show(self, _=None):
        ToolTip.hide_all()
        x = self.widget.winfo_rootx() + 24
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        ToolTip.active.append(self)
        tk.Label(tw, text=self.text, background=BG3, foreground=FG, relief="solid",
                 borderwidth=1, font=("Segoe UI", 9), justify="left", wraplength=380).pack(padx=1, pady=1)

    def hide(self, _=None):
        if self.tip:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None
        if self in ToolTip.active:
            ToolTip.active.remove(self)

    @classmethod
    def hide_all(cls):
        for t in list(cls.active):
            t.hide()


def apply_styles(root):
    s = ttk.Style(root)
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    s.configure(".", background=BG2, foreground=FG, bordercolor=BORDER,
                troughcolor=BG4, fieldbackground=BG3, font=FONT)
    s.configure("TFrame", background=BG2)
    s.configure("TLabel", background=BG2, foreground=FG, font=FONT)
    s.configure("Dim.TLabel", background=BG2, foreground=FG_DIM, font=FONT)
    s.configure("Title.TLabel", background=BG, foreground=FG, font=FONT_TITLE)
    s.configure("TButton", background=BG4, foreground=FG, bordercolor=BORDER, padding=(8, 4))
    s.map("TButton", background=[("active", "#4a4a4a"), ("disabled", BG3)], foreground=[("disabled", FG_DIM)])
    s.configure("Primary.TButton", background=ACCENT, foreground="#ffffff", font=FONT_BOLD, padding=(16, 6))
    s.map("Primary.TButton", background=[("active", "#4888e8"), ("disabled", BG4)], foreground=[("disabled", FG_DIM)])
    s.configure("Danger.TButton", background="#9c3030", foreground="#ffffff", font=FONT_BOLD, padding=(16, 6))
    s.map("Danger.TButton", background=[("active", "#b03838"), ("disabled", BG4)], foreground=[("disabled", FG_DIM)])
    s.configure("TEntry", fieldbackground=BG3, foreground=FG, insertcolor=FG, bordercolor=BORDER)
    s.configure("TCombobox", fieldbackground=BG3, background=BG4, foreground=FG, arrowcolor=FG_DIM)
    s.map("TCombobox", fieldbackground=[("readonly", BG3)], selectbackground=[("readonly", BG3)], selectforeground=[("readonly", FG)])
    root.option_add("*TCombobox*Listbox.background", BG3)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    s.configure("TSpinbox", fieldbackground=BG3, foreground=FG, arrowcolor=FG_DIM, background=BG4)
    s.configure("TCheckbutton", background=BG2, foreground=FG)
    s.map("TCheckbutton", background=[("active", BG2)])
    s.configure("TProgressbar", troughcolor=BG4, background=ACCENT, bordercolor=BG4)
    s.configure("TNotebook", background=BG, bordercolor=BORDER)
    s.configure("TNotebook.Tab", background=BG3, foreground=FG_DIM, padding=(14, 6))
    s.map("TNotebook.Tab", background=[("selected", BG2)], foreground=[("selected", FG)])


# ── Shared base panel ──────────────────────────────────────────────────────────
class ToolPanel(ttk.Frame):
    TOOL = "tool"
    CONFIG = "tool.json"
    RUN_LABEL = "Run"
    PROBE_ARGS: list[str] = []   # args used to probe the exe (e.g. ["--help"])
    HELP_TITLE = ""              # window title for the per-tab help guide
    HELP_TEXT = ""              # detailed per-tab user guide (set by each panel)

    def _resolve_exe(self):
        """Resolve and verify the tool's executable using its safe probe args."""
        return find_tool(self._exe_var.get().strip(), self.TOOL, self.PROBE_ARGS)

    def __init__(self, master, bottom_host=None):
        super().__init__(master)
        self._bottom_host = bottom_host if bottom_host is not None else self
        cpu = os.cpu_count() or 2
        self._cpu_limit = min(16, cpu)
        self._default_workers = max(1, min(4, cpu // 2))
        self._running = False
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._active: set = set()
        self._cfg_map: dict[str, tk.Variable] = {}
        self._exe_var = tk.StringVar(value=self.TOOL)
        # Save-log infrastructure (parity with the main converter).
        self._log_buffer: list[str] = []
        self._log_file_var = tk.BooleanVar(value=False)
        self._log_path_var = tk.StringVar()
        # (widget, enable_var) pairs for checkbox-gated value fields.
        self._gated_fields: list = []
        self._make_vars()
        self._cfg_map.setdefault("exe", self._exe_var)
        self._build_controls(self)
        self._build_bottom(self._bottom_host)
        self._load_config()
        self._toggle_log_path()
        self._sync_gates()      # reflect loaded enable-checkbox states on the fields
        self._post_init()

    # subclasses implement these
    def _make_vars(self): ...
    def _build_controls(self, parent): ...
    def _post_init(self): ...
    def _start(self): ...

    # ── shared UI helpers used by _build_controls ──────────────────────────
    @staticmethod
    def _chk(parent, text, var, tip, cmd=None):
        c = ttk.Checkbutton(parent, text=text, variable=var, command=cmd) if cmd \
            else ttk.Checkbutton(parent, text=text, variable=var)
        c.pack(side="left", padx=(0, 14)); ToolTip(c, tip); return c

    @staticmethod
    def _combo(parent, label, var, values, width, tip, cmd=None):
        if label:
            ttk.Label(parent, text=label).pack(side="left")
        cb = ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=width)
        cb.pack(side="left", padx=(6, 16)); ToolTip(cb, tip)
        if cmd:
            cb.bind("<<ComboboxSelected>>", lambda _e: cmd())
        return cb

    @staticmethod
    def _spin(parent, label, var, frm, to, inc, fmt, width, tip, state="normal"):
        if label:
            ttk.Label(parent, text=label).pack(side="left")
        sp = ttk.Spinbox(parent, from_=frm, to=to, increment=inc, format=fmt,
                         textvariable=var, width=width, state=state)
        sp.pack(side="left", padx=(6, 16)); ToolTip(sp, tip); return sp

    @staticmethod
    def _entry(parent, label, var, width, tip):
        if label:
            ttk.Label(parent, text=label).pack(side="left")
        e = ttk.Entry(parent, textvariable=var, width=width)
        e.pack(side="left", padx=(6, 16)); ToolTip(e, tip); return e

    # ── enable-gated value fields (parity with the PNG↔DDS tabs) ─────────────
    def _sync_gates(self):
        """Enable/disable every gated field from its checkbox state."""
        for widget, en_var in getattr(self, "_gated_fields", ()):
            try:
                widget.configure(state="normal" if en_var.get() else "disabled")
            except tk.TclError as e:
                log.debug("%s: gate sync failed for %r: %s", self.TOOL, widget, e)

    def _opt_spin(self, parent, label, en_var, var, frm, to, inc, fmt, width, tip):
        """Spinbox preceded by an enable checkbox: disabled until ticked, and the
        flag is omitted while off (mirrors the 'Max mip count' override fields)."""
        chk = ttk.Checkbutton(parent, text=label, variable=en_var, command=self._sync_gates)
        chk.pack(side="left", padx=(0, 4)); ToolTip(chk, f"Enable to apply {label.lower()}.")
        sp = ttk.Spinbox(parent, from_=frm, to=to, increment=inc, format=fmt,
                         textvariable=var, width=width, state="disabled")
        sp.pack(side="left", padx=(0, 16)); ToolTip(sp, tip)
        self._gated_fields.append((sp, en_var))
        return sp

    def _opt_entry(self, parent, label, en_var, var, width, tip):
        """Entry preceded by an enable checkbox: disabled until ticked, flag
        omitted while off."""
        chk = ttk.Checkbutton(parent, text=label, variable=en_var, command=self._sync_gates)
        chk.pack(side="left", padx=(0, 4)); ToolTip(chk, f"Enable to apply {label.lower()}.")
        e = ttk.Entry(parent, textvariable=var, width=width, state="disabled")
        e.pack(side="left", padx=(0, 16)); ToolTip(e, tip)
        self._gated_fields.append((e, en_var))
        return e

    def _gate_extra(self, widget, en_var):
        """Attach an extra widget to an existing checkbox's enable var (for groups
        like RGBA weights gated by a single toggle)."""
        widget.configure(state="disabled")
        self._gated_fields.append((widget, en_var))
        return widget

    def _path_row(self, cfg, row, label, var, on_folder=None, on_file=None, browse=None, test=None, launch=None):
        ttk.Label(cfg, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        ent = ttk.Entry(cfg, textvariable=var)
        ent.grid(row=row, column=1, sticky="ew", padx=(8, 6))
        bf = ttk.Frame(cfg); bf.grid(row=row, column=2, sticky="ew")
        if test:
            b = ttk.Button(bf, text="Test", command=test); b.pack(side="left", padx=(0, 2)); ToolTip(b, "Check the executable.")
        if launch:
            b = ttk.Button(bf, text="Open", command=launch); b.pack(side="left", padx=(0, 2)); ToolTip(b, "Launch this executable's native app/window (point the path at the GUI build if it has one).")
        if on_folder:
            b = ttk.Button(bf, text="Folder…", command=on_folder); b.pack(side="left", padx=(0, 2)); ToolTip(b, "Choose a folder.")
        if on_file:
            b = ttk.Button(bf, text="File…", command=on_file); b.pack(side="left", padx=(0, 2)); ToolTip(b, "Choose a file.")
        if browse:
            b = ttk.Button(bf, text="Browse…", command=browse); b.pack(side="left"); ToolTip(b, "Browse…")
        return ent

    # ── action bar + log ───────────────────────────────────────────────────
    def _build_bottom(self, parent):
        ttk.Separator(parent).pack(fill="x", pady=(4, 0))
        act = ttk.Frame(parent); act.pack(fill="x", padx=10, pady=8)
        self._go_btn = ttk.Button(act, text=self.RUN_LABEL, style="Primary.TButton", command=self._start)
        self._go_btn.pack(side="left")
        self._stop_btn = ttk.Button(act, text="Cancel", style="Danger.TButton", command=self._cancel_run, state="disabled")
        self._stop_btn.pack(side="left", padx=(8, 0))
        self._status = ttk.Label(act, text="", style="Dim.TLabel")
        self._status.pack(side="left", padx=(14, 0))
        b = ttk.Button(act, text="Clear log", command=self._clear_log); b.pack(side="right")
        # Save-log controls (parity with the main converter). Packed right-to-left.
        self._log_browse_btn = ttk.Button(act, text="…", width=2, command=self._browse_log_path, state="disabled")
        self._log_browse_btn.pack(side="right", padx=(0, 8)); ToolTip(self._log_browse_btn, "Choose where to save the log.")
        self._log_path_entry = ttk.Entry(act, textvariable=self._log_path_var, width=18, state="disabled")
        self._log_path_entry.pack(side="right", padx=(0, 2))
        self._log_chk = ttk.Checkbutton(act, text="Save log", variable=self._log_file_var, command=self._toggle_log_path)
        self._log_chk.pack(side="right", padx=(0, 4))
        ToolTip(self._log_chk, "Write the full log to a file when the run finishes (blank path = timestamped file in the config folder).")
        if hasattr(self, "_preview_command"):
            b = ttk.Button(act, text="Show command", command=self._preview_command); b.pack(side="right", padx=(0, 8))
            ToolTip(b, "Preview the command for the current settings.")
        if self.HELP_TEXT:
            self._help_btn = ttk.Button(act, text="?  Guide", command=self._show_help)
            self._help_btn.pack(side="right", padx=(0, 8))
            ToolTip(self._help_btn, "Open the detailed guide for this tool.")
        self._bar = ttk.Progressbar(parent, mode="determinate")
        self._bar.pack(fill="x", padx=10, pady=(0, 8))
        wrap = ttk.Frame(parent); wrap.pack(fill="both", expand=True, padx=10, pady=(0, 12))
        self._log = tk.Text(wrap, bg=BG3, fg=FG, font=FONT_MONO, borderwidth=0, highlightthickness=1,
                            height=6, highlightbackground=BORDER, highlightcolor=ACCENT, wrap="none", state="disabled")
        self._log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self._log.yview); sb.pack(side="right", fill="y")
        self._log["yscrollcommand"] = sb.set
        for tag, col in (("ok", SUCCESS), ("fail", ERROR), ("warn", WARN), ("header", ACCENT), ("dim", FG_DIM)):
            self._log.tag_configure(tag, foreground=col)
        # The log lives in the bottom host (a sibling of this panel when embedded),
        # so register it for drops too — dropping a file/folder on the log fills
        # the source field just like dropping on the controls.
        self._register_drop(wrap)
        self._register_drop(self._log)

    # ── help guide ────────────────────────────────────────────────────────────
    def _show_help(self):
        """Open a scrollable, read-only guide for this tool (matches the main app)."""
        text = self.HELP_TEXT or f"No help available for {self.TOOL}."
        win = tk.Toplevel(self)
        win.title(self.HELP_TITLE or f"{self.TOOL} · Help")
        win.minsize(680, 600)
        win.transient(self.winfo_toplevel())
        # Deliberately NOT modal (no grab_set): the guide can stay open while a run
        # is in progress, so the Cancel button on the tab stays clickable.
        win.configure(bg=BG2)
        container = ttk.Frame(win)
        container.pack(expand=True, fill="both", padx=10, pady=10)
        sb = ttk.Scrollbar(container, orient="vertical")
        sb.pack(side="right", fill="y")
        txt = tk.Text(container, bg=BG3, fg=FG, font=("Segoe UI", 10), wrap="word",
                      borderwidth=0, highlightthickness=0, padx=12, pady=10, yscrollcommand=sb.set)
        txt.pack(side="left", expand=True, fill="both")
        sb.config(command=txt.yview)
        txt.insert("1.0", text)
        txt.configure(state="disabled")
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 10))

    # ── log helpers ─────────────────────────────────────────────────────────
    def _log_line(self, text, tag=""):
        self._log_buffer.append(text)
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n", tag)
        # Bound the visible widget so a huge batch can't balloon memory or slow the
        # UI; the full log is still kept in _log_buffer for Save log.
        if int(self._log.index("end-1c").split(".")[0]) > 6000:
            self._log.delete("1.0", "2000.0")
        self._log.configure(state="disabled")
        self._log.see("end")

    def _toggle_log_path(self):
        st = "normal" if self._log_file_var.get() else "disabled"
        self._log_path_entry.configure(state=st)
        self._log_browse_btn.configure(state=st)

    def _browse_log_path(self):
        f = filedialog.asksaveasfilename(
            title="Save log as", defaultextension=".log",
            initialfile=f"{self.TOOL}_{time.strftime('%Y%m%d_%H%M%S')}.log",
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")])
        if f:
            self._log_path_var.set(f)

    def _write_log_file(self):
        if not self._log_file_var.get():
            return
        path = self._log_path_var.get().strip()
        if not path:
            path = str(_cfg_dir() / f"{self.TOOL}_{time.strftime('%Y%m%d_%H%M%S')}.log")
        try:
            Path(path).write_text("\n".join(self._log_buffer), encoding="utf-8")
            self._log_line(f"📄 Log saved → {path}", "dim")
        except Exception as e:
            self._warn(f"Log write failed: {e}")

    def _ok(self, m):   self._log_line(f"✔ {m}", "ok")
    def _fail(self, m): self._log_line(f"✖ {m}", "fail")
    def _warn(self, m): self._log_line(f"⚠ {m}", "warn")
    def _head(self, m): self._log_line(m, "header")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        self._bar.configure(value=0)
        self._status.configure(text="")

    def _safe_after(self, func, *args):
        try:
            self.after(0, func, *args)
        except (tk.TclError, RuntimeError) as e:
            log.debug("%s: _safe_after dropped a callback (window closing?): %s", self.TOOL, e)

    @staticmethod
    def _flat_collisions(predicted):
        """Output paths that more than one source maps to (silent-overwrite risk).

        Returns a list of (path_str, count) for any destination produced by two
        or more inputs — e.g. a/tex.png and b/tex.png both flattening to
        out/tex.dds. Paths are folded with os.path.normcase so comparison matches
        the host filesystem: case-insensitive on Windows, case-sensitive on POSIX
        (so Tex.dds and tex.dds are distinct on Linux and not falsely flagged).
        """
        counts: dict[str, int] = {}
        first: dict[str, str] = {}
        for p in predicted:
            k = os.path.normcase(str(p))
            counts[k] = counts.get(k, 0) + 1
            first.setdefault(k, str(p))
        return [(first[k], n) for k, n in counts.items() if n > 1]

    # ── run state ───────────────────────────────────────────────────────────
    def _arm(self, total):
        self._log_buffer.clear()
        self._log_buffer.append(f"=== {self.TOOL} run {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        self._save_config()
        self._running = True
        self._cancel.clear()
        with self._lock:
            self._active.clear()
        self._go_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._bar.configure(maximum=max(1, total), value=0)
        self._status.configure(text=f"0 / {total}")
        log.debug("%s: run armed — %d item(s)", self.TOOL, total)

    def _disarm(self):
        self._running = False
        self._go_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        log.debug("%s: run disarmed", self.TOOL)

    def _cancel_run(self):
        if not self._running:
            return
        self._cancel.set()
        self._stop_btn.configure(state="disabled")
        self._warn("Cancelling…")
        with self._lock:
            procs = list(self._active)
            self._active.clear()
        log.debug("%s: cancel requested — killing %d active process(es)", self.TOOL, len(procs))
        for p in procs:
            _kill(p)

    # ── generic parallel per-file runner ───────────────────────────────────
    def _run_parallel(self, jobs, fn, workers, log_each=True, on_finish=None):
        """jobs: list; fn(job) -> (ok: bool, msg: str). Runs in a pool with progress.

        log_each=False suppresses the per-item success line (failures are still
        shown), and on_finish() runs once on the main thread after every job is
        done. Together they let a caller collect output during the parallel run
        and render it in a deterministic order at the end, instead of letting
        nondeterministic worker-completion order interleave the log.
        """
        total = len(jobs)
        log.debug("%s: parallel run — %d job(s), %d worker(s)", self.TOOL, total, workers)
        state = {"ok": 0, "done": 0}

        def on_done(ok, msg):
            state["done"] += 1
            if ok:
                state["ok"] += 1
                if log_each:
                    self._ok(msg)
            else:
                self._fail(msg)
            self._bar.configure(value=state["done"])
            self._status.configure(text=f"{state['done']} / {total}")

        def worker():
            pool = ThreadPoolExecutor(max_workers=workers)
            try:
                futures = {pool.submit(fn, j): j for j in jobs}
                while futures:
                    if self._cancel.is_set():
                        for f in futures:
                            f.cancel()
                        break
                    done, _ = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                    for fut in done:
                        futures.pop(fut)
                        try:
                            ok, msg = fut.result()
                        except Exception as e:
                            ok, msg = False, f"[crash] {e}"
                            log.debug("%s: job raised: %s", self.TOOL, e, exc_info=True)
                        self._safe_after(on_done, ok, msg)
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
            cancelled = self._cancel.is_set()

            def done():
                self._disarm()
                if on_finish:
                    on_finish()
                if cancelled:
                    self._warn("Cancelled.")
                else:
                    self._log_line(f"✔ Done. {state['ok']} / {total} succeeded.", "ok")
                log.debug("%s: run complete — %d/%d succeeded, cancelled=%s", self.TOOL, state["ok"], total, cancelled)
                self._write_log_file()
            self._safe_after(done)
        threading.Thread(target=worker, daemon=True).start()

    # ── single-command runner (texassemble / texdiag diff) ─────────────────
    def _run_single(self, cmd, success_check=None):
        self._arm(1)
        self._head("  " + " ".join(f'"{c}"' if " " in c else c for c in cmd))

        def worker():
            rc, out = run_proc(cmd, self._active, self._lock, self._cancel)
            ok = (rc == 0) and (success_check() if success_check else True)
            text = out.strip()
            log.debug("%s: single command rc=%s ok=%s", self.TOOL, rc, ok)

            def finish():
                self._disarm()
                self._bar.configure(value=1)
                self._status.configure(text="1 / 1")
                if text:
                    for line in text.splitlines():
                        self._log_line("  " + line, "dim")
                if self._cancel.is_set():
                    self._warn("Cancelled.")
                elif ok:
                    self._ok("Done.")
                else:
                    self._fail("Failed (see output above).")
                self._write_log_file()
            self._safe_after(finish)
        threading.Thread(target=worker, daemon=True).start()

    # ── browse / dnd ────────────────────────────────────────────────────────
    def _browse_into(self, var, kind="dir", title="Select"):
        if kind == "dir":
            p = filedialog.askdirectory(title=title)
        else:
            p = filedialog.askopenfilename(title=title)
        if p:
            var.set(os.path.normpath(p))

    def _browse_exe_into(self, var, title):
        ft = [("Executables", "*.exe"), ("All files", "*.*")] if os.name == "nt" else [("All files", "*.*")]
        p = filedialog.askopenfilename(title=title, filetypes=ft)
        if p:
            var.set(os.path.normpath(p))

    def _test_exe(self):
        # Read the Tk path field on the main thread, then probe in a worker so a
        # slow or hung binary can't freeze the GUI (find_tool touches no Tk state).
        explicit = self._exe_var.get().strip()
        probe = list(self.PROBE_ARGS)
        self._head(f"Testing {self.TOOL}…")

        def worker():
            resolved = find_tool(explicit, self.TOOL, probe)

            def done():
                if resolved:
                    self._ok(f"Found: {resolved}")
                    messagebox.showinfo(self.TOOL, f"Found and runnable:\n\n{resolved}")
                else:
                    self._fail(f"No working '{self.TOOL}' found.")
                    messagebox.showerror(self.TOOL, f"Could not find a working '{self.TOOL}'. Set its path or put it on PATH.")
            self._safe_after(done)
        threading.Thread(target=worker, daemon=True).start()

    def _launch_native(self, path=None):
        """Launch the executable as its own detached process, using the right
        mechanism for the host OS (so a GUI build opens its window)."""
        raw = (path if path is not None else self._exe_var.get()).strip()
        resolved = raw if (raw and os.path.isfile(raw)) else (shutil.which(raw) if raw else None)
        if not resolved:
            self._fail(f"Couldn't find '{raw or self.TOOL}' to launch.")
            return
        try:
            if os.name == "nt":
                os.startfile(resolved)  # type: ignore[attr-defined]  # Windows shell-launch
            elif platform.system() == "Darwin":
                if resolved.endswith(".app") or os.path.isdir(resolved):
                    subprocess.Popen(["open", resolved])
                else:
                    subprocess.Popen([resolved], start_new_session=True)
            else:
                subprocess.Popen([resolved], start_new_session=True)
            self._log_line(f"Launched native app: {resolved}", "dim")
        except Exception as e:
            self._fail(f"Could not launch '{resolved}': {e}")

    def _register_drop(self, widget):
        """Make one widget a file drop target that fills this panel's source field."""
        if not _HAS_DND or not hasattr(self, "_dnd_var"):
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", lambda e: self._on_drop(e, self._dnd_var))
        except Exception as e:
            log.debug("%s: drop registration failed for %r: %s", self.TOOL, widget, e)

    def _setup_dnd(self, entry, var):
        if not _HAS_DND:
            return
        self._dnd_var = var
        # Register the source entry AND the whole panel, so a drop anywhere on the
        # tab fills the source field — matching the PNG↔DDS tabs. Registering the
        # panel also keeps suite-tab drops from falling through to the host app's
        # window-level handler (which only knows the built-in tabs). The log pane
        # is registered separately in _build_bottom (it lives in the bottom host,
        # not under this panel, when embedded in the integrated app).
        for target in (entry, self):
            self._register_drop(target)

    def _on_drop(self, event, var):
        try:
            paths = self.tk.splitlist(event.data)
        except Exception as e:
            log.debug("%s: could not splitlist drop data %r: %s", self.TOOL, event.data, e)
            paths = [event.data]
        if paths:
            p = os.path.normpath(paths[0].strip().strip("{}").strip('"'))
            log.debug("%s: drop → %s", self.TOOL, p)
            var.set(p)

    # ── value helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _int_or_none(s):
        s = (s or "").strip()
        if not s:
            return None
        try:
            return int(float(s))
        except ValueError:
            return None

    def _float_or(self, var, default):
        try:
            return float(var.get())
        except (tk.TclError, ValueError):
            return default

    # ── config ──────────────────────────────────────────────────────────────
    def _config_file(self):
        return _cfg_dir() / self.CONFIG

    def _save_config(self):
        cfg = {}
        for k, v in self._cfg_map.items():
            try:
                cfg[k] = v.get()
            except tk.TclError as e:
                log.debug("%s: skipping unreadable config var %s: %s", self.TOOL, k, e)
        try:
            # Atomic write: a crash or a second instance writing concurrently can't
            # leave a half-written/corrupt config — os.replace swaps it in one step.
            dest = self._config_file()
            tmp = dest.with_suffix(dest.suffix + f".tmp{os.getpid()}")
            tmp.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
            os.replace(tmp, dest)
            log.debug("%s: config saved → %s (%d keys)", self.TOOL, dest, len(cfg))
        except Exception as e:
            log.debug("%s: config save failed: %s", self.TOOL, e)

    def _load_config(self):
        f = self._config_file()
        if not f.exists():
            log.debug("%s: no saved config at %s", self.TOOL, f)
            return
        try:
            cfg = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            log.debug("%s: config load failed (%s): %s", self.TOOL, f, e)
            return
        log.debug("%s: config loaded ← %s (%d keys)", self.TOOL, f, len(cfg))
        for k, v in self._cfg_map.items():
            if k in cfg:
                try:
                    v.set(cfg[k])
                except (tk.TclError, ValueError, TypeError) as e:
                    log.debug("%s: could not restore %s=%r: %s", self.TOOL, k, cfg[k], e)
        # Clamp the saved worker count into this machine's valid range — a config
        # written on a many-core box must not exceed the limit when reloaded here.
        wv = getattr(self, "_workers_var", None)
        if wv is not None:
            try:
                wv.set(max(1, min(int(wv.get()), self._cpu_limit)))
            except (tk.TclError, ValueError, TypeError):
                wv.set(self._default_workers)


def _collect(directory: Path, exts, recursive=True):
    it = directory.rglob("*") if recursive else directory.glob("*")
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in exts)


# ══════════════════════════════════════════════════════════════════════════════
#  TEXCONV
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class TexconvOpts:
    """Immutable snapshot of every texconv setting, taken on the main thread.

    Decouples command construction from Tk: _build_cmd() reads only this object,
    so it never touches a Tk variable (safe in worker threads) and can be
    unit-tested without a display.
    """
    exe: str
    ft: str
    fmt: str
    mips: int | None
    filt: str
    colorspace: str
    ignore_srgb: bool
    xlum: bool
    coverage: bool
    alpha_ref: float
    sepalpha: bool
    pmalpha: bool
    straight: bool
    bc_d: bool
    bc_u: bool
    bc_q: bool
    bc_x: bool
    use_aw: bool
    aw: float
    width: int | None
    height: int | None
    pow2: bool
    fl: str
    header: str
    dword: bool
    hflip: bool
    vflip: bool
    invy: bool
    reconz: bool
    x2: bool
    swizzle: str
    nmap: bool
    nmap_opts: str
    nmapamp: float
    rotate: str
    nits: str
    tonemap: bool
    tu: bool
    tf: bool
    badtails: bool
    permissive: bool
    ignoremips: bool
    fixbc: bool
    colorkey: str
    addr: str
    prefix: str
    suffix: str
    lower: bool
    nogpu: bool
    gpu: int | None
    single: bool
    timing: bool
    nowic: bool
    overwrite: bool


TEXCONV_HELP = """\
Texconv · Guide

texconv is Microsoft's DirectXTex image → DDS converter. This tab front-ends every
texconv flag; switch on the options you need and leave the rest off.

── Getting started ──
1. texconv path — point at texconv.exe (Windows) or a cross-platform build (e.g.
   matyalatte's Texconv-Custom-DLL on Linux). Leave it as "texconv" if it's on
   your PATH. Click Test to confirm it's found.
2. Source target — Browse to a folder of images or a single image (PNG, TGA, BMP,
   JPG, TIFF, HDR, DDS), or drag & drop it onto the tab — the log pane works too.
3. Output folder — leave blank to write each DDS next to its source, or set one.
   With Recursive scan + Mirror structure on, the source's subfolders are
   recreated under the output.
4. Pick a Format, set any options, and click "Convert → DDS".

── Optional value fields ──
Every spinbox and value entry sits behind a checkbox: tick it to enable the field
and send its flag, untick to leave it at the tool's default. So Mips, Width/Height,
GPU#, Colour key, Swizzle, Prefix/Suffix, etc. are only applied when ticked.

── Choosing a format (-f) ──
  • BC1  — opaque or 1-bit alpha, smallest. Albedo without transparency.
  • BC3  — full 8-bit alpha. Albedo with smooth transparency.
  • BC4  — single channel (height, roughness, a mask).
  • BC5  — two channels; the standard for tangent-space normal maps (X,Y; Z is
           reconstructed in-shader).
  • BC6H — HDR, no alpha. For .hdr/.exr environment maps.
  • BC7  — highest-quality RGBA, slower to compress. Hero textures.
  Quality knobs: BC max (-bc x) for best BC7, BC quick (-bc q) for speed, BC
  dither to reduce banding, BC7 alpha weight (-aw) to protect alpha detail.

── Alpha-test coverage (headline feature) ──
Tick "Preserve alpha coverage" (--keep-coverage) for alpha-tested textures —
foliage, fences, chain-link, hair. As mips shrink, the fraction of pixels passing
the alpha test drifts, so distant foliage thins out and sparkles. Coverage keeps
that fraction constant per mip. Set "Alpha ref" to the same cutoff your shader
uses (commonly 0.5) — it feeds both --keep-coverage and -at. "Separate alpha"
(-sepalpha) mips the alpha independently for crisper edges.

── Resizing & mipmaps ──
  • Width / Height (-w / -h) resize the output; leave off to keep the source size.
  • Fit pow-of-2 (-pow2) rounds dimensions up to a power of two.
  • Mips (-m): 0 = full chain down to 1×1, 1 = base image only.
  • Filter (-if) sets the resample/mip kernel (FANT is a solid default).

── Normal maps ──
  • Height → normal (-nmap) builds a tangent-space normal map from a height/bump
    input; "nmap opts" picks the height channel and options, "Amplitude" sets the
    bump strength.
  • Invert Y (--invert-y) flips green for the OpenGL ↔ DirectX convention.
  • Reconstruct Z and ×2−1 bias help when working with BC5 two-channel normals.

── HDR ──
  • Tonemap (--tonemap) + Paper-white nits (-nits) when converting HDR down to an
    SDR format.
  • Rotate colour (--rotate-color) converts between colour primaries
    (e.g. Rec.709 ↔ Rec.2020 / HDR10).

── Colour space ──
"Colour" tags or converts sRGB vs linear (-srgb/-srgbi/-srgbo). Use sRGB for
albedo/colour maps and Linear for data maps (normals, roughness, masks).

── Naming & output ──
Prefix/Suffix (-px/-sx) and Lowercase (-l) rename outputs; Out type (-ft) can
export tga/png/hdr instead of dds; Header picks DX10 (needed for BC7/arrays) or
legacy DX9.

── Batch behaviour ──
  • Threads — how many images convert in parallel (clamped to your CPU range).
  • Dry run — log the exact command per file without writing anything; ideal for
    sanity-checking before a large batch.
  • Collision guard — if two sources would resolve to the same .dds (same name in
    different subfolders with Mirror off, or tex.png + tex.tga in one folder), the
    run is refused with the offenders listed rather than silently overwriting.
    Enable Mirror structure or add a prefix/suffix to disambiguate.
  • Show command previews the full invocation; Save log writes the run log to disk.

Hover any control for a one-line description of the flag it maps to.
"""


class TexconvPanel(ToolPanel):
    TOOL = "texconv"
    CONFIG = "texconv.json"
    RUN_LABEL = "Convert  →  DDS (texconv)"
    HELP_TITLE = "Texconv · Guide"
    HELP_TEXT = TEXCONV_HELP

    def _make_vars(self):
        self._dir_var = tk.StringVar(); self._out_var = tk.StringVar()
        self._fmt_var = tk.StringVar(value="BC3_UNORM")
        self._filter_var = tk.StringVar(value="FANT")
        self._ft_var = tk.StringVar(value="dds")
        self._mips_var = tk.IntVar(value=0)
        self._workers_var = tk.IntVar(value=self._default_workers)
        self._colorspace_var = tk.StringVar(value="Linear")
        self._recursive_var = tk.BooleanVar(value=True)
        self._mirror_var = tk.BooleanVar(value=True)
        self._overwrite_var = tk.BooleanVar(value=False)
        self._dryrun_var = tk.BooleanVar(value=False)
        self._coverage_var = tk.BooleanVar(value=False)
        self._alpha_ref_var = tk.DoubleVar(value=0.5)
        self._sepalpha_var = tk.BooleanVar(value=False)
        self._pmalpha_var = tk.BooleanVar(value=False)
        self._straight_var = tk.BooleanVar(value=False)
        self._ignore_srgb_var = tk.BooleanVar(value=False)
        self._bc_d = tk.BooleanVar(value=False); self._bc_u = tk.BooleanVar(value=False)
        self._bc_q = tk.BooleanVar(value=False); self._bc_x = tk.BooleanVar(value=False)
        self._use_aw_var = tk.BooleanVar(value=False); self._aw_var = tk.DoubleVar(value=1.0)
        self._width_var = tk.StringVar(); self._height_var = tk.StringVar()
        self._pow2_var = tk.BooleanVar(value=False)
        self._fl_var = tk.StringVar(value="Default"); self._header_var = tk.StringVar(value="Default")
        self._dword_var = tk.BooleanVar(value=False)
        self._hflip_var = tk.BooleanVar(value=False); self._vflip_var = tk.BooleanVar(value=False)
        self._invy_var = tk.BooleanVar(value=False); self._reconz_var = tk.BooleanVar(value=False)
        self._x2_var = tk.BooleanVar(value=False); self._swizzle_var = tk.StringVar()
        self._nmap_var = tk.BooleanVar(value=False); self._nmap_opts_var = tk.StringVar(value="rgb")
        self._nmapamp_var = tk.DoubleVar(value=1.0)
        self._prefix_var = tk.StringVar(); self._suffix_var = tk.StringVar()
        self._lower_var = tk.BooleanVar(value=False); self._addr_var = tk.StringVar(value="clamp")
        self._colorkey_var = tk.StringVar()
        self._tu_var = tk.BooleanVar(value=False); self._tf_var = tk.BooleanVar(value=False)
        self._badtails_var = tk.BooleanVar(value=False); self._permissive_var = tk.BooleanVar(value=False)
        self._ignoremips_var = tk.BooleanVar(value=False); self._fixbc_var = tk.BooleanVar(value=False)
        self._xlum_var = tk.BooleanVar(value=False)
        self._rotate_var = tk.StringVar(value=""); self._nits_var = tk.StringVar()
        self._tonemap_var = tk.BooleanVar(value=False)
        self._nogpu_var = tk.BooleanVar(value=False); self._gpu_var = tk.StringVar()
        self._single_var = tk.BooleanVar(value=False); self._timing_var = tk.BooleanVar(value=False)
        self._nowic_var = tk.BooleanVar(value=False)
        # Enable toggles for value fields (off → field disabled, flag omitted).
        self._mips_en_var = tk.BooleanVar(value=False)
        self._width_en_var = tk.BooleanVar(value=False)
        self._height_en_var = tk.BooleanVar(value=False)
        self._nits_en_var = tk.BooleanVar(value=False)
        self._gpu_en_var = tk.BooleanVar(value=False)
        self._swizzle_en_var = tk.BooleanVar(value=False)
        self._colorkey_en_var = tk.BooleanVar(value=False)
        self._prefix_en_var = tk.BooleanVar(value=False)
        self._suffix_en_var = tk.BooleanVar(value=False)
        self._cfg_map = {k: getattr(self, k) for k in vars(self) if k.endswith("_var")}

    def _build_controls(self, parent):
        cfg = ttk.Frame(parent); cfg.pack(fill="x", padx=10, pady=(10, 4)); cfg.columnconfigure(1, weight=1)
        self._dir_entry = self._path_row(cfg, 0, "Source target", self._dir_var,
                                         on_folder=lambda: self._browse_into(self._dir_var, "dir", "Source folder"),
                                         on_file=lambda: self._browse_into(self._dir_var, "file", "Source image"))
        self._path_row(cfg, 1, "Output folder", self._out_var,
                       browse=lambda: self._browse_into(self._out_var, "dir", "Output folder"))
        self._path_row(cfg, 2, "texconv path", self._exe_var,
                       test=self._test_exe, browse=lambda: self._browse_exe_into(self._exe_var, "Locate texconv"))
        self._setup_dnd(self._dir_entry, self._dir_var)

        opt = ttk.Frame(parent); opt.pack(fill="x", padx=10, pady=(6, 0))
        def row():
            r = ttk.Frame(opt); r.pack(fill="x", pady=(0, 6)); return r

        r = row()
        self._fmt_cb = self._combo(r, "Format", self._fmt_var, TEXCONV_FORMATS, 22,
            "DDS pixel format to compress to. BC1 = opaque or 1-bit alpha (smallest), BC3 = full alpha, "
            "BC4/BC5 = 1- and 2-channel (great for normals), BC6H = HDR, BC7 = highest-quality RGBA (-f).", self._toggle_aw)
        self._combo(r, "Filter", self._filter_var, FILTERS, 16,
            "Resampling filter used when resizing and building mipmaps. FANT (box) is a safe default; "
            "LINEAR/CUBIC/TRIANGLE trade speed for smoothness (-if).")
        self._combo(r, "Out type", self._ft_var, FILETYPES, 6,
            "File container written to disk — normally DDS. Choosing TGA/HDR/PNG etc. exports the decoded image instead (-ft).")
        self._opt_spin(r, "Mips", self._mips_en_var, self._mips_var, 0, 16, 1, "%.0f", 4,
            "How many mipmap levels to generate: 0 = full chain down to 1×1, 1 = base image only (-m).")
        self._workers_spin = ttk.Spinbox(r, from_=1, to=self._cpu_limit, textvariable=self._workers_var, width=4)
        self._workers_spin.pack(side="right"); ToolTip(self._workers_spin, "How many images to convert in parallel. Higher uses more CPU and memory.")
        ttk.Label(r, text="Threads").pack(side="right", padx=(6, 0))

        r = row()
        self._recursive_chk = self._chk(r, "Recursive scan", self._recursive_var, "Search every subfolder of the source for images, not just the top level.", self._toggle_mirror)
        self._mirror_chk = self._chk(r, "Mirror structure", self._mirror_var, "Recreate the source's subfolder layout inside the output folder instead of flattening everything together.")
        self._chk(r, "Overwrite existing", self._overwrite_var, "Replace DDS files that already exist instead of skipping them (-y).")
        self._chk(r, "Dry run", self._dryrun_var, "Show the command that would run for each file without actually writing any output.")

        r = row()
        self._combo(r, "Colour", self._colorspace_var, list(COLORSPACE_MAP.keys()), 9,
            "How colour space is handled: sRGB marks data as gamma-encoded, sRGB in/out convert on read/write; "
            "Linear leaves the pixels untouched (-srgb / -srgbi / -srgbo).")
        self._chk(r, "Ignore sRGB meta", self._ignore_srgb_var, "Ignore any sRGB tag in the source and treat the pixels exactly as stored (--ignore-srgb).")
        self._chk(r, "Premultiply alpha", self._pmalpha_var, "Multiply colour by alpha before compressing, for a premultiplied-alpha workflow (-pmalpha).")
        self._chk(r, "Straight alpha", self._straight_var, "Convert premultiplied-alpha input back to straight (non-premultiplied) alpha (-alpha).")
        self._chk(r, "Expand luminance", self._xlum_var, "Expand legacy luminance formats (L8, L16, A8P8) into full RGBA (-xlum).")

        r = row()
        self._coverage_chk = self._chk(r, "Preserve alpha coverage", self._coverage_var,
                                       "Scale each mip's alpha so the proportion of pixels passing the alpha test stays constant — stops "
                                       "alpha-tested foliage, fences and chain-link thinning out in the distance (--keep-coverage).", self._toggle_coverage)
        self._alpha_ref_spin = self._spin(r, "Alpha ref", self._alpha_ref_var, 0.0, 1.0, 0.05, "%.2f", 6,
                                          "Alpha-test cutoff (0–1) used by Preserve alpha coverage and written as the reference (-at). 0.5 is typical.")
        self._chk(r, "Separate alpha", self._sepalpha_var, "Resize and mip the alpha channel independently of colour, giving crisper alpha-test edges (-sepalpha).")

        r = row()
        self._chk(r, "BC dither", self._bc_d, "Add dithering during block compression to reduce visible banding (-bc d).")
        self._chk(r, "BC uniform", self._bc_u, "Weight RGB error equally instead of perceptually when compressing (-bc u).")
        self._chk(r, "BC quick", self._bc_q, "Faster, lower-quality BC7 compression (-bc q).")
        self._chk(r, "BC max", self._bc_x, "Slowest, maximum-quality BC7 compression (-bc x).")
        self._aw_chk = self._chk(r, "BC7 alpha weight", self._use_aw_var, "Bias BC7 to spend more bits on the alpha channel (BC7 formats only) (-aw).", self._toggle_aw)
        self._aw_spin = self._spin(r, "", self._aw_var, 0.1, 8.0, 0.1, "%.2f", 6, "BC7 alpha error weight — higher preserves alpha detail at the cost of colour (-aw).", state="disabled")

        r = row()
        self._opt_entry(r, "Width", self._width_en_var, self._width_var, 6, "Resize output to this width in pixels. Off = keep the source width (-w).")
        self._opt_entry(r, "Height", self._height_en_var, self._height_var, 6, "Resize output to this height in pixels. Off = keep the source height (-h).")
        self._chk(r, "Fit pow-of-2", self._pow2_var, "Round the output dimensions up to the nearest power of two (-pow2).")
        self._combo(r, "Feature lvl", self._fl_var, FEATURE_LEVELS, 8, "Clamp the maximum texture size to a Direct3D feature level's limit (-fl).")
        self._combo(r, "Header", self._header_var, list(HEADER_MAP.keys()), 8, "DDS header to write: DX10 (extended, required for BC7 and arrays) or legacy DX9 (-dx10 / -dx9).")
        self._chk(r, "DWORD align", self._dword_var, "Align each scanline to a 4-byte (DWORD) boundary in legacy DDS output (-dword).")

        r = row()
        self._chk(r, "H-flip", self._hflip_var, "Mirror the image left-to-right (-hflip).")
        self._chk(r, "V-flip", self._vflip_var, "Flip the image top-to-bottom (-vflip).")
        self._chk(r, "Invert Y", self._invy_var, "Invert the green channel — flips a normal map between OpenGL and DirectX conventions (--invert-y).")
        self._chk(r, "Reconstruct Z", self._reconz_var, "Rebuild the blue/Z channel of a normal map from R and G (for BC5 two-channel normals) (--reconstruct-z).")
        self._chk(r, "×2−1 bias", self._x2_var, "Remap values from 0..1 to −1..1, the signed range normal maps expect (--x2-bias).")
        self._opt_entry(r, "Swizzle", self._swizzle_en_var, self._swizzle_var, 8, "Reorder or duplicate channels with a 4-letter mask, e.g. rgba, bgra, rrrg (--swizzle).")

        r = row()
        self._nmap_chk = self._chk(r, "Height → normal", self._nmap_var, "Generate a tangent-space normal map from the input treated as a height/bump map (-nmap).", self._toggle_nmap)
        self._nmap_opts_entry = self._entry(r, "nmap opts", self._nmap_opts_var, 8, "Channels and options for normal generation: r/g/b/a/l pick the height source; m/u/v/i/o set mirror/wrap/invert (-nmap).")
        self._nmapamp_spin = self._spin(r, "Amplitude", self._nmapamp_var, 0.1, 20.0, 0.5, "%.2f", 6, "Bump strength when converting height → normal; higher gives steeper normals (-nmapamp).", state="disabled")
        self._combo(r, "Rotate colour", self._rotate_var, ROTATE_OPTS, 14, "Convert between HDR colour primaries / transfer functions, e.g. Rec.709 ↔ Rec.2020 / HDR10 (--rotate-color).")

        r = row()
        self._chk(r, "Tonemap", self._tonemap_var, "Apply a Reinhard tone-map when converting HDR down to an SDR format (--tonemap).")
        self._opt_entry(r, "Paper-white nits", self._nits_en_var, self._nits_var, 6, "HDR10 paper-white luminance in nits used during tone-mapping, default 200 (-nits).")
        self._chk(r, "Typeless→UNORM", self._tu_var, "Read typeless source formats as UNORM (normalised unsigned) (-tu).")
        self._chk(r, "Typeless→FLOAT", self._tf_var, "Read typeless source formats as floating-point (-tf).")
        self._opt_entry(r, "Colour key", self._colorkey_en_var, self._colorkey_var, 8, "Make this hex RGB colour fully transparent, e.g. ff00ff for magenta (-c).")

        r = row()
        self._opt_entry(r, "Prefix", self._prefix_en_var, self._prefix_var, 9, "Text added to the start of every output filename (-px).")
        self._opt_entry(r, "Suffix", self._suffix_en_var, self._suffix_var, 9, "Text added to the end of every output filename, before the extension (-sx).")
        self._chk(r, "Lowercase", self._lower_var, "Force output filenames to lowercase (-l).")
        self._combo(r, "Addressing", self._addr_var, list(ADDRESSING_MAP.keys()), 8, "Edge addressing assumed when filtering: clamp, wrap (tile) or mirror (-wrap / -mirror).")

        r = row()
        self._chk(r, "Bad tails", self._badtails_var, "Work around DDS input whose smallest mip levels are stored incorrectly (--bad-tails).")
        self._chk(r, "Permissive", self._permissive_var, "Accept slightly malformed DDS input that would otherwise be rejected (--permissive).")
        self._chk(r, "Ignore mips", self._ignoremips_var, "Discard any mipmaps in the DDS input and keep only the base image (--ignore-mips).")
        self._chk(r, "Fix BC 4x4", self._fixbc_var, "Repair block-compressed DDS input whose dimensions aren't multiples of 4 (--fix-bc-4x4).")

        r = row()
        self._chk(r, "No GPU", self._nogpu_var, "Disable GPU-accelerated BC6H/BC7 compression and use the CPU instead (-nogpu).")
        self._opt_entry(r, "GPU #", self._gpu_en_var, self._gpu_var, 4, "Index of the GPU adapter to use for compression (-gpu).")
        self._chk(r, "Single-proc", self._single_var, "Run texconv's own compression single-threaded (--single-proc).")
        self._chk(r, "Timing", self._timing_var, "Print how long the conversion took (--timing).")
        self._chk(r, "Non-WIC", self._nowic_var, "Use texconv's built-in image loaders instead of Windows WIC codecs (-nowic).")

    def _post_init(self):
        self._toggle_coverage(); self._toggle_aw(); self._toggle_nmap(); self._toggle_mirror()

    def _toggle_coverage(self):
        self._alpha_ref_spin.configure(state="normal" if self._coverage_var.get() else "disabled")

    def _toggle_aw(self):
        bc7 = self._fmt_var.get().startswith("BC7")
        self._aw_chk.configure(state="normal" if bc7 else "disabled")
        self._aw_spin.configure(state="normal" if (bc7 and self._use_aw_var.get()) else "disabled")

    def _toggle_nmap(self):
        st = "normal" if self._nmap_var.get() else "disabled"
        self._nmap_opts_entry.configure(state=st); self._nmapamp_spin.configure(state=st)

    def _toggle_mirror(self):
        st = "normal" if self._recursive_var.get() else "disabled"
        self._mirror_chk.configure(state=st)
        if st == "disabled":
            self._mirror_var.set(False)

    def _gather_opts(self) -> TexconvOpts:
        """Snapshot all Tk variables into a frozen TexconvOpts on the MAIN
        thread. Numeric reads go through the safe helpers so a cleared spinbox
        falls back to a sane default rather than raising."""
        v = self
        return TexconvOpts(
            exe=v._exe_var.get().strip() or "texconv",
            ft=v._ft_var.get(),
            fmt=v._fmt_var.get(),
            mips=(int(self._float_or(v._mips_var, 0)) if v._mips_en_var.get() else None),
            filt=v._filter_var.get(),
            colorspace=v._colorspace_var.get(),
            ignore_srgb=v._ignore_srgb_var.get(),
            xlum=v._xlum_var.get(),
            coverage=v._coverage_var.get(),
            alpha_ref=self._float_or(v._alpha_ref_var, 0.5),
            sepalpha=v._sepalpha_var.get(),
            pmalpha=v._pmalpha_var.get(),
            straight=v._straight_var.get(),
            bc_d=v._bc_d.get(), bc_u=v._bc_u.get(), bc_q=v._bc_q.get(), bc_x=v._bc_x.get(),
            use_aw=v._use_aw_var.get(),
            aw=self._float_or(v._aw_var, 1.0),
            width=(self._int_or_none(v._width_var.get()) if v._width_en_var.get() else None),
            height=(self._int_or_none(v._height_var.get()) if v._height_en_var.get() else None),
            pow2=v._pow2_var.get(),
            fl=v._fl_var.get(),
            header=v._header_var.get(),
            dword=v._dword_var.get(),
            hflip=v._hflip_var.get(), vflip=v._vflip_var.get(),
            invy=v._invy_var.get(), reconz=v._reconz_var.get(), x2=v._x2_var.get(),
            swizzle=(v._swizzle_var.get().strip() if v._swizzle_en_var.get() else ""),
            nmap=v._nmap_var.get(),
            nmap_opts=v._nmap_opts_var.get().strip() or "rgb",
            nmapamp=self._float_or(v._nmapamp_var, 1.0),
            rotate=v._rotate_var.get(),
            nits=(v._nits_var.get().strip() if v._nits_en_var.get() else ""),
            tonemap=v._tonemap_var.get(),
            tu=v._tu_var.get(), tf=v._tf_var.get(),
            badtails=v._badtails_var.get(), permissive=v._permissive_var.get(),
            ignoremips=v._ignoremips_var.get(), fixbc=v._fixbc_var.get(),
            colorkey=(v._colorkey_var.get().strip() if v._colorkey_en_var.get() else ""),
            addr=v._addr_var.get(),
            prefix=(v._prefix_var.get().strip() if v._prefix_en_var.get() else ""),
            suffix=(v._suffix_var.get().strip() if v._suffix_en_var.get() else ""),
            lower=v._lower_var.get(),
            nogpu=v._nogpu_var.get(),
            gpu=(self._int_or_none(v._gpu_var.get()) if v._gpu_en_var.get() else None),
            single=v._single_var.get(), timing=v._timing_var.get(), nowic=v._nowic_var.get(),
            overwrite=v._overwrite_var.get(),
        )

    @staticmethod
    def _build_cmd(o: TexconvOpts, src, out_dir) -> list:
        """Pure command builder: a function of (opts, src, out_dir) only — no Tk,
        no instance state. Keep flag order identical to texconv's expectations."""
        cmd = [o.exe, "-nologo", "-ft", o.ft, "-f", o.fmt]
        if o.mips is not None: cmd += ["-m", str(o.mips)]
        if o.filt: cmd += ["-if", o.filt]
        cs = COLORSPACE_MAP.get(o.colorspace, "")
        if cs: cmd.append(cs)
        if o.ignore_srgb: cmd.append("--ignore-srgb")
        if o.xlum: cmd.append("-xlum")
        if o.coverage:
            ref = f"{o.alpha_ref:.3f}"; cmd += ["--keep-coverage", ref, "-at", ref]
        if o.sepalpha: cmd.append("-sepalpha")
        if o.pmalpha: cmd.append("-pmalpha")
        if o.straight: cmd.append("-alpha")
        bc = "".join(l for l, on in (("d", o.bc_d), ("u", o.bc_u), ("q", o.bc_q), ("x", o.bc_x)) if on)
        if bc: cmd += ["-bc", bc]
        if o.fmt.startswith("BC7") and o.use_aw:
            cmd += ["-aw", f"{o.aw:.2f}"]
        if o.width is not None: cmd += ["-w", str(o.width)]
        if o.height is not None: cmd += ["-h", str(o.height)]
        if o.pow2: cmd.append("-pow2")
        if o.fl != "Default": cmd += ["-fl", o.fl]
        hd = HEADER_MAP.get(o.header, "")
        if hd: cmd.append(hd)
        if o.dword: cmd.append("-dword")
        if o.hflip: cmd.append("-hflip")
        if o.vflip: cmd.append("-vflip")
        if o.invy: cmd.append("--invert-y")
        if o.reconz: cmd.append("--reconstruct-z")
        if o.x2: cmd.append("--x2-bias")
        if o.swizzle: cmd += ["--swizzle", o.swizzle]
        if o.nmap:
            cmd += ["-nmap", o.nmap_opts, "-nmapamp", f"{o.nmapamp:.2f}"]
        if o.rotate: cmd += ["--rotate-color", o.rotate]
        if o.nits: cmd += ["-nits", o.nits]
        if o.tonemap: cmd.append("--tonemap")
        if o.tu: cmd.append("-tu")
        if o.tf: cmd.append("-tf")
        if o.badtails: cmd.append("--bad-tails")
        if o.permissive: cmd.append("--permissive")
        if o.ignoremips: cmd.append("--ignore-mips")
        if o.fixbc: cmd.append("--fix-bc-4x4")
        if o.colorkey: cmd += ["-c", o.colorkey]
        ad = ADDRESSING_MAP.get(o.addr, "")
        if ad: cmd.append(ad)
        if o.prefix: cmd += ["-px", o.prefix]
        if o.suffix: cmd += ["-sx", o.suffix]
        if o.lower: cmd.append("-l")
        if o.nogpu: cmd.append("-nogpu")
        if o.gpu is not None: cmd += ["-gpu", str(o.gpu)]
        if o.single: cmd.append("--single-proc")
        if o.timing: cmd.append("--timing")
        if o.nowic: cmd.append("-nowic")
        if o.overwrite: cmd.append("-y")
        cmd += ["-o", str(out_dir), str(src)]
        return cmd

    def _preview_command(self):
        sample = Path(self._dir_var.get().strip() or "example.png")
        if sample.suffix.lower() not in IMAGE_EXTS:
            sample = sample / "example.png"
        out = Path(self._out_var.get().strip() or sample.parent)
        cmd = self._build_cmd(self._gather_opts(), sample, out)
        self._head("Preview command:")
        self._log_line("  " + " ".join(f'"{c}"' if " " in c else c for c in cmd), "dim")

    def _start(self):
        if self._running:
            return
        exe = self._resolve_exe()
        if not exe:
            self._fail("texconv not found. Set its path or put it on PATH."); return
        self._exe_var.set(exe)
        directory = self._dir_var.get().strip()
        if not directory:
            self._warn("No source selected."); return
        in_path = Path(directory)
        if not in_path.exists():
            self._fail("Source path does not exist."); return
        if in_path.is_file():
            files = [in_path]; source_root = in_path.parent
        else:
            source_root = in_path
            files = _collect(source_root, {".png", ".tga", ".bmp", ".jpg", ".jpeg", ".tif", ".tiff", ".hdr", ".dds"},
                             self._recursive_var.get())
        if not files:
            self._fail("No image files found."); return
        out_target = self._out_var.get().strip()
        out_dir = Path(out_target) if out_target else None
        mirror = self._mirror_var.get()
        dry = self._dryrun_var.get()

        # Snapshot every Tk variable ONCE on the main thread; workers use only the
        # resulting frozen opts + prebuilt command lists, never Tk.
        opts = self._gather_opts()
        ft, fmt, overwrite = opts.ft, opts.fmt, opts.overwrite

        specs = []
        for src in files:
            if out_dir:
                tgt = out_dir / src.relative_to(source_root).parent if (mirror and src.is_relative_to(source_root)) else out_dir
            else:
                tgt = src.parent
            stem = opts.prefix + src.stem + opts.suffix
            if opts.lower:
                stem = stem.lower()
            predicted = tgt / f"{stem}.{ft}"
            specs.append((src, tgt, predicted, stem, self._build_cmd(opts, src, tgt)))

        # Don't let texconv overwrite a source with its own output (same folder,
        # name and extension — e.g. re-compressing a .dds in place).
        _n0 = len(specs)
        specs = [s for s in specs if os.path.normcase(str(s[2])) != os.path.normcase(str(s[0]))]
        if len(specs) < _n0:
            self._warn(f"Skipped {_n0 - len(specs)} file(s) whose output would overwrite the source in place.")
        if not specs:
            self._fail("Nothing to convert — every output would overwrite its source."); return

        # Heads-up if the output sits inside a recursively-scanned source: a later
        # re-run would pick these outputs back up (.dds is itself an input type).
        if out_dir and self._recursive_var.get():
            try:
                if out_dir.resolve().is_relative_to(source_root.resolve()):
                    self._warn("Output folder is inside the source — a re-run may re-convert these outputs.")
            except (ValueError, OSError):
                pass

        # Guard against silent-overwrite data loss: with mirroring off and
        # recursive on, identically named files in different subfolders collapse
        # onto one output path. Detect that up front and refuse rather than lose
        # data — texconv's parallel workers could otherwise race and clobber.
        # A dry run writes nothing, so collisions are harmless there — let it
        # through (warned below) so the colliding commands can still be previewed.
        dupes = self._flat_collisions([s[2] for s in specs])
        if dupes and not dry:
            self._clear_log()
            self._fail(f"{len(dupes)} output-name collision(s) — sources would overwrite each other:")
            for p, n in dupes[:6]:
                self._log_line(f"    {n}× → {Path(p).name}", "warn")
            if out_dir and not mirror and self._recursive_var.get():
                self._warn("Enable “Mirror subfolders” to keep them in separate output folders.")
            else:
                self._warn("Use a prefix/suffix or distinct output folders to disambiguate.")
            return

        workers = max(1, min(int(self._float_or(self._workers_var, self._default_workers)), self._cpu_limit, len(specs)))
        log.debug("texconv: start — source=%s, %d file(s), out=%s, mirror=%s, workers=%d, fmt=%s",
                  source_root, len(specs), out_dir, mirror, workers, fmt)
        self._arm(len(specs))
        self._head(f"▶ texconv · {len(specs)} files · {workers} threads · {fmt}")
        if dupes:   # dry run only — a real run with collisions already returned above
            self._warn(f"{len(dupes)} output-name collision(s) — a real run would overwrite; dry run previews only.")

        def job(spec):
            src, tgt, predicted, stem, cmd = spec
            label = f"{src.name} → {predicted.name} [{fmt}]"
            if predicted.exists() and not overwrite and not dry:
                return False, f"{src.name}  [skipped: exists]"
            if dry:
                return True, f"[dry] {label}"
            tgt.mkdir(parents=True, exist_ok=True)
            rc, out = run_proc(cmd, self._active, self._lock, self._cancel)
            if rc == 0 and (predicted.exists() or (tgt / f"{stem}.{ft.upper()}").exists()):
                return True, label
            return False, f"{label}\n      ↳ {(out.strip().splitlines() or ['failed'])[-1]}"

        self._run_parallel(specs, job, workers)


# ══════════════════════════════════════════════════════════════════════════════
#  TEXASSEMBLE
# ══════════════════════════════════════════════════════════════════════════════
ASSEMBLE_COMMANDS = [
    "cube", "volume", "array", "cubearray", "h-cross", "v-cross", "v-cross-fnz",
    "h-tee", "h-strip", "v-strip", "array-strip", "merge", "gif",
    "cube-from-hc", "cube-from-vc", "cube-from-vc-fnz", "cube-from-ht",
    "cube-from-hs", "cube-from-vs", "from-mips", "cube-from-mips",
]


@dataclass(frozen=True)
class TexassembleOpts:
    """Immutable snapshot of texassemble settings, taken on the main thread."""
    exe: str
    cmd: str
    fmt: str
    filt: str
    colorspace: str
    width: int | None
    height: int | None
    mips: int | None
    fl: str
    recursive: bool
    sepalpha: bool
    alpha: bool
    dx10: bool
    tonemap: bool
    gifbg: bool
    stripmips: bool
    nowic: bool
    addr: str
    swizzle: str
    lower: bool
    overwrite: bool
    out: str


TEXASSEMBLE_HELP = """\
Texassemble · Guide

texassemble builds composite DDS textures — cubemaps, arrays, volumes and more —
from a set of input images. This tab exposes every command and option.

── Getting started ──
1. texassemble path — point at the executable (or leave the default if it's on
   PATH); Test confirms it's found.
2. Command — choose the operation (see below).
3. Input files / folder — pick a folder, or use File… to select several images.
   ORDER MATTERS: for "cube" the inputs are the six faces in +X −X +Y −Y +Z −Z
   order; for array/volume it's the slice order. Drag & drop also works.
4. Output file — the .dds to write. Click Assemble.

── Commands ──
  • cube / cubearray — build a cubemap (6 faces) or an array of cubemaps.
  • array — stack images into a texture array.
  • volume — build a 3-D (volume) texture from slices.
  • merge — combine channels from several files into one (see Swizzle).
  • gif — assemble frames into an animated-GIF-style array.
  • h-cross / v-cross / h-tee / h-strip / v-strip / array-strip — lay the faces
    out into a single cross or strip image.
  • cube-from-hc / -vc / -ht / -hs / -vs — the inverse: split a cross or strip
    image back into the six cube faces.
  • from-mips / cube-from-mips — assemble using each input's mip levels.

── Key options ──
  • Format (-f) — pixel format of the result (the same set as texconv).
  • Width / Height (-w / -h) — force every input to a common size first.
  • Mips (-m) — mip count, used by the *-from-mips commands.
  • Swizzle (--swizzle) — for merge, the 4-letter mask choosing which source
    channel feeds each output channel.
  • DX10 header (-dx10) — required for arrays and cubemap arrays.
  • Separate alpha, Straight alpha, Addressing, Feature level — as in texconv.
  • Tonemap / GIF bg colour — for the gif command.

Value fields (Width/Height/Mips/Swizzle) apply only when their checkbox is ticked.
Hover any control for the flag it maps to.
"""


class TexassemblePanel(ToolPanel):
    TOOL = "texassemble"
    CONFIG = "texassemble.json"
    RUN_LABEL = "Assemble"
    HELP_TITLE = "Texassemble · Guide"
    HELP_TEXT = TEXASSEMBLE_HELP

    def _make_vars(self):
        self._cmd_var = tk.StringVar(value="cube")
        self._inputs_var = tk.StringVar()      # folder or ; separated files
        self._out_var = tk.StringVar()
        self._fmt_var = tk.StringVar(value="R8G8B8A8_UNORM")
        self._filter_var = tk.StringVar(value="FANT")
        self._width_var = tk.StringVar(); self._height_var = tk.StringVar()
        self._mips_var = tk.StringVar()
        self._colorspace_var = tk.StringVar(value="Linear")
        self._fl_var = tk.StringVar(value="Default")
        self._recursive_var = tk.BooleanVar(value=False)
        self._overwrite_var = tk.BooleanVar(value=False)
        self._lower_var = tk.BooleanVar(value=False)
        self._sepalpha_var = tk.BooleanVar(value=False)
        self._nowic_var = tk.BooleanVar(value=False)
        self._addr_var = tk.StringVar(value="clamp")
        self._alpha_var = tk.BooleanVar(value=False)
        self._dx10_var = tk.BooleanVar(value=True)
        self._tonemap_var = tk.BooleanVar(value=False)
        self._gifbg_var = tk.BooleanVar(value=False)
        self._swizzle_var = tk.StringVar()
        self._stripmips_var = tk.BooleanVar(value=False)
        # Enable toggles for value fields (off → field disabled, flag omitted).
        self._width_en_var = tk.BooleanVar(value=False)
        self._height_en_var = tk.BooleanVar(value=False)
        self._mips_en_var = tk.BooleanVar(value=False)
        self._swizzle_en_var = tk.BooleanVar(value=False)
        self._cfg_map = {k: getattr(self, k) for k in vars(self) if k.endswith("_var")}

    def _build_controls(self, parent):
        cfg = ttk.Frame(parent); cfg.pack(fill="x", padx=10, pady=(10, 4)); cfg.columnconfigure(1, weight=1)
        ttk.Label(cfg, text="Command").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        cb = ttk.Combobox(cfg, textvariable=self._cmd_var, values=ASSEMBLE_COMMANDS, state="readonly", width=20)
        cb.grid(row=0, column=1, sticky="w", padx=(8, 6)); ToolTip(cb,
            "Which texassemble operation to run: cube/cubearray build cubemaps, array stacks images into a texture array, "
            "volume builds a 3-D texture, merge combines channels from several files, gif makes an animated GIF, and the "
            "cube-from-* commands split a cross or strip layout into the six cube faces.")
        self._inputs_entry = self._path_row(cfg, 1, "Input files / folder", self._inputs_var,
                                            on_folder=lambda: self._browse_into(self._inputs_var, "dir", "Input folder"),
                                            on_file=self._pick_files)
        self._path_row(cfg, 2, "Output file", self._out_var,
                       browse=lambda: self._browse_into(self._out_var, "file", "Output DDS"))
        self._path_row(cfg, 3, "texassemble path", self._exe_var,
                       test=self._test_exe, browse=lambda: self._browse_exe_into(self._exe_var, "Locate texassemble"))
        self._setup_dnd(self._inputs_entry, self._inputs_var)
        ttk.Label(cfg, text="Tip: pick a folder, or File… to choose several; order matters for cube faces.",
                  style="Dim.TLabel").grid(row=4, column=1, sticky="w", padx=(8, 0))

        opt = ttk.Frame(parent); opt.pack(fill="x", padx=10, pady=(6, 0))
        def row():
            r = ttk.Frame(opt); r.pack(fill="x", pady=(0, 6)); return r
        r = row()
        self._combo(r, "Format", self._fmt_var, ASSEMBLE_FORMATS, 22, "Pixel format of the assembled DDS — the same format set as texconv (-f).")
        self._combo(r, "Filter", self._filter_var, FILTERS, 16, "Resampling filter used if the inputs need resizing to a common size (-if).")
        self._combo(r, "Colour", self._colorspace_var, list(COLORSPACE_MAP.keys()), 9, "Colour-space handling for the inputs — sRGB (gamma) vs Linear.")
        self._combo(r, "Feature lvl", self._fl_var, FEATURE_LEVELS, 8, "Clamp the result to a Direct3D feature level's maximum texture size (-fl).")
        r = row()
        self._opt_entry(r, "Width", self._width_en_var, self._width_var, 6, "Force each input to this width before assembling (-w).")
        self._opt_entry(r, "Height", self._height_en_var, self._height_var, 6, "Force each input to this height before assembling (-h).")
        self._opt_entry(r, "Mips", self._mips_en_var, self._mips_var, 5, "Number of mip levels to read per input — only used by the *-from-mips commands (-m).")
        self._combo(r, "Addressing", self._addr_var, list(ADDRESSING_MAP.keys()), 8, "Edge addressing assumed when filtering: clamp, wrap (tile) or mirror (-wrap / -mirror).")
        self._opt_entry(r, "Swizzle", self._swizzle_en_var, self._swizzle_var, 8, "Channel-select mask the merge command uses to pick which source channel goes where (--swizzle).")
        r = row()
        self._chk(r, "Recursive", self._recursive_var, "When the input is a folder, search its subfolders for images too (-r).")
        self._chk(r, "Overwrite", self._overwrite_var, "Replace the output file if it already exists (-y).")
        self._chk(r, "Lowercase", self._lower_var, "Force the output filename to lowercase (-l).")
        self._chk(r, "Separate alpha", self._sepalpha_var, "Process the alpha channel separately from colour when resizing (-sepalpha).")
        self._chk(r, "DX10 header", self._dx10_var, "Write the extended DX10 DDS header — required for arrays and cubemap arrays (-dx10).")
        r = row()
        self._chk(r, "Straight alpha", self._alpha_var, "Treat the input alpha as straight (non-premultiplied) (-alpha).")
        self._chk(r, "Tonemap (gif)", self._tonemap_var, "Tone-map HDR inputs when building an animated GIF (-tonemap).")
        self._chk(r, "GIF bg colour", self._gifbg_var, "Composite transparent GIF frames over a solid background colour (--gif-bg-color).")
        self._chk(r, "Strip mips", self._stripmips_var, "Drop any mipmaps from the inputs before assembling (--strip-mips).")
        self._chk(r, "Non-WIC", self._nowic_var, "Use built-in image loaders instead of Windows WIC codecs (-nowic).")

    def _pick_files(self):
        ps = filedialog.askopenfilenames(title="Select input images (order matters)")
        if ps:
            files = [Path(os.path.normpath(p)) for p in ps]
            # Keep the exact list so _input_list doesn't have to re-parse the
            # display string (which would mis-split a path containing ';').
            self._picked_files = files
            self._inputs_var.set(";".join(str(f) for f in files))

    def _input_list(self):
        raw = self._inputs_var.get().strip()
        if not raw:
            return []
        # Prefer the precise picked list while the field still shows exactly what
        # we set — this is the only reliable handling for paths that contain ';'.
        picked = getattr(self, "_picked_files", None)
        if picked and raw == ";".join(str(f) for f in picked):
            return list(picked)
        if ";" in raw:
            return [Path(p) for p in raw.split(";") if p.strip()]
        p = Path(raw)
        if p.is_dir():
            return _collect(p, IMAGE_EXTS, self._recursive_var.get())
        return [p]

    def _gather_opts(self) -> TexassembleOpts:
        """Snapshot all Tk variables into a frozen TexassembleOpts (main thread)."""
        v = self
        return TexassembleOpts(
            exe=v._exe_var.get().strip() or "texassemble",
            cmd=v._cmd_var.get(),
            fmt=v._fmt_var.get(),
            filt=v._filter_var.get(),
            colorspace=v._colorspace_var.get(),
            width=(self._int_or_none(v._width_var.get()) if v._width_en_var.get() else None),
            height=(self._int_or_none(v._height_var.get()) if v._height_en_var.get() else None),
            mips=(self._int_or_none(v._mips_var.get()) if v._mips_en_var.get() else None),
            fl=v._fl_var.get(),
            recursive=v._recursive_var.get(),
            sepalpha=v._sepalpha_var.get(),
            alpha=v._alpha_var.get(),
            dx10=v._dx10_var.get(),
            tonemap=v._tonemap_var.get(),
            gifbg=v._gifbg_var.get(),
            stripmips=v._stripmips_var.get(),
            nowic=v._nowic_var.get(),
            addr=v._addr_var.get(),
            swizzle=(v._swizzle_var.get().strip() if v._swizzle_en_var.get() else ""),
            lower=v._lower_var.get(),
            overwrite=v._overwrite_var.get(),
            out=v._out_var.get().strip(),
        )

    @staticmethod
    def _build_cmd(o: TexassembleOpts, inputs) -> list:
        """Pure command builder: a function of (opts, inputs) only — no Tk."""
        cmd = [o.exe, o.cmd, "-nologo", "-f", o.fmt]
        if o.filt: cmd += ["-if", o.filt]
        cs = COLORSPACE_MAP.get(o.colorspace, "")
        if cs: cmd.append(cs)
        if o.width is not None: cmd += ["-w", str(o.width)]
        if o.height is not None: cmd += ["-h", str(o.height)]
        if o.mips is not None: cmd += ["-m", str(o.mips)]
        if o.fl != "Default": cmd += ["-fl", o.fl]
        if o.recursive: cmd.append("-r")
        if o.sepalpha: cmd.append("-sepalpha")
        if o.alpha: cmd.append("-alpha")
        if o.dx10: cmd.append("-dx10")
        if o.tonemap: cmd.append("-tonemap")
        if o.gifbg: cmd.append("--gif-bg-color")
        if o.stripmips: cmd.append("--strip-mips")
        if o.nowic: cmd.append("-nowic")
        ad = ADDRESSING_MAP.get(o.addr, "")
        if ad: cmd.append(ad)
        if o.swizzle: cmd += ["--swizzle", o.swizzle]
        if o.lower: cmd.append("-l")
        if o.overwrite: cmd.append("-y")
        if o.out: cmd += ["-o", o.out]
        cmd += [str(p) for p in inputs]
        return cmd

    def _preview_command(self):
        cmd = self._build_cmd(self._gather_opts(), self._input_list() or [Path("in1.png"), Path("in2.png")])
        self._head("Preview command:")
        self._log_line("  " + " ".join(f'"{c}"' if " " in c else c for c in cmd), "dim")

    def _start(self):
        if self._running:
            return
        exe = self._resolve_exe()
        if not exe:
            self._fail("texassemble not found."); return
        self._exe_var.set(exe)
        inputs = self._input_list()
        if not inputs:
            self._warn("No input files."); return
        out = self._out_var.get().strip()
        if not out:
            self._warn("Set an output file."); return
        log.debug("texassemble: start — command=%s, %d input(s), out=%s",
                  self._cmd_var.get(), len(inputs), out)
        self._head(f"▶ texassemble {self._cmd_var.get()} · {len(inputs)} inputs → {os.path.basename(out)}")
        self._run_single(self._build_cmd(self._gather_opts(), inputs), success_check=lambda: Path(out).exists())


# ══════════════════════════════════════════════════════════════════════════════
#  TEXDIAG
# ══════════════════════════════════════════════════════════════════════════════
DIAG_COMMANDS = ["info", "analyze", "compare", "diff", "dumpbc", "dumpdds"]


@dataclass(frozen=True)
class TexdiagOpts:
    """Immutable snapshot of texdiag settings, taken on the main thread."""
    exe: str
    cmd: str
    tu: bool
    tf: bool
    dword: bool
    badtails: bool
    permissive: bool
    ignoremips: bool
    xlum: bool
    fmt: str
    diffcolor: str
    threshold: str
    out: str
    tx: int | None
    ty: int | None
    lower: bool
    overwrite: bool


TEXDIAG_HELP = """\
Texdiag · Guide

texdiag inspects and compares DDS / image files — it doesn't convert anything.
Pick a Command, point it at a file or folder, and read the results in the log.

── Commands ──
  • info — print each file's header and metadata (format, size, mips, flags).
  • analyze — per-pixel statistics (min/max/avg, alpha coverage, etc.).
  • compare — print difference metrics between two images (uses the 2nd file).
  • diff — write a visual difference image (set Output, Diff colour, Threshold).
  • dumpbc — dump the compressed bytes of one block (set Target X / Target Y).
  • dumpdds — extract each sub-image (faces / slices / mips) to disk.

── Using it ──
1. texdiag path — set and Test the executable.
2. Input — a file, or a folder (info/analyze run over every file in it).
3. 2nd file — the comparison image for compare / diff.
4. Output — where diff / dumpdds writes its result.
5. Click "Run texdiag". Drag & drop fills the input field (log pane too).

── Output ──
info/analyze/dumpbc/dumpdds read files in parallel for speed but print one clean,
clearly separated block per file in sorted order (green header = ok, red =
failed), so multi-worker output never interleaves. compare/diff are single runs.

── Options ──
  • Diff format (-f), Diff colour (-c), Threshold (-t) shape the diff image.
  • Target X / Target Y (--target-x / --target-y) pick the block for dumpbc.
  • Typeless→UNORM/FLOAT, DWORD align, Bad tails, Permissive, Ignore mips and
    Expand luminance handle awkward or legacy DDS input.

Value fields apply only when their checkbox is ticked. Hover any control for the
flag it maps to.
"""


class TexdiagPanel(ToolPanel):
    TOOL = "texdiag"
    CONFIG = "texdiag.json"
    RUN_LABEL = "Run texdiag"
    HELP_TITLE = "Texdiag · Guide"
    HELP_TEXT = TEXDIAG_HELP

    def _make_vars(self):
        self._cmd_var = tk.StringVar(value="info")
        self._dir_var = tk.StringVar()      # file/folder (input A)
        self._b_var = tk.StringVar()        # second file for compare/diff
        self._out_var = tk.StringVar()      # output for diff/dumpdds
        self._recursive_var = tk.BooleanVar(value=True)
        self._fmt_var = tk.StringVar(value="R8G8B8A8_UNORM")
        self._workers_var = tk.IntVar(value=self._default_workers)
        self._diffcolor_var = tk.StringVar()
        self._threshold_var = tk.StringVar()
        self._tx_var = tk.StringVar(); self._ty_var = tk.StringVar()
        self._overwrite_var = tk.BooleanVar(value=False)
        self._lower_var = tk.BooleanVar(value=False)
        self._tu_var = tk.BooleanVar(value=False); self._tf_var = tk.BooleanVar(value=False)
        self._dword_var = tk.BooleanVar(value=False); self._badtails_var = tk.BooleanVar(value=False)
        self._permissive_var = tk.BooleanVar(value=False); self._ignoremips_var = tk.BooleanVar(value=False)
        self._xlum_var = tk.BooleanVar(value=False)
        # Enable toggles for value fields (off → field disabled, flag omitted).
        self._diffcolor_en_var = tk.BooleanVar(value=False)
        self._threshold_en_var = tk.BooleanVar(value=False)
        self._tx_en_var = tk.BooleanVar(value=False)
        self._ty_en_var = tk.BooleanVar(value=False)
        self._cfg_map = {k: getattr(self, k) for k in vars(self) if k.endswith("_var")}

    def _build_controls(self, parent):
        cfg = ttk.Frame(parent); cfg.pack(fill="x", padx=10, pady=(10, 4)); cfg.columnconfigure(1, weight=1)
        ttk.Label(cfg, text="Command").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        cb = ttk.Combobox(cfg, textvariable=self._cmd_var, values=DIAG_COMMANDS, state="readonly", width=12)
        cb.grid(row=0, column=1, sticky="w", padx=(8, 6)); ToolTip(cb,
            "Which texdiag command to run: info prints header/metadata, analyze reports per-pixel statistics, "
            "compare prints difference metrics between two files, diff writes a visual difference image, "
            "dumpbc dumps one compressed block's bytes, dumpdds extracts each sub-image to disk.")
        self._dir_entry = self._path_row(cfg, 1, "Input (file/folder)", self._dir_var,
                                        on_folder=lambda: self._browse_into(self._dir_var, "dir", "Input folder"),
                                        on_file=lambda: self._browse_into(self._dir_var, "file", "Input file"))
        self._path_row(cfg, 2, "2nd file (compare/diff)", self._b_var,
                       browse=lambda: self._browse_into(self._b_var, "file", "Second file"))
        self._path_row(cfg, 3, "Output (diff/dumpdds)", self._out_var,
                       browse=lambda: self._browse_into(self._out_var, "file", "Output"))
        self._path_row(cfg, 4, "texdiag path", self._exe_var,
                       test=self._test_exe, browse=lambda: self._browse_exe_into(self._exe_var, "Locate texdiag"))
        self._setup_dnd(self._dir_entry, self._dir_var)

        opt = ttk.Frame(parent); opt.pack(fill="x", padx=10, pady=(6, 0))
        def row():
            r = ttk.Frame(opt); r.pack(fill="x", pady=(0, 6)); return r
        r = row()
        self._chk(r, "Recursive scan", self._recursive_var, "For info/analyze on a folder, search its subfolders too.")
        self._combo(r, "Diff format", self._fmt_var, ASSEMBLE_FORMATS, 22, "Pixel format of the difference image written by the diff command (-f).")
        self._workers_spin = ttk.Spinbox(r, from_=1, to=self._cpu_limit, textvariable=self._workers_var, width=4)
        self._workers_spin.pack(side="right"); ToolTip(self._workers_spin, "How many files info/analyze process in parallel.")
        ttk.Label(r, text="Threads").pack(side="right", padx=(6, 0))
        r = row()
        self._opt_entry(r, "Diff colour", self._diffcolor_en_var, self._diffcolor_var, 8, "Hex RGB colour used to highlight differing pixels in the diff image, e.g. ff0000 (-c).")
        self._opt_entry(r, "Threshold", self._threshold_en_var, self._threshold_var, 6, "Per-channel difference above which a pixel is flagged in the diff image (-t).")
        self._opt_entry(r, "Target X", self._tx_en_var, self._tx_var, 6, "X coordinate of the block to dump with the dumpbc command (--target-x).")
        self._opt_entry(r, "Target Y", self._ty_en_var, self._ty_var, 6, "Y coordinate of the block to dump with the dumpbc command (--target-y).")
        self._chk(r, "Overwrite", self._overwrite_var, "Replace the output file if it already exists (-y).")
        self._chk(r, "Lowercase", self._lower_var, "Force the output filename to lowercase (-l).")
        r = row()
        self._chk(r, "Typeless→UNORM", self._tu_var, "Read typeless source formats as UNORM (normalised unsigned) (-tu).")
        self._chk(r, "Typeless→FLOAT", self._tf_var, "Read typeless source formats as floating-point (-tf).")
        self._chk(r, "DWORD align", self._dword_var, "Assume legacy DWORD-aligned scanlines when reading the DDS (-dword).")
        self._chk(r, "Bad tails", self._badtails_var, "Work around DDS files whose smallest mip levels are stored incorrectly (--bad-tails).")
        self._chk(r, "Permissive", self._permissive_var, "Accept slightly malformed DDS input that would otherwise be rejected (--permissive).")
        self._chk(r, "Ignore mips", self._ignoremips_var, "Look at only the base image, ignoring any mipmaps (--ignore-mips).")
        self._chk(r, "Expand luminance", self._xlum_var, "Expand legacy luminance formats (L8/L16/A8P8) to RGBA before analysing (-xlum).")

    def _gather_opts(self) -> TexdiagOpts:
        """Snapshot all Tk variables into a frozen TexdiagOpts (main thread)."""
        v = self
        return TexdiagOpts(
            exe=v._exe_var.get().strip() or "texdiag",
            cmd=v._cmd_var.get(),
            tu=v._tu_var.get(), tf=v._tf_var.get(), dword=v._dword_var.get(),
            badtails=v._badtails_var.get(), permissive=v._permissive_var.get(),
            ignoremips=v._ignoremips_var.get(), xlum=v._xlum_var.get(),
            fmt=v._fmt_var.get(),
            diffcolor=(v._diffcolor_var.get().strip() if v._diffcolor_en_var.get() else ""),
            threshold=(v._threshold_var.get().strip() if v._threshold_en_var.get() else ""),
            out=v._out_var.get().strip(),
            tx=(self._int_or_none(v._tx_var.get()) if v._tx_en_var.get() else None),
            ty=(self._int_or_none(v._ty_var.get()) if v._ty_en_var.get() else None),
            lower=v._lower_var.get(),
            overwrite=v._overwrite_var.get(),
        )

    @staticmethod
    def _build_cmd(o: TexdiagOpts, files) -> list:
        """Pure command builder: a function of (opts, files) only — no Tk."""
        common = []
        if o.tu: common.append("-tu")
        if o.tf: common.append("-tf")
        if o.dword: common.append("-dword")
        if o.badtails: common.append("--bad-tails")
        if o.permissive: common.append("--permissive")
        if o.ignoremips: common.append("--ignore-mips")
        if o.xlum: common.append("-xlum")
        cmd = [o.exe, o.cmd, "-nologo"] + common
        if o.cmd == "diff":
            if o.fmt: cmd += ["-f", o.fmt]
            if o.diffcolor: cmd += ["-c", o.diffcolor]
            if o.threshold: cmd += ["-t", o.threshold]
            if o.out: cmd += ["-o", o.out]
            if o.lower: cmd.append("-l")
            if o.overwrite: cmd.append("-y")
        elif o.cmd == "dumpbc":
            if o.tx is not None: cmd += ["--target-x", str(o.tx)]
            if o.ty is not None: cmd += ["--target-y", str(o.ty)]
        elif o.cmd == "dumpdds":
            if o.out: cmd += ["-o", o.out]
        cmd += [str(f) for f in files]
        return cmd

    def _preview_command(self):
        cmd = self._build_cmd(self._gather_opts(), [Path(self._dir_var.get().strip() or "a.dds")])
        self._head("Preview command:")
        self._log_line("  " + " ".join(f'"{c}"' if " " in c else c for c in cmd), "dim")

    def _start(self):
        if self._running:
            return
        exe = self._resolve_exe()
        if not exe:
            self._fail("texdiag not found."); return
        self._exe_var.set(exe)
        opts = self._gather_opts()      # one main-thread snapshot for every command below
        c = self._cmd_var.get()
        a = self._dir_var.get().strip()
        if not a:
            self._warn("Select an input."); return
        ap = Path(a)
        log.debug("texdiag: start — command=%s, input=%s", c, ap)

        if c in ("compare", "diff"):
            b = self._b_var.get().strip()
            if not b:
                self._warn(f"'{c}' needs a second file."); return
            self._head(f"▶ texdiag {c}")
            # Capture the output path on the main thread; the success check runs
            # in a worker thread and must not read a Tk variable there.
            out = self._out_var.get().strip()
            check = (lambda: Path(out).exists()) if (c == "diff" and out) else None
            self._run_single(self._build_cmd(opts, [ap, Path(b)]), success_check=check)
            return

        # info / analyze / dumpbc / dumpdds: per-file, capture output to log
        if ap.is_file():
            files = [ap]
        else:
            files = _collect(ap, {".dds"} if c in ("dumpbc", "dumpdds") else IMAGE_EXTS, self._recursive_var.get())
        if not files:
            self._fail("No files found."); return
        workers = max(1, min(int(self._float_or(self._workers_var, self._default_workers)), self._cpu_limit, len(files)))
        self._arm(len(files))
        self._head(f"▶ texdiag {c} · {len(files)} files")

        # Pre-build per-file commands on the main thread (no Tk reads in workers).
        specs = [(f, self._build_cmd(opts, [f])) for f in files]

        # Workers run in parallel but finish in nondeterministic order. Stream
        # results in sorted order *incrementally* — each finished file unblocks the
        # contiguous in-order prefix, flushed a few at a time on the main thread
        # (yielding to the UI between chunks) so a large folder can't freeze the
        # window with one giant end-of-run render.
        results: dict[Path, tuple[bool, str]] = {}
        nxt = [0]

        def flush():
            shown = 0
            while nxt[0] < len(files) and files[nxt[0]] in results:
                f = files[nxt[0]]
                ok, txt = results[f]
                self._log_line(f"── {f.name} ──", "ok" if ok else "fail")
                for ln in (txt.splitlines() or ["(no output)"]):
                    self._log_line("    " + ln, "dim")
                self._log_line("", "dim")      # blank line separates each file
                nxt[0] += 1
                shown += 1
                if shown >= 15:                # yield, continue next tick
                    self._safe_after(flush)
                    return

        def job(spec):
            f, cmd = spec
            rc, out = run_proc(cmd, self._active, self._lock, self._cancel)
            results[f] = (rc == 0, out.strip())   # distinct keys → thread-safe under the GIL
            self._safe_after(flush)
            return (rc == 0), f.name

        self._run_parallel(specs, job, workers, log_each=False, on_finish=flush)


# ── Standalone suite ───────────────────────────────────────────────────────────
def main():
    logging.basicConfig(level=os.environ.get("DXTEX_LOGLEVEL", "WARNING").upper())
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    root.title("DirectXTex Tools")
    root.configure(bg=BG)
    root.minsize(1040, 840)
    apply_styles(root)

    hdr = ttk.Frame(root); hdr.pack(fill="x")
    ttk.Label(hdr, text="DirectXTex Tools", style="Title.TLabel").pack(side="left", padx=18, pady=12)
    ttk.Separator(root).pack(fill="x")

    paned = ttk.PanedWindow(root, orient="vertical")
    paned.pack(fill="both", expand=True, padx=12, pady=12)
    nb = ttk.Notebook(paned)
    paned.add(nb, weight=0)

    # One shared bottom pane per tab; only the active tab's strip is shown.
    bottoms = {}
    for cls, title in ((TexconvPanel, "  Texconv  "),
                       (TexassemblePanel, "  Texassemble  "),
                       (TexdiagPanel, "  Texdiag  ")):
        b = ttk.Frame(paned)
        panel = cls(nb, bottom_host=b)
        nb.add(panel, text=title)
        bottoms[nb.index(panel)] = b
    paned.add(bottoms[nb.index("current")], weight=1)
    shown = {"idx": nb.index("current")}

    def on_tab(_=None):
        cur = nb.index("current")
        if cur == shown["idx"]:
            return
        try:
            paned.forget(bottoms[shown["idx"]])
        except Exception:
            pass
        paned.add(bottoms[cur], weight=1)
        shown["idx"] = cur
    nb.bind("<<NotebookTabChanged>>", on_tab)

    root.mainloop()


if __name__ == "__main__":
    main()
