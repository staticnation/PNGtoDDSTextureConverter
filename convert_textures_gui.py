"""
convert_textures_gui.py - PNG → DDS batch converter (GUI)
Requires: Python 3.10+ - Pillow (pip install Pillow)
Uses: nvcompress (must be on PATH or specified in the UI)
"""

from __future__ import annotations

import os
import json
import shutil
import time
import signal
import threading
import subprocess
import warnings
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image

CONFIG_FILE = Path(__file__).parent / "convert_textures_config.json"

# ── Palette ──────────────────────────────────────────────────────────────────

BG      = "#181818"
BG2     = "#232323"
BG3     = "#2e2e2e"
BG4     = "#3a3a3a"
FG      = "#e0e0e0"
FG_DIM  = "#777777"
ACCENT  = "#5c9cf5"
SUCCESS = "#6abf69"
ERROR   = "#e57373"
WARN    = "#ffb74d"
BORDER  = "#404040"

FONT        = ("Segoe UI",  10)
FONT_SMALL  = ("Segoe UI",  9)
FONT_BOLD   = ("Segoe UI",  10, "bold")
FONT_TITLE  = ("Segoe UI",  13, "bold")
FONT_MONO   = ("Consolas",   9)


# ── Filter parameter metadata ─────────────────────────────────────────────────

FILTER_PARAMS: dict[str, tuple | None] = {
    "kaiser":             ("Width",  0.1, 10.0, 3.0,       "Stretch", 0.1, 5.0,  1.0),
    "mitchell-netravali": ("B",      0.0,  1.0, 1.0 / 3.0, "C",       0.0, 1.0,  1.0 / 3.0),
    "box":                None,
    "triangle":           None,
    "min":                None,  # Supported natively in NVTT 3.2.5+
    "max":                None,  # Supported natively in NVTT 3.2.5+
}

FILTERS = list(FILTER_PARAMS.keys())

FMT_MAP = {
    "Auto (BC1/BC3 Fallback)": "auto",
    
    # Block Compression Formats
    "BC1 (DXT1 Opaque / Punch-through)": "bc1",
    "BC1a (DXT1a Binary Alpha)":         "bc1a",
    "BC2 (DXT3 Explicit Alpha)":          "bc2",
    "BC3 (DXT5 Interpolated Alpha)":      "bc3",
    "BC7 (High Quality RGBA / Smooth)":   "bc7",
    
    # HDR / Floating Point Formats
    "BC6 (High Dynamic Range Unsigned)": "bc6",
    "BC6s (High Dynamic Range Signed)":   "bc6s",
    
    # Normal Maps (Enforces -normal flag)
    "BC1n (DXT1nm Normal Map)":           "bc1n",
    "BC3n (DXT5nm Normal Map)":           "bc3n",
    "BC5 (ATI2 / 3Dc Two-Channel Normal)": "bc5",
    "BC5s (BC5 Two-Channel Signed)":      "bc5s",
    "ATI2 (ATI2 Legacy Variant)":         "ati2",
    
    # Single/Dual Channel Greyscale & Component Maps
    "BC4 (ATI1 Single Channel Unsigned)": "bc4",
    "BC4s (BC4 Single Channel Signed)":   "bc4s",
    
    # Specialized Formats
    "BC3-RGBM (High Range LDR Encoding)": "bc3_rgbm",
    
    # ASTC Formats (Adaptive Scalable Texture Compression)
    "ASTC LDR 4x4":   "astc_ldr_4x4",
    "ASTC LDR 5x4":   "astc_ldr_5x4",
    "ASTC LDR 5x5":   "astc_ldr_5x5",
    "ASTC LDR 6x5":   "astc_ldr_6x5",
    "ASTC LDR 6x6":   "astc_ldr_6x6",
    "ASTC LDR 8x5":   "astc_ldr_8x5",
    "ASTC LDR 8x6":   "astc_ldr_8x6",
    "ASTC LDR 10x5":  "astc_ldr_10x5",
    "ASTC LDR 10x6":  "astc_ldr_10x6",
    "ASTC LDR 8x8":   "astc_ldr_8x8",
    "ASTC LDR 10x8":  "astc_ldr_10x8",
    "ASTC LDR 10x10": "astc_ldr_10x10",
    "ASTC LDR 12x10": "astc_ldr_12x10",
    "ASTC LDR 12x12": "astc_ldr_12x12",
    
    # Uncompressed Fallback
    "RGBA (Uncompressed 32-bit Raw)":     "rgb",
}

QUALITY_MAP = {
    "Fastest (-fastest)": "fastest",
    "Normal (-normal)": "normal",
    "Production (-production)": "production",
    "Highest (-highest)": "highest",
}

# ── Conversion helpers ────────────────────────────────────────────────────────

def get_image_info(path: Path) -> tuple[bool, bool]:
    """Returns (is_valid, has_alpha). Halves I/O by combining verify and scan."""
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            has_alpha = False
            if img.mode in ("RGBA", "LA"):
                has_alpha = img.getchannel("A").getextrema()[0] < 255
            elif img.mode == "P":
                has_alpha = "transparency" in img.info
            return True, has_alpha
    except Exception:
        return False, False


def collect_pngs(directory: Path, recursive: bool) -> list[Path]:
    iterator = directory.rglob("*") if recursive else directory.glob("*")
    return sorted(
        p for p in iterator 
        if p.is_file() and p.suffix.lower() == ".png"
    )


def convert_file(
    png: Path,
    base_dir: Path,
    out_dir: Path | None,
    mirror_tree: bool,
    nvcompress: str,
    fmt: str,
    quality: str,
    mip_filter: str,
    mip_params: tuple[float, float] | None,
    dithering: bool,
    dry_run: bool,
    overwrite: bool,
    active_processes: set[subprocess.Popen],
    process_lock: threading.Lock,
    cancel_event: threading.Event,
) -> tuple[bool, str]:
    """Returns (success, log_message)."""
    if cancel_event.is_set():
        return False, f"{png.name}  ->  [skipped due to cancellation]"

# Resolve output path mirroring
    if out_dir:
        if mirror_tree:
            rel_path = png.relative_to(base_dir)
            out = (out_dir / rel_path).with_suffix(".dds")
        else:
            out = out_dir / png.with_suffix(".dds").name
    else:
        out = png.with_suffix(".dds")
    
    if out.exists() and not overwrite and not dry_run:
        return False, f"{png.name}  ->  [skipped: {out.name} already exists]"

    is_valid, has_alpha = get_image_info(png)
    if not is_valid:
        return False, f"{png.name}  ->  [corrupt image validation error]"

    chosen = fmt if fmt != "auto" else ("bc3" if has_alpha else "bc1")
    label = f"{png.name}  ->  {out.name}  [{chosen.upper()}]"

    if dry_run:
        return True, f"[dry run]  {label}"

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [nvcompress]

    if quality != "default":
        cmd.append(f"-{quality}")
    
    # Automatically switch input processing profiles based on normal map targets
    if chosen in ("bc1n", "bc3n", "bc5", "bc5s", "ati2"):
        cmd.append("-normal")
    elif chosen == "bc7":
        cmd.append("-alpha" if has_alpha else "-color")
    elif chosen in ("bc1a", "bc2", "bc3", "bc3_rgbm") or (fmt == "auto" and has_alpha):
        cmd.append("-alpha")
    else:
        cmd.append("-color")

    if dithering and chosen in ("bc1a", "bc2", "bc3"):
        cmd.extend(["-alpha_dithering", "4"])

    cmd += ["-mipfilter", mip_filter]
    if mip_params is not None:
        cmd += ["-param1", str(mip_params[0]), "-param2", str(mip_params[1])]
        
    if chosen in ("bc6", "bc6s", "bc7") or chosen.startswith("astc"):
        cmd.append("-dds10")

    cmd += [f"-{chosen}", str(png), str(out)]

    try:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
            text=True, creationflags=flags, startupinfo=startupinfo, start_new_session=(os.name != "nt")
        )
        
        with process_lock:
            active_processes.add(proc)
            if cancel_event.is_set():
                if os.name == "nt": subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                else: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                return False, f"{label}\n         ↳ [aborted]"

        # Polling loop for responsiveness
        start_time = time.time()
        while proc.poll() is None:
            if cancel_event.is_set():
                if os.name == "nt": subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                else: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                return False, f"{label}\n         ↳ [aborted by user]"
            
            if time.time() - start_time > 300:
                if os.name == "nt": subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                else: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                if out.exists(): out.unlink(missing_ok=True)
                return False, f"{label}\n         ↳ [execution timed out after 300s]"
            time.sleep(0.5)

        stdout, stderr = proc.communicate()
        if proc.returncode == 0:
            try: shutil.copystat(png, out)
            except Exception: pass
            return True, label
            
        detail = (stderr or stdout).strip().splitlines() or ["unknown error"]
        return False, f"{label}\n         ↳ {detail[0]}"

    except Exception as e:
        return False, f"{label}\n         ↳ [execution error] {e}"
    finally:
        with process_lock:
            active_processes.discard(proc)

# ── Tooltip helper ───────────────────────────────────────────

class ToolTip:
    active_tooltips = []
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None

        self.widget.bind("<Enter>", self.show)
        self.widget.bind("<Leave>", self.hide)
        self.widget.bind("<Button-1>", self.hide)

        if isinstance(widget, ttk.Combobox):
            self.widget.bind("<<ComboboxSelected>>", self.hide)
            self.widget.bind("<FocusOut>", self.hide)

    def show(self, event=None):
        # Ensure no other tooltips are lingering
        ToolTip.hide_all()
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5

        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")

        # Add to global registry for tracking
        ToolTip.active_tooltips.append(self)

        tk.Label(
            tw,
            text=self.text,
            background=BG3,
            relief="solid",
            foreground=FG,
            borderwidth=1,
            font=("Segoe UI", 9),
            justify="left",
        ).pack(padx=1, pady=1)

    def hide(self, event=None):
        if self.tipwindow:
            try:
                self.tipwindow.destroy()
            except:
                pass
            self.tipwindow = None
            if self in ToolTip.active_tooltips:
                ToolTip.active_tooltips.remove(self)

    @classmethod
    def hide_all(cls):
        # Use cls instead of ToolTip to be safer
        for tip in list(cls.active_tooltips):
            tip.hide()

# ── App ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PNG to DDS Texture Converter")
        self.configure(bg=BG)
        self.minsize(820, 720)
        self.resizable(True, True)

        self._running = False
        self._cancel  = threading.Event()
        self._process_lock = threading.Lock()
        self._active_processes: set[subprocess.Popen] = set()
        self._failed_files: list[str] = []

        self._apply_styles()
        self._build_ui()
        self._load_config()
        self._setup_global_cleanup()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_global_cleanup(self):
        # Global cleanup on click, move, or resize
        self.bind("<Button-1>", lambda e: ToolTip.hide_all())
        self.bind("<Configure>", lambda e: ToolTip.hide_all())

    def _on_close(self):
        ToolTip.hide_all()
        self.destroy()
    
    def _show_help(self):
        win = tk.Toplevel(self)
        win.title("Help & Guidelines")
        win.geometry("500x450")
        win.configure(bg=BG2)
        
        help_text = (
            "DDS Texture Converter · User Guide\n\n"
            "1. Setup: Select your 'Texture folder' and 'Output folder'. Use the 'Test' button to verify your 'nvcompress' path.\n\n"
            "2. Formats: 'Auto' intelligently selects between BC1/BC3 based on alpha transparency. Use specific formats (like BC5/BC7) for normal maps or high-quality assets.\n\n"
            "3. Workflow: Multi-threaded conversion is handled by a worker pool. 'Dry run' mode allows you to verify file paths without writing any output.\n\n"
            "3. Workers: Parallelization uses ThreadPoolExecutor. 4 is recommended for most CPUs.\n"
            "5. Troubleshooting:\n"
            "   - If a conversion hangs, click 'Cancel' to force-kill the process tree.\n"
            "   - If a file is locked or corrupt, it will be logged as a failure in the status window.\n"
            "   - Settings are saved automatically to 'convert_textures_config.json'."
        )
        
        txt = tk.Text(win, bg=BG3, fg=FG, font=FONT, padx=15, pady=15, 
                      relief="flat", wrap="word")
        txt.insert("1.0", help_text)
        txt.configure(state="disabled")
        txt.pack(expand=True, fill="both", padx=10, pady=10)
        
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=10)

# ── Styles ────────────────────────────────────────────────────────────────

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")

        base = dict(
            background=BG2,
            foreground=FG,
            bordercolor=BORDER,
            troughcolor=BG4,
            fieldbackground=BG3,
            selectbackground=ACCENT,
            selectforeground="#ffffff",
            font=FONT,
        )

        s.configure(".", **base)
        s.configure("TFrame",       background=BG2)
        s.configure("TLabel",       background=BG2, foreground=FG,     font=FONT)
        s.configure("Dim.TLabel",   background=BG2, foreground=FG_DIM, font=FONT_SMALL)
        s.configure("Title.TLabel", background=BG,  foreground=FG,     font=FONT_TITLE)
        s.configure("Head.TFrame",  background=BG)

        s.configure("TEntry", fieldbackground=BG3, foreground=FG, insertcolor=FG, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        s.configure("TButton", background=BG4, foreground=FG, bordercolor=BORDER, focuscolor=BG4, padding=(8, 4))
        s.map("TButton", background=[("active", "#4a4a4a"), ("disabled", BG3)], foreground=[("disabled", FG_DIM)])
        
        s.configure("Primary.TButton", background=ACCENT, foreground="#ffffff", font=FONT_BOLD, padding=(16, 6))
        s.map("Primary.TButton", background=[("active", "#4888e8"), ("disabled", BG4)], foreground=[("disabled", FG_DIM)])
        
        s.configure("Danger.TButton", background="#9c3030", foreground="#ffffff", font=FONT_BOLD, padding=(16, 6))
        s.map("Danger.TButton", background=[("active", "#b03838"), ("disabled", BG4)], foreground=[("disabled", FG_DIM)])
        
        s.configure("TCombobox", fieldbackground=BG3, background=BG4, foreground=FG, arrowcolor=FG_DIM, bordercolor=BORDER)
        s.map("TCombobox", fieldbackground=[("readonly", BG3)], selectbackground=[("readonly", BG3)], selectforeground=[("readonly", FG)])
        self.option_add("*TCombobox*Listbox.background", BG3)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

        s.configure("TSpinbox", fieldbackground=BG3, foreground=FG, arrowcolor=FG_DIM, bordercolor=BORDER, background=BG4)
        s.configure("TCheckbutton", background=BG2, foreground=FG, indicatorcolor=BG4, indicatorbackground=BG4)
        s.map("TCheckbutton", indicatorcolor=[("selected", ACCENT)], background=[("active", BG2)])
        s.configure("TProgressbar", troughcolor=BG4, background=ACCENT, bordercolor=BG4)
        s.configure("TSeparator", background=BORDER)


# ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header container
        hdr = ttk.Frame(self, style="Head.TFrame")
        hdr.pack(fill="x")
        
        # Use grid for the header inner frame to control column positioning
        inner = ttk.Frame(hdr, style="Head.TFrame")
        inner.pack(fill="x", padx=18, pady=12)
        inner.columnconfigure(1, weight=1) # The empty middle column will expand
        
        # Left side: Title and Metadata
        title_group = ttk.Frame(inner, style="Head.TFrame")
        title_group.grid(row=0, column=0, sticky="w")
        ttk.Label(title_group, text="PNG to DDS Texture Converter", style="Title.TLabel").pack(side="left")
        ttk.Label(title_group, text="  nvcompress  ·  Block Compression Spectrum  ·  Mipmap Engine", 
                  style="Dim.TLabel").pack(side="left", pady=(2, 0), padx=(10, 0))

        # Right side: Help button
        # This will be pushed to the far right because column 1 (the middle) has weight=1
        ttk.Button(inner, text="?", width=3, command=self._show_help).grid(row=0, column=2, sticky="e")

        ttk.Separator(self).pack(fill="x")

        cfg = ttk.Frame(self)
        cfg.pack(fill="x", padx=18, pady=12)
        cfg.columnconfigure(1, weight=1)

        self._dir_var = tk.StringVar()
        self._out_var = tk.StringVar()
        self._nv_var  = tk.StringVar(value="nvcompress")

         # Row 0 - Texture folder
        ttk.Label(cfg, text="Texture folder").grid(
            row=0, column=0, sticky="w", pady=3
        )

        self._dir_entry = ttk.Entry(
            cfg,
            textvariable=self._dir_var
        )
        self._dir_entry.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(10, 6)
        )

        self._dir_btn = ttk.Button(
            cfg,
            text="Browse…",
            command=self._browse_dir
        )
        self._dir_btn.grid(
            row=0,
            column=2,
            sticky="ew"
        )

        ToolTip(
            self._dir_entry,
            "Root folder containing the PNG texture files to convert."
        )
        ToolTip(
            self._dir_btn,
            "Browse for the source texture folder."
        )


        # Row 1 - Output folder
        ttk.Label(cfg, text="Output folder").grid(
            row=1, column=0, sticky="w", pady=3
        )

        self._out_entry = ttk.Entry(
            cfg,
            textvariable=self._out_var
        )
        self._out_entry.grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(10, 6)
        )

        self._out_btn = ttk.Button(
            cfg,
            text="Browse…",
            command=self._browse_out
        )
        self._out_btn.grid(
            row=1,
            column=2,
            sticky="ew"
        )

        ToolTip(
            self._out_entry,
            "Destination folder where DDS files will be written."
        )
        ToolTip(
            self._out_btn,
            "Browse for the DDS output location."
        )


        # Row 2 - nvcompress path
        ttk.Label(cfg, text="nvcompress path").grid(
            row=2, column=0, sticky="w", pady=3
        )

        self._nv_entry = ttk.Entry(
            cfg,
            textvariable=self._nv_var
        )
        self._nv_entry.grid(
            row=2,
            column=1,
            sticky="ew",
            padx=(10, 6)
        )

        nv_btns = ttk.Frame(cfg)
        nv_btns.grid(
            row=2,
            column=2,
            sticky="ew"
        )

        self._nv_test_btn = ttk.Button(
            nv_btns,
            text="Test",
            command=self._test_nvcompress
        )
        self._nv_test_btn.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(0, 2)
        )

        self._nv_browse_btn = ttk.Button(
            nv_btns,
            text="Browse…",
            command=self._browse_nv
        )
        self._nv_browse_btn.pack(
            side="left",
            fill="x",
            expand=True
        )

        ToolTip(
            self._nv_entry,
            "Path to NVIDIA Texture Tools nvcompress executable."
        )
        ToolTip(
            self._nv_test_btn,
            "Run a quick test to verify nvcompress works."
        )
        ToolTip(
            self._nv_browse_btn,
            "Locate nvcompress.exe manually."
        )


        opt_frame = ttk.Frame(cfg)
        opt_frame.grid(
            row=3,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(10, 0)
        )


        # Row 3 - Compression options
        row3 = ttk.Frame(opt_frame)
        row3.pack(
            fill="x",
            anchor="w",
            pady=(0, 4)
        )

        ttk.Label(row3, text="Format").pack(side="left")

        self._fmt_var = tk.StringVar(
            value="Auto (BC1/BC3 Fallback)"
        )

        self._fmt_cb = ttk.Combobox(
            row3,
            textvariable=self._fmt_var,
            values=list(FMT_MAP.keys()),
            state="readonly",
            width=32
        )
        self._fmt_cb.pack(
            side="left",
            padx=(6, 16)
        )


        ttk.Label(row3, text="Mip filter").pack(side="left")

        self._mip_var = tk.StringVar(
            value="kaiser"
        )

        self._mip_cb = ttk.Combobox(
            row3,
            textvariable=self._mip_var,
            values=FILTERS,
            state="readonly",
            width=12
        )
        self._mip_cb.pack(
            side="left",
            padx=(6, 16)
        )

        self._mip_cb.bind(
            "<<ComboboxSelected>>",
            self._on_filter_changed
        )


        ttk.Label(row3, text="Quality").pack(side="left")

        self._quality_var = tk.StringVar(
            value="Production (-production)"
        )

        self._quality_cb = ttk.Combobox(
            row3,
            textvariable=self._quality_var,
            values=list(QUALITY_MAP.keys()),
            state="readonly",
            width=18
        )

        self._quality_cb.pack(
            side="left",
            padx=(6, 16)
        )


        ttk.Label(row3, text="Workers").pack(side="left")

        cpu_count = os.cpu_count() or 2
        default_workers = min(
            4,
            max(1, cpu_count // 2)
        )

        self._workers_var = tk.IntVar(
            value=default_workers
        )

        self._workers_spin = ttk.Spinbox(
            row3,
            from_=1,
            to=min(16, cpu_count),
            textvariable=self._workers_var,
            width=4
        )

        self._workers_spin.pack(
            side="left",
            padx=(6, 16)
        )


        ToolTip(
            self._fmt_cb,
            "DDS compression format selection. BC7 provides high quality RGBA compression."
        )

        ToolTip(
            self._mip_cb,
            "Mipmap downsampling filter used when generating texture mip levels."
        )

        ToolTip(
            self._quality_cb,
            "Compression quality preset. Higher quality requires more processing time."
        )

        ToolTip(
            self._workers_spin,
            "Number of parallel nvcompress jobs. Higher values increase RAM and CPU usage."
        )


        # Row 4 - Additional options
        row4 = ttk.Frame(opt_frame)
        row4.pack(
            fill="x",
            anchor="w",
            pady=(0, 8)
        )

        self._recursive_var = tk.BooleanVar(value=False)

        self._recursive_chk = ttk.Checkbutton(
            row4,
            text="Recursive scan",
            variable=self._recursive_var,
            command=self._toggle_mirror
        )

        self._recursive_chk.pack(
            side="left",
            padx=(0, 16)
        )


        self._mirror_var = tk.BooleanVar(value=False)

        self._mirror_chk = ttk.Checkbutton(
            row4,
            text="Mirror structure",
            variable=self._mirror_var,
            state="disabled"
        )

        self._mirror_chk.pack(
            side="left",
            padx=(0, 16)
        )


        self._overwrite_var = tk.BooleanVar(value=False)

        self._overwrite_chk = ttk.Checkbutton(
            row4,
            text="Overwrite existing",
            variable=self._overwrite_var
        )

        self._overwrite_chk.pack(
            side="left",
            padx=(0, 16)
        )


        self._dither_var = tk.BooleanVar(value=False)

        self._dither_chk = ttk.Checkbutton(
            row4,
            text="Alpha dithering",
            variable=self._dither_var
        )

        self._dither_chk.pack(
            side="left",
            padx=(0, 16)
        )


        self._dryrun_var = tk.BooleanVar(value=False)

        self._dryrun_chk = ttk.Checkbutton(
            row4,
            text="Dry run mode",
            variable=self._dryrun_var
        )

        self._dryrun_chk.pack(
            side="left"
        )


        ToolTip(
            self._recursive_chk,
            "Search all subdirectories for PNG files."
        )

        ToolTip(
            self._mirror_chk,
            "Recreates the source folder hierarchy inside the output folder."
        )

        ToolTip(
            self._overwrite_chk,
            "Replace existing DDS files instead of skipping them."
        )

        ToolTip(
            self._dither_chk,
            "Applies alpha dithering to reduce visible banding after compression."
        )

        ToolTip(
            self._dryrun_chk,
            "Simulates conversion without writing DDS files."
        )

        # Row 5: Parameter Overrides Configuration
        row5 = ttk.Frame(opt_frame)
        row5.pack(fill="x", anchor="w")

        self._use_params_var = tk.BooleanVar(value=False)
        self._param_chk = ttk.Checkbutton(
            row5,
            text="Override filter params",
            variable=self._use_params_var,
            command=self._toggle_param_entries,
        )
        self._param_chk.pack(side="left", padx=(0, 10))

        self._p1_label_var = tk.StringVar(value="Param 1 (Width)")
        ttk.Label(row5, textvariable=self._p1_label_var).pack(side="left")

        self._param1_var = tk.DoubleVar(value=3.0)
        self._p1_entry = ttk.Spinbox(
            row5,
            from_=0.1,
            to=10.0,
            increment=0.1,
            format="%.3f",
            textvariable=self._param1_var,
            width=7,
            state="disabled",
        )
        self._p1_entry.pack(side="left", padx=(6, 16))

        self._p2_label_var = tk.StringVar(value="Param 2 (Stretch)")
        ttk.Label(row5, textvariable=self._p2_label_var).pack(side="left")

        self._param2_var = tk.DoubleVar(value=1.0)
        self._p2_entry = ttk.Spinbox(
            row5,
            from_=0.1,
            to=10.0,
            increment=0.1,
            format="%.3f",
            textvariable=self._param2_var,
            width=7,
            state="disabled",
        )
        self._p2_entry.pack(side="left", padx=(6, 16))

        self._param_note = ttk.Label(
            row5,
            text="",
            style="Dim.TLabel",
        )
        self._param_note.pack(side="left", padx=(4, 0))

        # Row 5 Tooltips
        ToolTip(
            self._param_chk,
            "Enable manual override of the mipmap filter's mathematical parameters."
        )

        ToolTip(
            self._p1_entry,
            "Primary filter parameter.\n"
            "Example: Kaiser filter width controls the sampling window size."
        )

        ToolTip(
            self._p2_entry,
            "Secondary filter parameter.\n"
            "Example: Kaiser stretch controls the shape of the filter curve."
        )

        ToolTip(
            self._param_note,
            "Displays information about the currently selected mipmap filter."
        )

        ttk.Separator(self).pack(fill="x", padx=0, pady=(10, 0))

        act = ttk.Frame(self)
        act.pack(fill="x", padx=18, pady=10)

        self._go_btn = ttk.Button(act, text="Convert Textures", style="Primary.TButton", command=self._start)
        self._go_btn.pack(side="left")

        self._stop_btn = ttk.Button(act, text="Cancel", style="Danger.TButton", command=self._cancel_run, state="disabled")
        self._stop_btn.pack(side="left", padx=(8, 0))

        self._status = ttk.Label(act, text="", style="Dim.TLabel")
        self._status.pack(side="left", padx=(14, 0))

        self._clear_btn = ttk.Button(
            act,
            text="Clear log",
            command=self._clear_log
        )
        self._clear_btn.pack(side="right")

        ToolTip(
            self._clear_btn,
            "Clear the conversion log and reset the progress display."
        )

        self._bar = ttk.Progressbar(self, mode="determinate")
        self._bar.pack(fill="x", padx=18, pady=(0, 8))

        log_wrap = ttk.Frame(self)
        log_wrap.pack(fill="both", expand=True, padx=18, pady=(0, 16))

        self._log = tk.Text(
            log_wrap, bg=BG3, fg=FG, font=FONT_MONO, insertbackground=FG,
            selectbackground=ACCENT, selectforeground="#ffffff", borderwidth=0,
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
            wrap="none", state="disabled"
        )
        self._log.pack(side="left", fill="both", expand=True)

        sb = ttk.Scrollbar(log_wrap, orient="vertical", command=self._log.yview)
        sb.pack(side="right", fill="y")
        self._log["yscrollcommand"] = sb.set

        self._log.tag_configure("ok",     foreground=SUCCESS)
        self._log.tag_configure("fail",   foreground=ERROR)
        self._log.tag_configure("warn",   foreground=WARN)
        self._log.tag_configure("header", foreground=ACCENT)
        self._log.tag_configure("dim",    foreground=FG_DIM)

        self._on_filter_changed()

    # ── UI State Handlers ─────────────────────────────────────────────────────

    def _toggle_mirror(self):
        state = "normal" if self._recursive_var.get() else "disabled"
        self._mirror_chk.configure(state=state)

    def _on_filter_changed(self, event=None, load_defaults=True):
        meta = FILTER_PARAMS.get(self._mip_var.get())

        if meta is None:
            self._use_params_var.set(False)
            self._param_chk.configure(state="disabled")
            self._p1_entry.configure(state="disabled")
            self._p2_entry.configure(state="disabled")
            self._p1_label_var.set("Param 1")
            self._p2_label_var.set("Param 2")
            self._param_note.configure(text="(no params for this filter)")
        else:
            p1_lbl, p1_min, p1_max, p1_def, p2_lbl, p2_min, p2_max, p2_def = meta
            self._param_chk.configure(state="normal")
            self._p1_label_var.set(f"Param 1 ({p1_lbl})")
            self._p2_label_var.set(f"Param 2 ({p2_lbl})")
            self._param_note.configure(text="")
            self._p1_entry.configure(from_=p1_min, to=p1_max)
            self._p2_entry.configure(from_=p2_min, to=p2_max)
            if load_defaults:
                self._param1_var.set(round(p1_def, 4))
                self._param2_var.set(round(p2_def, 4))
            self._toggle_param_entries()

    def _toggle_param_entries(self):
        state = "normal" if self._use_params_var.get() else "disabled"
        self._p1_entry.configure(state=state)
        self._p2_entry.configure(state=state)

    # ── Configuration persistence ─────────────────────────────────────────────

    def _load_config(self):
        if not CONFIG_FILE.exists():
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                
            if "texture_dir" in cfg: self._dir_var.set(cfg["texture_dir"])
            if "output_dir"  in cfg: self._out_var.set(cfg["output_dir"])
            if "nvcompress"  in cfg: self._nv_var.set(cfg["nvcompress"])
            if "workers"     in cfg: self._workers_var.set(cfg["workers"])
            
            if "format" in cfg and cfg["format"] in FMT_MAP: self._fmt_var.set(cfg["format"])
            if "filter" in cfg and cfg["filter"] in FILTERS: self._mip_var.set(cfg["filter"])
            if "quality" in cfg and cfg["quality"] in QUALITY_MAP: self._quality_var.set(cfg["quality"])
                
            if "recursive"   in cfg: self._recursive_var.set(cfg["recursive"])
            if "mirror_tree" in cfg: self._mirror_var.set(cfg["mirror_tree"])
            if "overwrite"   in cfg: self._overwrite_var.set(cfg["overwrite"])
            if "dithering"   in cfg: self._dither_var.set(cfg["dithering"])
            if "dry_run"     in cfg: self._dryrun_var.set(cfg["dry_run"])
            if "use_params"  in cfg: self._use_params_var.set(cfg["use_params"])
            if "param1"      in cfg: self._param1_var.set(cfg["param1"])
            if "param2"      in cfg: self._param2_var.set(cfg["param2"])
            
            self._on_filter_changed(load_defaults=False)
            self._toggle_mirror()
        except Exception as e:
            self._log_warn(f"Config load failed: {e}")

    def _save_config(self):
        try:
            cfg = {
                "texture_dir": self._dir_var.get().strip(),
                "output_dir":  self._out_var.get().strip(),
                "nvcompress":  self._nv_var.get().strip(),
                "format":      self._fmt_var.get(),
                "filter":      self._mip_var.get(),
                "quality":     self._quality_var.get(),
                "workers":     self._workers_var.get(),
                "recursive":   self._recursive_var.get(),
                "mirror_tree": self._mirror_var.get(),
                "overwrite":   self._overwrite_var.get(),
                "dithering":   self._dither_var.get(),
                "dry_run":     self._dryrun_var.get(),
                "use_params":  self._use_params_var.get(),
                "param1":      self._param1_var.get(),
                "param2":      self._param2_var.get(),
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    # ── Browse & Test ─────────────────────────────────────────────────────────

    def _browse_dir(self):
        d = filedialog.askdirectory(title="Select texture input folder")
        if d: self._dir_var.set(d)

    def _browse_out(self):
        d = filedialog.askdirectory(title="Select output folder (leave empty for same folder)")
        if d: self._out_var.set(d)

    def _browse_nv(self):
        f = filedialog.askopenfilename(
            title="Locate nvcompress binary",
            filetypes=[("Executables", "*.exe"), ("All files", "*.*")],
        )
        if f: self._nv_var.set(f)

    def _test_nvcompress(self):
        nv_path = self._nv_var.get().strip() or "nvcompress"
        p = Path(nv_path)
        
        # If the user selected the parent folder instead of the file, look inside it
        if p.is_dir() and nv_path != "nvcompress":
            if (p / "nvcompress.exe").is_file():
                resolved = str(p / "nvcompress.exe")
            elif (p / "nvcompress").is_file():
                resolved = str(p / "nvcompress")
            else:
                resolved = None
        else:
            resolved = shutil.which(nv_path) or (nv_path if p.is_file() else None)
        
        if not resolved:
            messagebox.showerror("Error", f"Could not find 'nvcompress' inside '{nv_path}' or on your system PATH.")
            return

        try:
            # Launch with no arguments to accommodate older builds gracefully
            subprocess.run([resolved], capture_output=True, text=True, timeout=3)
            messagebox.showinfo("Success", f"nvcompress is valid and functional.\n\nPath: {resolved}")
        except Exception as e:
            messagebox.showerror("Execution Error", f"Failed to run executable:\n{e}")

    # ── Log helpers ───────────────────────────────────────────────────────────

    def _log_line(self, text: str, tag: str = ""):
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n", tag)
        self._log.configure(state="disabled")
        self._log.see("end")

    def _log_ok(self, msg: str): self._log_line(f"✔  {msg}", "ok")
    def _log_fail(self, msg: str): self._log_line(f"✖  {msg}", "fail")
    def _log_warn(self, msg: str): self._log_line(f"⚠  {msg}", "warn")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        self._bar["value"] = 0
        self._status.configure(text="")

    # ── Conversion ────────────────────────────────────────────────────────────

    def _start(self):
        directory  = self._dir_var.get().strip()
        out_target = self._out_var.get().strip()
        nvcompress_input = self._nv_var.get().strip() or "nvcompress"
        
        fmt_choice = FMT_MAP.get(self._fmt_var.get(), "auto")
        mip_filter = self._mip_var.get()
        quality_choice = QUALITY_MAP.get(self._quality_var.get(), "production")
        
        p = Path(nvcompress_input)
        # Only treat it as a directory if it's a real path, not the default "nvcompress" keyword
        if p.is_dir() and nvcompress_input != "nvcompress":
            if (p / "nvcompress.exe").is_file():
                resolved = str(p / "nvcompress.exe")
            elif (p / "nvcompress").is_file():
                resolved = str(p / "nvcompress")
            else:
                resolved = None
        else:
            resolved = shutil.which(nvcompress_input)
            
        if resolved is None and not p.is_file():
            self._log_fail(f"Executable path error: '{nvcompress_input}' could not be located.")
            return
            
        nvcompress = resolved if resolved else str(p.resolve())

        try:
            # Verify the binary launches without throwing an OS exception
            subprocess.run([nvcompress], capture_output=True, text=True, timeout=3)
        except Exception as e:
            self._log_fail(f"Could not execute nvcompress: {e}")
            return

        try:
            workers = max(1, self._workers_var.get())
        except (tk.TclError, ValueError):
            workers = 1
            
        recursive   = self._recursive_var.get()
        mirror_tree = self._mirror_var.get() if recursive else False
        overwrite   = self._overwrite_var.get()
        dithering   = self._dither_var.get()
        dry_run     = self._dryrun_var.get()

        mip_params = None
        if self._use_params_var.get():
            meta = FILTER_PARAMS.get(mip_filter)
            try:
                p1 = float(self._param1_var.get())
                p2 = float(self._param2_var.get())
                if meta:
                    p1 = max(meta[1], min(p1, meta[2]))
                    p2 = max(meta[5], min(p2, meta[6]))
                mip_params = (p1, p2)
            except (ValueError, tk.TclError):
                self._log_fail("Invalid filter parameter values — numbers required.")
                return

        if not directory:
            self._log_warn("No texture folder selected.")
            return

        base_path = Path(directory)
        if not base_path.is_dir():
            self._log_fail(f"Not a directory: {directory}")
            return

        out_path = Path(out_target) if out_target else None

        pngs = collect_pngs(base_path, recursive)
        if not pngs:
            self._log_warn("No PNG files found.")
            return

        workers = min(workers, len(pngs))

        self._save_config()
        self._cancel.clear()
        with self._process_lock:
            self._active_processes.clear()
            
        self._running = True
        self._failed_files.clear()
        self._go_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._bar["value"]   = 0
        self._bar["maximum"] = len(pngs)

        if out_path:
            if mirror_tree:
                existing_dds_count = sum(1 for p in pngs if (out_path / p.relative_to(base_path)).with_suffix(".dds").exists())
            else:
                existing_dds_count = sum(1 for p in pngs if (out_path / p.with_suffix(".dds").name).exists())
        else:
            existing_dds_count = sum(1 for p in pngs if p.with_suffix(".dds").exists())

        tags = [
            f"{len(pngs)} file{'s' if len(pngs) != 1 else ''}",
            f"format: {fmt_choice}",
            f"filter: {mip_filter}",
            f"quality: {quality_choice}",
            f"workers: {workers}",
        ]
        if mip_params: tags.append(f"params: {mip_params[0]:.3f}, {mip_params[1]:.3f}")
        if dithering: tags.append("dithering: on")
        if recursive: tags.append(f"recursive {'(mirroring)' if mirror_tree and out_path else ''}")
        
        if dry_run:
            tags.append("DRY RUN")
        else:
            tags.append(f"existing DDS: {existing_dds_count} (" + ("overwrite" if overwrite else "skip") + ")")

        self._log_line("▶  " + "  ·  ".join(tags), "header")
        self._log_line("─" * 62, "dim")

        threading.Thread(
            target=self._run,
            args=(pngs, base_path, out_path, mirror_tree, nvcompress, fmt_choice, quality_choice, mip_filter, mip_params, dithering, workers, overwrite, dry_run),
            daemon=True,
        ).start()

    def _run(
        self, pngs: list[Path], base_dir: Path, out_dir: Path | None, mirror_tree: bool,
        nvcompress: str, fmt: str, quality: str, mip_filter: str, mip_params: tuple[float, float] | None, 
        dithering: bool, workers: int, overwrite: bool, dry_run: bool
    ):
        total = len(pngs)
        state = {"success": 0, "failed": 0, "done": 0}
        failed_tracker: list[str] = []

        def pipeline_update(ok, msg, name: str):
            state["done"] += 1
            if ok:
                state["success"] += 1
                self._log_ok(msg)
            else:
                state["failed"] += 1
                failed_tracker.append(name)
                self._log_fail(msg)
            self._tick(state["done"], total)

        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {
                pool.submit(
                    convert_file, p, base_dir, out_dir, mirror_tree, nvcompress, fmt, quality, mip_filter, 
                    mip_params, dithering, dry_run, overwrite, self._active_processes, self._process_lock, self._cancel
                ): p for p in pngs
            }
            
            while futures:
                if self._cancel.is_set():
                    for future in futures:
                        future.cancel()
                    break
                
                done, _ = wait(futures, timeout=0.2, return_when=FIRST_COMPLETED)
                
                for future in done:
                    p = futures.pop(future)
                    try:
                        ok, msg = future.result()
                    except Exception as exc:
                        ok, msg  = False, f"{p.name}\n         ↳ [internal error] {exc}"
                    self.after(0, pipeline_update, ok, msg, p.name)
            
            if self._cancel.is_set():
                remaining_done, _ = wait(futures, timeout=2.0)
                for future in remaining_done:
                    p = futures.pop(future)
                    try:
                        ok, msg = future.result()
                    except Exception:
                        ok, msg = False, f"{p.name} -> [aborted]"
                    self.after(0, pipeline_update, ok, msg, p.name)
                    
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

        success_val, failed_val, done_val = state["success"], state["failed"], state["done"]
        self.after(0, lambda: self._finish(success_val, failed_val, done_val, total, self._cancel.is_set(), failed_tracker))

    def _tick(self, done: int, total: int):
        self._bar["value"] = done
        self._status.configure(text=f"{done} / {total}")

    def _finish(self, success: int, failed: int, done: int, total: int, cancelled: bool, failed_tracker: list[str]):
        self._running = False
        self._failed_files = failed_tracker
        self._go_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._log_line("─" * 62, "dim")

        if cancelled:
            self._log_line(f"⏹  Cancelled.  Converted: {success}  Failed: {failed}", "warn")
            self._status.configure(text=f"{done} / {total}")
        else:
            if failed:
                self._log_warn(f"Done with errors.  Converted: {success}  Failed: {failed}  Total: {total}")
                self._log_line("\nFailed files summary:", "fail")
                for f_name in self._failed_files: self._log_line(f"  ↳ {f_name}", "dim")
            else:
                self._log_line(f"✔  All done.  {success} file{'s' if success != 1 else ''} converted.", "ok")
            self._status.configure(text=f"{total} / {total}")

    def _cancel_run(self):
        if self._running:
            self._cancel.set()
            self._stop_btn.configure(state="disabled")
            self._log_warn("Cancelling conversion and terminating active compressors…")
            
            with self._process_lock:
                processes_to_kill = list(self._active_processes)
                self._active_processes.clear()

            for proc in processes_to_kill:
                try:
                    if os.name == "nt":
                        # Windows: Force terminate the process tree
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], 
                                       capture_output=True, check=False)
                    else:
                        # Unix: Kill the process group
                        try:
                            pgid = os.getpgid(proc.pid)
                            os.killpg(pgid, signal.SIGKILL)
                        except ProcessLookupError:
                            # Process already dead, ignore
                            pass
                        except OSError:
                            # Fallback to single process kill if pgid lookup fails
                            proc.kill()
                except Exception:
                    # Catch-all for unexpected termination errors
                    pass

    def _on_close(self):
        if self._running: self._cancel_run()
        self.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()