"""
convert_textures_gui.py  –  Optimized Bidirectional DDS ↔ PNG Texture Converter (GUI)

  PNG → DDS  :  uses nvcompress with dynamic format capability detection
  DDS → PNG  :  uses nvdecompress with a structural fallback to Pillow

Requires : Python 3.10+, tkinter, tkinterdnd2, and Pillow
"""

from __future__ import annotations

import os
import re
import json
import shutil
import signal
import time
import threading
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES
from PIL import Image

# Safely isolate configuration boundaries across distinct platforms
def get_config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming")))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")))
    
    app_dir = base / "DDSConverter"
    try:
        app_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return Path(__file__).parent / "convert_textures_config.json"
    return app_dir / "config.json"

CONFIG_FILE = get_config_path()

# ── Palette ───────────────────────────────────────────────────────────────────

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

FONT       = ("Segoe UI",  10)
FONT_SMALL = ("Segoe UI",  9)
FONT_BOLD  = ("Segoe UI",  10, "bold")
FONT_TITLE = ("Segoe UI",  13, "bold")
FONT_MONO  = ("Consolas",   9)

# ── Filter / format / quality metadata ───────────────────────────────────────

FILTER_PARAMS: dict[str, tuple | None] = {
    "kaiser":    ("Width",  0.1, 10.0, 3.0,       "Stretch", 0.1, 5.0, 1.0),
    "mitchell-netravali":  ("B",      0.0,  1.0, 1.0 / 3.0, "C",       0.0, 1.0, 1.0 / 3.0),
    "box":       None,
    "triangle":  None,
    "min":       None,
    "max":       None,
}

FILTERS = list(FILTER_PARAMS.keys())

FMT_MAP = {
    "Auto (BC1/BC3 Fallback)":             "auto",
    "BC1 (DXT1 Opaque / Punch-through)":   "bc1",
    "BC1a (DXT1a Binary Alpha)":           "bc1a",
    "BC2 (DXT3 Explicit Alpha)":           "bc2",
    "BC3 (DXT5 Interpolated Alpha)":       "bc3",
    "BC7 (High Quality RGBA / Smooth)":    "bc7",
    "BC6 (High Dynamic Range Unsigned)":   "bc6",
    "BC6s (High Dynamic Range Signed)":    "bc6s",
    "BC1n (DXT1nm Normal Map)":            "bc1n",
    "BC3n (DXT5nm Normal Map)":            "bc3n",
    "BC5 (ATI2 / 3Dc Two-Channel Normal)": "bc5",
    "BC5s (BC5 Two-Channel Signed)":       "bc5s",
    "ATI2 (ATI2 Legacy Variant)":          "ati2",
    "BC4 (ATI1 Single Channel Unsigned)":  "bc4",
    "BC4s (BC4 Single Channel Signed)":    "bc4s",
    "BC3-RGBM (High Range LDR Encoding)":  "bc3_rgbm",
    "ASTC LDR 4x4":                        "astc_ldr_4x4",
    "ASTC LDR 5x4":                        "astc_ldr_5x4",
    "ASTC LDR 5x5":                        "astc_ldr_5x5",
    "ASTC LDR 6x5":                        "astc_ldr_6x5",
    "ASTC LDR 6x6":                        "astc_ldr_6x6",
    "ASTC LDR 8x5":                        "astc_ldr_8x5",
    "ASTC LDR 8x6":                        "astc_ldr_8x6",
    "ASTC LDR 10x5":                       "astc_ldr_10x5",
    "ASTC LDR 10x6":                       "astc_ldr_10x6",
    "ASTC LDR 8x8":                        "astc_ldr_8x8",
    "ASTC LDR 10x8":                       "astc_ldr_10x8",
    "ASTC LDR 10x10":                      "astc_ldr_10x10",
    "ASTC LDR 12x10":                      "astc_ldr_12x10",
    "ASTC LDR 12x12":                      "astc_ldr_12x12",
    "RGBA (Uncompressed 32-bit Raw)":      "rgb",
}

QUALITY_MAP = {
    "Fast (-fast)":             "fast",
    "Production (-production)": "production",
    "Highest (-highest)":       "highest",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_image_info(path: Path) -> tuple[bool, bool]:
    try:
        with Image.open(path) as img:
            # 1. Check for standard alpha bands (RGBA, LA)
            if "A" in img.getbands():
                # Extract minimum and maximum alpha values found in the image
                alpha_min, _ = img.getchannel("A").getextrema()
                # If the lowest alpha value is less than 255, transparency is actively used
                if alpha_min < 255:
                    return True, True
                return True, False

            # 2. Check for indexed transparency (e.g., GIFs, 8-bit PNGs in 'P' or 'PA' mode)
            transparency = img.info.get("transparency")
            if transparency is not None:
                # In 'P' mode, transparency can be an integer index or a byte array mapping colors
                if img.mode == "P":
                    # Check if the transparent palette index is actually used in the image pixel data
                    # getcolors() returns a list of (count, pixel_value)
                    used_colors = img.getcolors()
                    if used_colors:
                        used_indices = {color[1] for color in used_colors}
                        # If transparency is a byte array (transparency mapping per palette entry)
                        if isinstance(transparency, bytes):
                            for idx in used_indices:
                                if idx < len(transparency) and transparency[idx] < 255:
                                    return True, True
                        # If transparency is a single integer index
                        elif transparency in used_indices:
                            return True, True
                else:
                    # Fallback for alternative transparent metadata structures
                    return True, True

            return True, False
            
    except Exception:
        # Returns False, False if the file is corrupted, unreadable, or not an image
        return False, False
        
def collect_pngs(directory: Path, recursive: bool) -> list[Path]:
    iterator = directory.rglob("*") if recursive else directory.glob("*")
    return sorted(p for p in iterator if p.is_file() and p.suffix.lower() == ".png")

def collect_dds(directory: Path, recursive: bool = True) -> list[Path]:
    iterator = directory.rglob("*") if recursive else directory.glob("*")
    return sorted(p for p in iterator if p.is_file() and p.suffix.lower() == ".dds")

def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                proc.kill()
    except Exception:
        pass

# ── PNG → DDS Worker ──────────────────────────────────────────────────────────

def convert_png_file(
    png: Path,
    source_root: Path,
    out_dir: Path | None,
    mirror_tree: bool,
    nvcompress: str,
    fmt: str,
    quality: str,
    mip_filter: str,
    mip_params: tuple[float, float] | None,
    dithering: bool,
    dither_bits: int,
    gamma: bool,
    normal: bool,
    tonormal: bool,       
    noalpha: bool,        
    nocuda: bool,         
    rangescale: bool,     
    rgbm: bool,           
    nomips: bool,         
    max_mip_count: int | None,   
    min_mip_size: int | None,    
    wrap_repeat: bool,    # -repeat / -clamp
    weight_r: float | None,
    weight_g: float | None,
    weight_b: float | None,
    weight_a: float | None,
    dry_run: bool,
    overwrite: bool,
    delete_source: bool,
    active_processes: set[subprocess.Popen],
    process_lock: threading.Lock,
    cancel_event: threading.Event,
) -> tuple[bool, str, bool]:
    if cancel_event.is_set():
        return False, f"{png.name}  ->  [skipped due to cancellation]", False

    if out_dir:
        if mirror_tree:
            rel = png.relative_to(source_root)
            out = (out_dir / rel).with_suffix(".dds")
        else:
            out = out_dir / png.with_suffix(".dds").name
    else:
        out = png.with_suffix(".dds")

    if out.exists() and not overwrite and not dry_run:
        return False, f"{png.name}  ->  [skipped: {out.name} already exists]", False

    is_valid, has_alpha = get_image_info(png)
    if not is_valid:
        return False, f"{png.name}  ->  [corrupt – image validation failed]", False

    chosen = fmt if fmt != "auto" else ("bc3" if has_alpha else "bc1")
    label  = f"{png.name}  ->  {out.name}  [{chosen.upper()}]"

    if dry_run:
        return True, f"[dry run]  {label}", False

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [nvcompress, f"-{quality}"]

    if nocuda:
        cmd.append("-nocuda")

    # Input type — tonormal takes priority, then explicit normal flag, then format-implied
    if tonormal:
        cmd.append("-tonormal")
    elif normal or chosen in ("bc1n", "bc3n", "bc5", "bc5s", "ati2"):
        cmd.append("-normal")
    elif noalpha:
        cmd.append("-noalpha")
    elif chosen == "bc7":
        cmd.append("-alpha" if has_alpha else "-color")
    elif chosen in ("bc1a", "bc2", "bc3", "bc3_rgbm") or (fmt == "auto" and has_alpha):
        cmd.append("-alpha")
    else:
        cmd.append("-color")

    if dithering and chosen in ("bc1a", "bc2", "bc3"):
        cmd.extend(["-alpha_dithering", str(dither_bits)])

    if gamma:
        cmd.append("-no-mip-gamma-correct")

    if rangescale:
        cmd.append("-rangescale")

    if rgbm:
        cmd.append("-rgbm")

    cmd.append("-repeat" if wrap_repeat else "-clamp")

    if nomips:
        cmd.append("-nomips")
    else:
        if max_mip_count is not None:
            cmd += ["-max-mip-count", str(max_mip_count)]
        if min_mip_size is not None:
            cmd += ["-min-mip-size", str(min_mip_size)]

    cmd += ["-mipfilter", mip_filter]
    if mip_params is not None:
        cmd += ["-param1", str(mip_params[0]), "-param2", str(mip_params[1])]

    if weight_r is not None: cmd += ["-weight_r", f"{weight_r:.2f}"]
    if weight_g is not None: cmd += ["-weight_g", f"{weight_g:.2f}"]
    if weight_b is not None: cmd += ["-weight_b", f"{weight_b:.2f}"]
    if weight_a is not None: cmd += ["-weight_a", f"{weight_a:.2f}"]

    if chosen in ("bc6", "bc6s", "bc7") or chosen.startswith("astc"):
        cmd.append("-dds10")

    cmd += [f"-{chosen}", str(png), str(out)]

    proc: subprocess.Popen | None = None
    try:
        flags       = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, creationflags=flags, startupinfo=startupinfo,
            start_new_session=(os.name != "nt"),
        )

        with process_lock:
            active_processes.add(proc)
            if cancel_event.is_set():
                _kill(proc)
                return False, f"{label}\n         ↳ [aborted]", False

        while proc.poll() is None:
            if cancel_event.is_set():
                _kill(proc)
                return False, f"{label}\n         ↳ [aborted by user]", False
            time.sleep(0.1)

        stdout, stderr = proc.communicate()
        if proc.returncode == 0:
            try:
                shutil.copystat(png, out)
            except Exception:
                pass
            if delete_source and out.exists() and out.stat().st_size > 0:
                png.unlink()
                return True, f"{label}  [PNG deleted]", True
            return True, label, False

        detail = (stderr or stdout).strip().splitlines() or ["unknown error"]
        return False, f"{label}\n         ↳ {detail[0]}", False

    except Exception as e:
        return False, f"{label}\n         ↳ [execution error] {e}", False
    finally:
        if proc is not None:
            with process_lock:
                active_processes.discard(proc)

# ── DDS → PNG Worker ──────────────────────────────────────────────────────────

def convert_dds_file(
    dds: Path,
    source_root: Path,
    out_dir: Path | None,
    mirror_tree: bool,
    nvdecompress: str,
    delete_source: bool,
    overwrite: bool,
    dry_run: bool,
    active_processes: set[subprocess.Popen],
    process_lock: threading.Lock,
    cancel_event: threading.Event,
) -> tuple[bool, str, bool]:
    if cancel_event.is_set():
        return False, f"{dds.name}  ->  [skipped due to cancellation]", False

    if out_dir:
        if mirror_tree:
            rel = dds.relative_to(source_root)
            png_path = (out_dir / rel).with_suffix(".png")
        else:
            png_path = out_dir / dds.with_suffix(".png").name
    else:
        png_path = dds.with_suffix(".png")
    label    = f"{dds.name}  ->  {png_path.name}"

    if png_path.exists() and not overwrite and not dry_run:
        return False, f"{label}  [skipped: PNG already exists]", False

    if dry_run:
        return True, f"[dry run]  {label}", False

    png_path.parent.mkdir(parents=True, exist_ok=True)

    # Use a temp file path to guarantee cleanup
    temp_png = png_path.with_suffix(".temp.tga")
    
    nv_success = False
    error_detail = "Skipped binary pass"

    try:
        if nvdecompress and shutil.which(nvdecompress):
            proc: subprocess.Popen | None = None
            try:
                # Use the temp path for nvdecompress
                cmd = [nvdecompress, str(dds), str(temp_png)]
                flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                startupinfo = None
                if os.name == "nt":
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE

                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, creationflags=flags, startupinfo=startupinfo,
                    start_new_session=(os.name != "nt"),
                )

                with process_lock:
                    active_processes.add(proc)
                    if cancel_event.is_set():
                        _kill(proc)
                        return False, f"{label}\n         ↳ [aborted]", False

                while proc.poll() is None:
                    if cancel_event.is_set():
                        _kill(proc)
                        return False, f"{label}\n         ↳ [aborted by user]", False
                    time.sleep(0.1)

                stdout, stderr = proc.communicate()
                
                # Check if the TGA was created successfully by nvdecompress
                if proc.returncode == 0 and temp_png.exists() and temp_png.stat().st_size > 0:
                    try:
                        # PROPER CONVERSION: Open the TGA and save as a real PNG
                        with Image.open(temp_png) as img:
                            img.save(png_path, "PNG")
                        nv_success = True
                    except Exception as e:
                        error_detail = f"Pillow conversion failed: {e}"
                        nv_success = False
                else:
                    error_detail = (stderr or stdout).strip().splitlines() or ["nvdecompress return check failed"]
                    error_detail = error_detail[0]
            except Exception as e:
                error_detail = str(e)
            finally:
                if proc is not None:
                    with process_lock:
                        active_processes.discard(proc)

        if not nv_success:
            if cancel_event.is_set():
                return False, f"{label}\n         ↳ [aborted]", False
            try:
                with Image.open(dds) as img:
                    img.save(png_path, "PNG")
                nv_success = True
            except Exception as e:
                return False, f"{label}\n         ↳ [extraction error] {e} (Fallback detail: {error_detail})", False

        try:
            shutil.copystat(dds, png_path)
        except Exception:
            pass

        if delete_source and png_path.exists() and png_path.stat().st_size > 0:
            dds.unlink()
            return True, f"{label}  [DDS deleted]", True

        return True, label, False

    finally:
        # Guarantee cleanup of any left-over temp file
        if temp_png.exists():
            temp_png.unlink(missing_ok=True)

# ── Tooltip UI Element ────────────────────────────────────────────────────────

class ToolTip:
    active_tooltips: list["ToolTip"] = []

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget     = widget
        self.text       = text
        self.tipwindow  = None
        widget.bind("<Enter>",    self.show)
        widget.bind("<Leave>",    self.hide)
        widget.bind("<Button-1>", self.hide)
        if isinstance(widget, ttk.Combobox):
            widget.bind("<<ComboboxSelected>>", self.hide, add=True)
            widget.bind("<FocusOut>",           self.hide)

    def show(self, event=None) -> None:
        ToolTip.hide_all()
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        ToolTip.active_tooltips.append(self)
        tk.Label(tw, text=self.text, background=BG3, relief="solid",
                 foreground=FG, borderwidth=1, font=("Segoe UI", 9),
                 justify="left").pack(padx=1, pady=1)

    def hide(self, event=None) -> None:
        if self.tipwindow:
            try:
                self.tipwindow.destroy()
            except Exception:
                pass
            self.tipwindow = None
        if self in ToolTip.active_tooltips:
            ToolTip.active_tooltips.remove(self)

    @classmethod
    def hide_all(cls) -> None:
        for tip in list(cls.active_tooltips):
            tip.hide()

# ── App Window Layer ──────────────────────────────────────────────────────────

class App(TkinterDnD.Tk):
    def __init__(self) -> None:
        try:
            super().__init__()
        except Exception:
            tk.Tk.__init__(self)
            try:
                self.TkdndVersion = TkinterDnD._init_tkdnd(self)
            except AttributeError:
                self.tk.call('package', 'require', 'tkdnd')
                self.TkdndVersion = '2.9'


        self.title("DDS ↔ PNG Texture Converter")
        self.configure(bg=BG)
        self.minsize(860, 780)

        # Centralized worker configuration
        cpu_count = os.cpu_count() or 2
        self._cpu_limit = max(16, cpu_count)
        default_workers = 32 if cpu_count > 32 else max(1, cpu_count // 2)
        self._shared_workers_var = tk.IntVar(value=default_workers)

        self._running        = False
        self._cancel         = threading.Event()
        self._process_lock   = threading.Lock()
        self._active_processes: set[subprocess.Popen] = set()
        self._log_buffer:   list[str] = []
        self._log_file_var  = tk.BooleanVar(value=False)
        self._log_path_var  = tk.StringVar()

        self._apply_styles()
        self._apply_checkbox_images()
        self._build_ui()
        self._setup_drag_and_drop() 
        self._attach_tooltips()
        self._load_config()

        self.after(500, self._detect_nvcompress_capabilities)

        self.bind("<Button-1>",  lambda _: ToolTip.hide_all())
        self.bind("<Configure>", lambda _: ToolTip.hide_all())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._explicit_png_files: list[Path] = []
        self._explicit_dds_files: list[Path] = []

    def _handle_tab_drop(self, event, dir_var: tk.StringVar, out_var: tk.StringVar, target_ext: str) -> None:
        if not event.data:
            return
            
        cleaned = self._clean_dropped_path(event.data)
        if not cleaned:
            return

        path = cleaned[0]
        dir_var.set(path)
        
        if os.path.isfile(path) and not out_var.get().strip():
            out_var.set(os.path.dirname(path))
            
        if os.path.isfile(path) and not path.lower().endswith(target_ext.lower()):
            self._log_warn(f"Warning: Dropped file does not appear to be a {target_ext.upper()} file.")

    def _apply_styles(self) -> None:
        s = ttk.Style(self)
        s.theme_use("clam")
        base = dict(background=BG2, foreground=FG, bordercolor=BORDER,
                    troughcolor=BG4, fieldbackground=BG3,
                    selectbackground=ACCENT, selectforeground="#ffffff", font=FONT)
        s.configure(".", **base)
        s.configure("TFrame",       background=BG2)
        s.configure("TLabel",       background=BG2, foreground=FG,     font=FONT)
        s.configure("Dim.TLabel",   background=BG2, foreground=FG_DIM, font=FONT_SMALL)
        s.configure("Title.TLabel", background=BG,  foreground=FG,     font=FONT_TITLE)
        s.configure("Head.TFrame",  background=BG)
        s.configure("TEntry", fieldbackground=BG3, foreground=FG, insertcolor=FG,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        s.configure("TButton", background=BG4, foreground=FG, bordercolor=BORDER, padding=(8, 4))
        s.map("TButton", background=[("active", "#4a4a4a"), ("disabled", BG3)], foreground=[("disabled", FG_DIM)])
        s.configure("Primary.TButton", background=ACCENT, foreground="#ffffff", font=FONT_BOLD, padding=(16, 6))
        s.map("Primary.TButton", background=[("active", "#4888e8"), ("disabled", BG4)], foreground=[("disabled", FG_DIM)])
        s.configure("Danger.TButton", background="#9c3030", foreground="#ffffff", font=FONT_BOLD, padding=(16, 6))
        s.map("Danger.TButton", background=[("active", "#b03838"), ("disabled", BG4)], foreground=[("disabled", FG_DIM)])
        s.configure("TCombobox", fieldbackground=BG3, background=BG4, foreground=FG, arrowcolor=FG_DIM, bordercolor=BORDER)
        s.map("TCombobox", fieldbackground=[("readonly", BG3)], selectbackground=[("readonly", BG3)], selectforeground=[("readonly", FG)])
        self.option_add("*TCombobox*Listbox.background",       BG3)
        self.option_add("*TCombobox*Listbox.foreground",       FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        s.configure("TSpinbox", fieldbackground=BG3, foreground=FG, arrowcolor=FG_DIM, bordercolor=BORDER, background=BG4)
        s.configure("TCheckbutton", background=BG2, foreground=FG, indicatorcolor=ERROR, indicatorbackground=BG4)
        s.map("TCheckbutton", indicatorcolor=[("selected", ACCENT)], background=[("active", BG2)])
        s.configure("TProgressbar", troughcolor=BG4, background=ACCENT, bordercolor=BG4)
        s.configure("TSeparator",   background=BORDER)
        s.configure("TNotebook", background=BG, bordercolor=BORDER, tabmargins=[2, 2, 0, 0])
        s.configure("TNotebook.Tab", background=BG3, foreground=FG_DIM, padding=(14, 6), font=FONT)
        s.map("TNotebook.Tab", background=[("selected", BG2), ("active", BG4)], foreground=[("selected", FG), ("active", FG)])

    def _apply_checkbox_images(self) -> None:
        size = 13
        def make_img(draw_x: bool) -> tk.PhotoImage:
            img = tk.PhotoImage(width=size, height=size)
            for y in range(size):
                row = []
                for x in range(size):
                    if y == 0 or y == size - 1 or x == 0 or x == size - 1:
                        row.append(BORDER)
                    elif draw_x and 2 <= x <= 10 and 2 <= y <= 10:
                        on_bslash = (x == y) or (x == y + 1)
                        on_slash  = (x + y == 12) or (x + y == 11)
                        row.append(ERROR if (on_bslash or on_slash) else BG4)
                    else:
                        row.append(BG4)
                img.put("{" + " ".join(row) + "}", to=(0, y))
            return img

        self._chk_off = make_img(False)
        self._chk_on  = make_img(True)
        s = ttk.Style(self)
        s.element_create("RedX.Checkbutton.indicator", "image", self._chk_off, ("selected", self._chk_on), padding=(0, 0, 6, 0), sticky="w")
        s.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nsew", "children": [("RedX.Checkbutton.indicator", {"side": "left", "sticky": ""}), ("Checkbutton.focus", {"side": "left", "sticky": "", "children": [("Checkbutton.label", {"sticky": "nsew"})]})]})])

    def _build_ui(self) -> None:
        hdr = ttk.Frame(self, style="Head.TFrame")
        hdr.pack(fill="x")
        inner = ttk.Frame(hdr, style="Head.TFrame")
        inner.pack(fill="x", padx=18, pady=12)
        inner.columnconfigure(1, weight=1)

        grp = ttk.Frame(inner, style="Head.TFrame")
        grp.grid(row=0, column=0, sticky="w")
        ttk.Label(grp, text="DDS ↔ PNG Texture Converter", style="Title.TLabel").pack(side="left")
        ttk.Label(grp, text="  PNG→DDS via nvcompress  ·  DDS→PNG Parallelized Architecture", style="Dim.TLabel").pack(side="left", pady=(2, 0), padx=(10, 0))
        
        self._help_btn = ttk.Button(inner, text="?", width=3, command=self._show_help)
        self._help_btn.grid(row=0, column=2, sticky="e")

        ttk.Separator(self).pack(fill="x")

        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="x", padx=18, pady=(10, 4))
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        tab_p2d = ttk.Frame(self._notebook)
        self._notebook.add(tab_p2d, text="  PNG → DDS  ")
        self._build_png_to_dds_tab(tab_p2d)

        tab_d2p = ttk.Frame(self._notebook)
        self._notebook.add(tab_d2p, text="  DDS → PNG  ")
        self._build_dds_to_png_tab(tab_d2p)

        ttk.Separator(self).pack(fill="x", pady=(6, 0))
        act = ttk.Frame(self)
        act.pack(fill="x", padx=18, pady=10)

        self._go_btn = ttk.Button(act, text="Convert  PNG → DDS", style="Primary.TButton", command=self._start)
        self._go_btn.pack(side="left")

        self._stop_btn = ttk.Button(act, text="Cancel", style="Danger.TButton", command=self._cancel_run, state="disabled")
        self._stop_btn.pack(side="left", padx=(8, 0))

        self._status = ttk.Label(act, text="", style="Dim.TLabel")
        self._status.pack(side="left", padx=(14, 0))

        # ── Right side: log controls + clear ────────────────────────────────
        clr_frame = ttk.Frame(act)
        clr_frame.pack(side="right")

        self._log_chk = ttk.Checkbutton(
            clr_frame, text="Save log",
            variable=self._log_file_var,
            command=self._toggle_log_path)
        self._log_chk.pack(side="left", padx=(0, 4))

        self._log_path_entry = ttk.Entry(
            clr_frame, textvariable=self._log_path_var, width=22, state="disabled")
        self._log_path_entry.pack(side="left", padx=(0, 2))

        self._log_browse_btn = ttk.Button(
            clr_frame, text="…", width=2,
            command=self._browse_log_path, state="disabled")
        self._log_browse_btn.pack(side="left", padx=(0, 8))

        self._clear_btn = ttk.Button(clr_frame, text="Clear log", command=self._clear_log)
        self._clear_btn.pack(side="left")

        self._bar = ttk.Progressbar(self, mode="determinate")
        self._bar.pack(fill="x", padx=18, pady=(0, 8))

        log_wrap = ttk.Frame(self)
        log_wrap.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self._log = tk.Text(log_wrap, bg=BG3, fg=FG, font=FONT_MONO, borderwidth=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, wrap="none", state="disabled")
        self._log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_wrap, orient="vertical", command=self._log.yview)
        sb.pack(side="right", fill="y")
        self._log["yscrollcommand"] = sb.set
        self._log.tag_configure("ok",     foreground=SUCCESS)
        self._log.tag_configure("fail",   foreground=ERROR)
        self._log.tag_configure("warn",   foreground=WARN)
        self._log.tag_configure("header", foreground=ACCENT)
        self._log.tag_configure("dim",    foreground=FG_DIM)

    def _build_png_to_dds_tab(self, parent: ttk.Frame) -> None:
        cfg = ttk.Frame(parent)
        cfg.pack(fill="x", padx=4, pady=10)
        cfg.columnconfigure(1, weight=1)

        # Variables
        self._dir_var = tk.StringVar()
        self._out_var = tk.StringVar()
        self._nv_var  = tk.StringVar(value="nvcompress")

        # --- Row 0-2: Inputs ---
        ttk.Label(cfg, text="Source target").grid(row=0, column=0, sticky="w", pady=3)
        self._dir_entry = ttk.Entry(cfg, textvariable=self._dir_var)
        self._dir_entry.grid(row=0, column=1, sticky="ew", padx=(10, 6))
        p2d_src_btns = ttk.Frame(cfg)
        p2d_src_btns.grid(row=0, column=2, sticky="ew")
        self._dir_btn = ttk.Button(p2d_src_btns, text="Folder…", command=self._browse_dir)
        self._dir_btn.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self._file_btn = ttk.Button(p2d_src_btns, text="File…", command=self._browse_src_file)
        self._file_btn.pack(side="left", fill="x", expand=True)

        ttk.Label(cfg, text="Output folder").grid(row=1, column=0, sticky="w", pady=3)
        self._out_entry = ttk.Entry(cfg, textvariable=self._out_var)
        self._out_entry.grid(row=1, column=1, sticky="ew", padx=(10, 6))
        self._out_btn = ttk.Button(cfg, text="Browse…", command=self._browse_out)
        self._out_btn.grid(row=1, column=2, sticky="ew")

        ttk.Label(cfg, text="nvcompress path").grid(row=2, column=0, sticky="w", pady=3)
        self._nv_entry = ttk.Entry(cfg, textvariable=self._nv_var)
        self._nv_entry.grid(row=2, column=1, sticky="ew", padx=(10, 6))
        nv_btns = ttk.Frame(cfg)
        nv_btns.grid(row=2, column=2, sticky="ew")
        self._nv_test_btn = ttk.Button(nv_btns, text="Test", command=self._test_nvcompress)
        self._nv_test_btn.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self._nv_browse_btn = ttk.Button(nv_btns, text="Browse…", command=self._browse_nv)
        self._nv_browse_btn.pack(side="left", fill="x", expand=True)

        # --- Row 3: Format & Quality ---
        opt = ttk.Frame(cfg)
        opt.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        row3 = ttk.Frame(opt)
        row3.pack(fill="x", pady=(0, 8))
        
        # Format
        ttk.Label(row3, text="Format").pack(side="left")
        self._fmt_var = tk.StringVar(value="Auto (BC1/BC3 Fallback)")
        self._fmt_cb = ttk.Combobox(row3, textvariable=self._fmt_var, values=list(FMT_MAP.keys()), state="readonly", width=32)
        self._fmt_cb.pack(side="left", padx=(6, 16))

        # Mip filter
        ttk.Label(row3, text="Mip filter").pack(side="left")
        self._mip_var = tk.StringVar(value="kaiser")
        self._mip_cb = ttk.Combobox(row3, textvariable=self._mip_var, values=FILTERS, state="readonly", width=12)
        self._mip_cb.pack(side="left", padx=(6, 16))
        self._mip_cb.bind("<<ComboboxSelected>>", self._on_filter_changed)

        # Quality
        ttk.Label(row3, text="Quality").pack(side="left")
        self._quality_var = tk.StringVar(value="Production (-production)")
        self._quality_cb = ttk.Combobox(row3, textvariable=self._quality_var, values=list(QUALITY_MAP.keys()), state="readonly", width=18)
        self._quality_cb.pack(side="left", padx=(6, 16))

        # Workers
        self._workers_spin = ttk.Spinbox(row3, from_=1, to=self._cpu_limit, textvariable=self._shared_workers_var, width=4)
        self._workers_spin.pack(side="right")
        ttk.Label(row3, text="Threads").pack(side="right", padx=(6, 16))

        # --- Row 4: File Management Flags ---
        row4 = ttk.Frame(opt)
        row4.pack(fill="x", anchor="w", pady=(0, 8))

        self._recursive_var = tk.BooleanVar(value=True)
        self._recursive_chk = ttk.Checkbutton(row4, text="Recursive scan", variable=self._recursive_var, command=self._toggle_mirror)
        self._recursive_chk.pack(side="left", padx=(0, 16))
        
        self._mirror_var = tk.BooleanVar(value=True)
        self._mirror_chk = ttk.Checkbutton(row4, text="Mirror structure", variable=self._mirror_var)
        self._mirror_chk.pack(side="left", padx=(0, 16))
        
        self._overwrite_var = tk.BooleanVar(value=False)
        self._overwrite_chk = ttk.Checkbutton(row4, text="Overwrite existing", variable=self._overwrite_var)
        self._overwrite_chk.pack(side="left", padx=(0, 16))
        
        self._p2p_delete_var = tk.BooleanVar(value=False)
        self._p2p_delete_chk = ttk.Checkbutton(row4, text="Delete source PNG", variable=self._p2p_delete_var)
        self._p2p_delete_chk.pack(side="left", padx=(0, 16))
        
        self._dryrun_var = tk.BooleanVar(value=False)
        self._dryrun_chk = ttk.Checkbutton(row4, text="Dry run mode", variable=self._dryrun_var)
        self._dryrun_chk.pack(side="left")

        # --- Row 5: Texture Processing Flags ---
        row5 = ttk.Frame(opt)
        row5.pack(fill="x", anchor="w", pady=(0, 8))

        self._dither_var = tk.BooleanVar(value=False)
        self._dither_chk = ttk.Checkbutton(row5, text="Alpha dithering", variable=self._dither_var, command=self._toggle_dithering)
        self._dither_chk.pack(side="left", padx=(0, 4))
        
        self._dither_bits_var = tk.IntVar(value=4)
        self._dither_bits_spin = ttk.Spinbox(row5, from_=1, to=8, textvariable=self._dither_bits_var, width=3, state="disabled")
        self._dither_bits_spin.pack(side="left", padx=(0, 16))

        self._gamma_var = tk.BooleanVar(value=False)
        self._gamma_chk = ttk.Checkbutton(row5, text="No mip gamma correction", variable=self._gamma_var)
        self._gamma_chk.pack(side="left", padx=(0, 16))
        
        self._normal_var = tk.BooleanVar(value=False)
        self._normal_chk = ttk.Checkbutton(row5, text="Normalization per mip", variable=self._normal_var)
        self._normal_chk.pack(side="left", padx=(0, 16))

        # --- Row 6: Advanced Pipeline ---
        row6 = ttk.Frame(opt)
        row6.pack(fill="x", anchor="w", pady=(0, 8))

        self._tonormal_var = tk.BooleanVar(value=False)
        self._tonormal_chk = ttk.Checkbutton(row6, text="Convert to normal", variable=self._tonormal_var)
        self._tonormal_chk.pack(side="left", padx=(0, 16))
        
        self._noalpha_var = tk.BooleanVar(value=False)
        self._noalpha_chk = ttk.Checkbutton(row6, text="Ignore alpha", variable=self._noalpha_var)
        self._noalpha_chk.pack(side="left", padx=(0, 16))
        
        self._rangescale_var = tk.BooleanVar(value=False)
        self._rangescale_chk = ttk.Checkbutton(row6, text="Range scale", variable=self._rangescale_var)
        self._rangescale_chk.pack(side="left", padx=(0, 16))
        
        self._nocuda_var = tk.BooleanVar(value=False)
        self._nocuda_chk = ttk.Checkbutton(row6, text="No CUDA", variable=self._nocuda_var)
        self._nocuda_chk.pack(side="left", padx=(0, 16))
        
        self._rgbm_var = tk.BooleanVar(value=False)
        self._rgbm_chk = ttk.Checkbutton(row6, text="RGBM encode", variable=self._rgbm_var)
        self._rgbm_chk.pack(side="left")

        # --- Row 7: Mipmap Controls ---
        row7 = ttk.Frame(opt)
        row7.pack(fill="x", anchor="w", pady=(0, 8))

        self._nomips_var = tk.BooleanVar(value=False)
        self._nomips_chk = ttk.Checkbutton(row7, text="No mipmaps", variable=self._nomips_var, command=self._toggle_nomips)
        self._nomips_chk.pack(side="left", padx=(0, 12))
        
        self._use_max_mip_count_var = tk.BooleanVar(value=False)
        self._use_max_mip_count_chk = ttk.Checkbutton(row7, text="Max mip count", variable=self._use_max_mip_count_var, command=self._toggle_mip_overrides)
        self._use_max_mip_count_chk.pack(side="left", padx=(0, 4))
        self._max_mip_count_var = tk.IntVar(value=0)
        self._max_mip_count_spin = ttk.Spinbox(row7, from_=0, to=16, textvariable=self._max_mip_count_var, width=4, state="disabled")
        self._max_mip_count_spin.pack(side="left", padx=(0, 12))

        self._use_min_mip_size_var = tk.BooleanVar(value=False)
        self._use_min_mip_size_chk = ttk.Checkbutton(row7, text="Min mip size", variable=self._use_min_mip_size_var, command=self._toggle_mip_overrides)
        self._use_min_mip_size_chk.pack(side="left", padx=(0, 4))
        self._min_mip_size_var = tk.IntVar(value=1)
        self._min_mip_size_spin = ttk.Spinbox(row7, from_=1, to=4096, textvariable=self._min_mip_size_var, width=6, state="disabled")
        self._min_mip_size_spin.pack(side="left", padx=(0, 12))
        
        ttk.Label(row7, text="Wrap").pack(side="left", padx=(8, 4))
        self._wrap_var = tk.StringVar(value="clamp")
        self._wrap_cb = ttk.Combobox(row7, textvariable=self._wrap_var, values=["clamp", "repeat"], state="readonly", width=7)
        self._wrap_cb.pack(side="left")

        # --- Row 8: Filter Parameters ---
        row8 = ttk.Frame(opt)
        row8.pack(fill="x", anchor="w", pady=(0, 8))
        
        self._use_params_var = tk.BooleanVar(value=False)
        self._param_chk = ttk.Checkbutton(row8, text="Override filter params", variable=self._use_params_var, command=self._toggle_param_entries)
        self._param_chk.pack(side="left", padx=(0, 10))
        
        self._p1_label_var = tk.StringVar(value="Param 1")
        ttk.Label(row8, textvariable=self._p1_label_var).pack(side="left")
        self._param1_var = tk.DoubleVar(value=3.0)
        self._p1_entry = ttk.Spinbox(row8, from_=0.1, to=10.0, increment=0.1, format="%.3f", textvariable=self._param1_var, width=7, state="disabled")
        self._p1_entry.pack(side="left", padx=(6, 16))

        self._p2_label_var = tk.StringVar(value="Param 2")
        ttk.Label(row8, textvariable=self._p2_label_var).pack(side="left")
        self._param2_var = tk.DoubleVar(value=1.0)
        self._p2_entry = ttk.Spinbox(row8, from_=0.1, to=10.0, increment=0.1, format="%.3f", textvariable=self._param2_var, width=7, state="disabled")
        self._p2_entry.pack(side="left", padx=(6, 16))

        self._param_note = ttk.Label(row8, text="", style="Dim.TLabel")
        self._param_note.pack(side="left", padx=(4, 0))

        # --- Row 9: Weights ---
        row9 = ttk.Frame(opt)
        row9.pack(fill="x", anchor="w", pady=(4, 0))
        ttk.Label(row9, text="Weights").pack(side="left", padx=(0, 8))

        # Helper to create channel toggle and spinbox
        def create_channel(parent, label_text, var_toggle, var_val):
            frame = ttk.Frame(parent)
            frame.pack(side="left", padx=(0, 10))
    
            # Checkbox (The Toggle)
            chk = ttk.Checkbutton(frame, text=label_text, variable=var_toggle, 
                          command=lambda: spin.configure(state="normal" if var_toggle.get() else "disabled"))
            chk.pack(side="left")
    
            # Spinbox (The Value)
            spin = ttk.Spinbox(frame, from_=0.0, to=4.0, increment=0.1, format="%.2f", 
                       textvariable=var_val, width=5, state="disabled")
            spin.pack(side="left", padx=(2, 0))
            return spin

        # Variables
        self._use_r_var = tk.BooleanVar(value=False)
        self._weight_r_var = tk.DoubleVar(value=1.0)
        self._weight_r_spin = create_channel(row9, "R", self._use_r_var, self._weight_r_var)

        self._use_g_var = tk.BooleanVar(value=False)
        self._weight_g_var = tk.DoubleVar(value=1.0)
        self._weight_g_spin = create_channel(row9, "G", self._use_g_var, self._weight_g_var)

        self._use_b_var = tk.BooleanVar(value=False)
        self._weight_b_var = tk.DoubleVar(value=1.0)
        self._weight_b_spin = create_channel(row9, "B", self._use_b_var, self._weight_b_var)

        self._use_a_var = tk.BooleanVar(value=False)
        self._weight_a_var = tk.DoubleVar(value=1.0)
        self._weight_a_spin = create_channel(row9, "A", self._use_a_var, self._weight_a_var)
    
    def _on_filter_changed(self, event=None, load_defaults: bool = True) -> None:
        if not hasattr(self, "_param_chk"):
            return
        filter_name = self._mip_var.get()
        meta = FILTER_PARAMS.get(filter_name)
        if meta is None:
            self._use_params_var.set(False)
            self._param_chk.configure(state="disabled")
            self._p1_entry.configure(state="disabled")
            self._p2_entry.configure(state="disabled")
            self._p1_label_var.set("Param 1")
            self._p2_label_var.set("Param 2")
            self._param_note.configure(text="(no params for this filter)")
        else:
            p1l, p1mn, p1mx, p1df, p2l, p2mn, p2mx, p2df = meta
            self._param_chk.configure(state="normal")
            self._p1_label_var.set(f"Param 1 ({p1l})")
            self._p2_label_var.set(f"Param 2 ({p2l})")
            self._param_note.configure(text="")
            self._p1_entry.configure(from_=p1mn, to=p1mx)
            self._p2_entry.configure(from_=p2mn, to=p2mx)
            if load_defaults:
                self._param1_var.set(p1df)
                self._param2_var.set(p2df)
            self._toggle_param_entries()

    def _build_dds_to_png_tab(self, parent: ttk.Frame) -> None:
        cfg = ttk.Frame(parent)
        cfg.pack(fill="x", padx=4, pady=10)
        cfg.columnconfigure(1, weight=1)

        self._d2p_dir_var  = tk.StringVar()
        self._d2p_out_var  = tk.StringVar()
        self._nvd_var      = tk.StringVar(value="nvdecompress")

        ttk.Label(cfg, text="Source target").grid(row=0, column=0, sticky="w", pady=3)
        self._d2p_dir_entry = ttk.Entry(cfg, textvariable=self._d2p_dir_var)
        self._d2p_dir_entry.grid(row=0, column=1, sticky="ew", padx=(10, 6))
        d2p_src_btns = ttk.Frame(cfg)
        d2p_src_btns.grid(row=0, column=2, sticky="ew")
        
        self._d2p_dir_btn = ttk.Button(d2p_src_btns, text="Folder…", command=self._d2p_browse_dir)
        self._d2p_dir_btn.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self._file_d2p_btn = ttk.Button(d2p_src_btns, text="File…", command=self._browse_d2p_file)
        self._file_d2p_btn.pack(side="left", fill="x", expand=True)

        ttk.Label(cfg, text="Output folder").grid(row=1, column=0, sticky="w", pady=3)
        self._d2p_out_entry = ttk.Entry(cfg, textvariable=self._d2p_out_var)
        self._d2p_out_entry.grid(row=1, column=1, sticky="ew", padx=(10, 6))
        
        self._d2p_out_btn = ttk.Button(cfg, text="Browse…", command=self._d2p_browse_out)
        self._d2p_out_btn.grid(row=1, column=2, sticky="ew")

        ttk.Label(cfg, text="nvdecompress path").grid(row=2, column=0, sticky="w", pady=3)
        self._nvd_entry = ttk.Entry(cfg, textvariable=self._nvd_var)
        self._nvd_entry.grid(row=2, column=1, sticky="ew", padx=(10, 6))
        nvd_btns = ttk.Frame(cfg)
        nvd_btns.grid(row=2, column=2, sticky="ew")
        
        self._nvd_test_btn = ttk.Button(nvd_btns, text="Test", command=self._test_nvdecompress)
        self._nvd_test_btn.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self._nvd_browse_btn = ttk.Button(nvd_btns, text="Browse…", command=self._browse_nvd)
        self._nvd_browse_btn.pack(side="left", fill="x", expand=True)

        opt = ttk.Frame(cfg)
        opt.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 4))

        # Top options row: left checkboxes, right workers
        row_top = ttk.Frame(opt)
        row_top.pack(fill="x", pady=(10, 0))

        # LEFT SIDE: checkboxes
        left_opts = ttk.Frame(row_top)
        left_opts.pack(side="left", anchor="w")

        self._d2p_recursive_var  = tk.BooleanVar(value=True)
        self._d2p_mirror_var    = tk.BooleanVar(value=True)
        self._d2p_delete_var    = tk.BooleanVar(value=False)
        self._d2p_overwrite_var = tk.BooleanVar(value=False)
        self._d2p_dryrun_var    = tk.BooleanVar(value=False)

        self._d2p_recursive_chk = ttk.Checkbutton(
            left_opts,
            text="Recursive scan",
            variable=self._d2p_recursive_var,
            command=self._toggle_d2p_mirror
        )
        self._d2p_recursive_chk.pack(
            side="left",
            padx=(0, 16)
        )

        self._d2p_mirror_chk = ttk.Checkbutton(
            left_opts,
            text="Mirror structure",
            variable=self._d2p_mirror_var
        )
        self._d2p_mirror_chk.pack(
            side="left",
            padx=(0, 16)
        )

        self._d2p_overwrite_chk = ttk.Checkbutton(
            left_opts,
            text="Overwrite existing",
            variable=self._d2p_overwrite_var
        )
        self._d2p_overwrite_chk.pack(
            side="left",
            padx=(0, 16)
        )

        self._d2p_delete_chk = ttk.Checkbutton(
            left_opts,
            text="Delete source DDS",
            variable=self._d2p_delete_var
        )
        self._d2p_delete_chk.pack(
            side="left",
            padx=(0, 16)
        )

        self._d2p_dryrun_chk = ttk.Checkbutton(
            left_opts,
            text="Dry run mode",
            variable=self._d2p_dryrun_var
        )
        self._d2p_dryrun_chk.pack(
            side="left"
        )

        # RIGHT SIDE: workers
        right_opts = ttk.Frame(row_top)
        right_opts.pack(
            side="right",
            anchor="e"
        )

        ttk.Label(
            right_opts,
            text="Threads"
        ).pack(
            side="left",
            padx=(16, 6)
        )

        self._d2p_workers_spin = ttk.Spinbox(
            right_opts,
            from_=1,
            to=self._cpu_limit,
            textvariable=self._shared_workers_var,
            width=4
        )

        self._d2p_workers_spin.pack(
            side="left"
        )

    # ── Tooltip Instantiation Connection ──────────────────────────────────────

    def _attach_tooltips(self) -> None:
        # Global UI Elements
        ToolTip(self._help_btn,           "Open the user guide.")
        ToolTip(self._go_btn,             "Start converting files in the active tab.")
        ToolTip(self._stop_btn,           "Cancel the running conversion and terminate any active nvcompress processes.")
        ToolTip(self._clear_btn,          "Clear the log output and reset the progress bar.")
        ToolTip(self._log_chk,            "Write the full log to a file when the run completes.")
        ToolTip(self._log_path_entry,     "Path for the saved log file. Leave blank to auto-generate a timestamped file next to the config.")
        ToolTip(self._log_browse_btn,     "Choose where to save the log file.")

        # Tab 1: PNG → DDS
        ToolTip(self._dir_entry,          "Source folder or single PNG file to convert.")
        ToolTip(self._dir_btn,            "Browse for a source folder.")
        ToolTip(self._file_btn,           "Browse for a single source PNG file.")
        ToolTip(self._out_entry,          "Output folder for DDS files. Leave blank to write alongside the source PNGs.")
        ToolTip(self._out_btn,            "Browse for an output folder.")
        ToolTip(self._nv_entry,           "Path to the nvcompress executable.")
        ToolTip(self._nv_test_btn,        "Test that nvcompress is found and working, and check which formats it supports.")
        ToolTip(self._nv_browse_btn,      "Browse for the nvcompress executable.")
        ToolTip(self._fmt_cb,             "DDS compression format. Auto picks BC1 (opaque) or BC3 (alpha). Use BC7 for high-quality RGBA.")
        ToolTip(self._quality_cb,         "Higher quality is slower: Fast compression (-fast). Production compression (higher/slower than default)(-production). Highest-quality compression.(-highest)")
        ToolTip(self._mip_cb,             "Filter used when generating mipmap levels.")
        ToolTip(self._workers_spin,       "Number of parallel nvcompress jobs. Higher uses more CPU and RAM.")
        ToolTip(self._recursive_chk,      "Search all subdirectories for PNG files.")
        ToolTip(self._mirror_chk,         "Recreate the source folder structure inside the output folder.")
        ToolTip(self._overwrite_chk,      "Replace existing DDS files instead of skipping them.")
        ToolTip(self._p2p_delete_chk,     "⚠ Delete the source PNG after a successful DDS write.")
        ToolTip(self._dither_chk,         "Apply alpha dithering to reduce banding on transparent edges (-alpha_dithering).")
        ToolTip(self._dither_bits_spin,   "Number of bits to use for alpha dithering (typically 4 or 8).")
        ToolTip(self._gamma_chk,          "Disable gamma correction for mipmap generation (default: only for normal maps)(-no-mip-gamma-correct).")
        ToolTip(self._normal_chk,         "Normal map normalization per mip ensures that normal vectors in mipmaps maintain their correct unit length (-normal).")
        ToolTip(self._tonormal_chk,       "Convert the input image into a normal map before compression (-tonormal).")
        ToolTip(self._noalpha_chk,        "Treat the image as having no alpha, even if one is present (-noalpha).")
        ToolTip(self._rangescale_chk,     "Scale the image to use the full colour range before compression (-rangescale).")
        ToolTip(self._nocuda_chk,         "Disable CUDA acceleration and use the CPU compressor only (-nocuda).")
        ToolTip(self._rgbm_chk,           "Pre-encode the image into RGBM format before compression (-rgbm).")
        ToolTip(self._nomips_chk,         "Disable mipmap generation entirely. Disables the count and size controls (-nomips).")
        ToolTip(self._max_mip_count_spin, "Maximum number of mipmaps. 0 and 1 are the same as -nomips; 2 generates the base mip and one more; and so on. (-max-mip-count).")
        ToolTip(self._min_mip_size_spin,  "Minimum mipmap size; avoids generating mips whose width or height is smaller than this number. (default: 1)(-min-mip-size).")
        ToolTip(self._wrap_cb,            "Texture wrapping mode for mipmap edge sampling: clamp (default) or repeat (-clamp / -repeat).")
        ToolTip(self._dryrun_chk,         "Simulate the conversion without writing any files.")
        ToolTip(self._param_chk,          "Manually override the mipmap filter's math parameters.")
        ToolTip(self._p1_entry,           "Primary filter parameter (e.g. Kaiser Width, Mitchell-Netravali B).")
        ToolTip(self._p2_entry,           "Secondary filter parameter (e.g. Kaiser Stretch, Mitchell-Netravali C).")
        ToolTip(self._weight_r_spin,      "Weight of R (Red) channel, default is 1. (-weight_r).")
        ToolTip(self._weight_g_spin,      "Weight of G (Green) channel, default is 1. (-weight_g).")
        ToolTip(self._weight_b_spin,      "Weight of B (Blue) channel, default is 1. (-weight_b)")
        ToolTip(self._weight_a_spin,      "Weight of A (Alpha) channel, default is 1 when alpha is used, overwritten to 0 when alpha is not used.(-weight_a)")

        # Tab 2: DDS → PNG
        ToolTip(self._d2p_dir_entry,      "Source folder or single DDS file to convert.")
        ToolTip(self._d2p_dir_btn,        "Browse for a source folder.")
        ToolTip(self._file_d2p_btn,       "Browse for a single source DDS file.")
        ToolTip(self._d2p_out_entry,      "Output folder for PNG files. Leave blank to write alongside the source DDS files.")
        ToolTip(self._d2p_out_btn,        "Browse for an output folder.")
        ToolTip(self._nvd_entry,          "Path to the nvdecompress executable (used as primary decoder, falls back to Pillow).")
        ToolTip(self._nvd_test_btn,       "Test that nvdecompress is found and working.")
        ToolTip(self._nvd_browse_btn,     "Browse for the nvdecompress executable.")
        ToolTip(self._d2p_recursive_chk,  "Search all subdirectories for DDS files.")
        ToolTip(self._d2p_mirror_chk,     "Recreate the source folder structure inside the output folder.")
        ToolTip(self._d2p_delete_chk,     "⚠ Delete the source DDS after a successful PNG write.")
        ToolTip(self._d2p_overwrite_chk,  "Replace existing PNG files instead of skipping them.")
        ToolTip(self._d2p_dryrun_chk,     "Simulate the extraction without writing any files.")
        ToolTip(self._d2p_workers_spin,   "Number of parallel conversion jobs. Higher uses more CPU and RAM.")

    # ── Drag and Drop Event Infrastructure ────────────────────────────────────

    def _setup_drag_and_drop(self) -> None:
        # Register the Entry widgets individually (keeps old behavior working)
        self._dir_entry.drop_target_register(DND_FILES)
        self._dir_entry.dnd_bind("<<Drop>>", self._on_png_tab_drop)
        self._d2p_dir_entry.drop_target_register(DND_FILES)
        self._d2p_dir_entry.dnd_bind("<<Drop>>", self._on_dds_tab_drop)

        # Register the parent window instance itself for global drop capture
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self._on_global_window_drop)

    def _clean_dropped_path(self, raw_path: str) -> list[str]:
        path_str = raw_path.strip()
        
        # Safely parse Tk multi-file string syntax
        paths = re.findall(r'\{([^}]+)\}|(\S+)', path_str)
        extracted_paths = [p[0] if p[0] else p[1] for p in paths if p[0] or p[1]]
        
        # Normalize all extracted paths
        normalized_paths = []
        for p in extracted_paths:
            if p.startswith('"') and p.endswith('"'): p = p[1:-1]
            elif p.startswith("'") and p.endswith("'"): p = p[1:-1]
            normalized_paths.append(os.path.normpath(p))
            
        return normalized_paths

    def _on_global_window_drop(self, event) -> None:
        if not event.data:
            return
        
        cleaned_paths = self._clean_dropped_path(event.data)
        if not cleaned_paths:
            return
            
        current_tab = self._notebook.index("current")
        
        # Check if it's a multi-file selection or a single directory
        first_path = cleaned_paths[0]
        is_multi_file = len(cleaned_paths) > 1 or os.path.isfile(first_path)
        
        if is_multi_file:
            # Find the common directory folder of the dropped items
            common_dir = os.path.dirname(first_path) if os.path.isfile(first_path) else first_path
        else:
            common_dir = first_path

        if current_tab == 0:
            # PNG -> DDS Tab
            valid_files = []
            for p in cleaned_paths:
                if os.path.isfile(p) and os.path.splitext(p)[1].lower() == ".png":
                    valid_files.append(Path(p))
            
            if os.path.isfile(first_path) and not valid_files:
                self._log_warn("Rejected drop: No valid .png files found in selection.")
                return
                
            self._dir_var.set(common_dir)
            if not self._out_var.get().strip():
                self._out_var.set(common_dir)
                
            if len(cleaned_paths) > 1:
                self._explicit_png_files = valid_files
                self._log_line(f"🎯 Staged {len(valid_files)} explicit PNG targets from folder: {os.path.basename(common_dir)}", "header")
            else:
                self._explicit_png_files = [] # Reset to normal behavior if it's a folder/single file
                self._log_line(f"🎯 Dropped target into PNG → DDS workflow: {os.path.basename(first_path)}", "header")
                
        else:
            # DDS -> PNG Tab
            valid_files = []
            for p in cleaned_paths:
                if os.path.isfile(p) and os.path.splitext(p)[1].lower() == ".dds":
                    valid_files.append(Path(p))
            
            if os.path.isfile(first_path) and not valid_files:
                self._log_warn("Rejected drop: No valid .dds files found in selection.")
                return
                
            self._d2p_dir_var.set(common_dir)
            if not self._d2p_out_var.get().strip():
                self._d2p_out_var.set(common_dir)
                
            if len(cleaned_paths) > 1:
                self._explicit_dds_files = valid_files
                self._log_line(f"🎯 Staged {len(valid_files)} explicit DDS targets from folder: {os.path.basename(common_dir)}", "header")
            else:
                self._explicit_dds_files = []
                self._log_line(f"🎯 Dropped target into DDS → PNG workflow: {os.path.basename(first_path)}", "header")

    def _on_png_tab_drop(self, event) -> None:
        if event.data:
            cleaned = self._clean_dropped_path(event.data)
            # Re-using logic: set directory based on first item
            path = cleaned[0]
            self._dir_var.set(path)
            if os.path.isfile(path) and not self._out_var.get().strip():
                self._out_var.set(os.path.dirname(path))

    def _on_dds_tab_drop(self, event) -> None:
        if event.data:
            cleaned = self._clean_dropped_path(event.data)
            path = cleaned[0]
            self._d2p_dir_var.set(path)
            if os.path.isfile(path) and not self._d2p_out_var.get().strip():
                self._d2p_out_var.set(os.path.dirname(path))

    # ── Dynamic Format Capability Detection (Fixed Stream Capture) ────────────

    def _detect_nvcompress_capabilities(self, show_alerts: bool = False) -> list[str]:
        """Queries the specified binary to verify exactly which compression formats are valid."""
        exe = self._nv_var.get().strip()
        if exe == "nvcompress":
            resolved = self.find_nvcompress()
            if not resolved:
                if show_alerts:
                    messagebox.showerror("Error", "Could not locate 'nvcompress' binary to analyze capabilities.")
                return list(FMT_MAP.keys())
            exe = resolved

        # Fallback modes always considered baseline active
        supported_modes: set[str] = {"auto", "bc1", "bc1a", "bc2", "bc3", "rgb"}
        
        try:
            # Capture strictly as raw binary bytes to avoid Windows console decode exceptions
            res = subprocess.run([exe, "-help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
            help_bytes = (res.stderr or b"") + (res.stdout or b"")
            
            # Scrape binary content using raw byte arrays
            if b"bc4" in help_bytes or b"BC4" in help_bytes:  supported_modes.update(["bc4", "bc4s"])
            if b"bc5" in help_bytes or b"BC5" in help_bytes:  supported_modes.update(["bc5", "bc5s", "ati2"])
            if b"bc6" in help_bytes or b"BC6" in help_bytes:  supported_modes.update(["bc6", "bc6s"])
            if b"bc7" in help_bytes or b"BC7" in help_bytes:  supported_modes.add("bc7")
            if b"bc1n" in help_bytes or b"BC1n" in help_bytes: supported_modes.add("bc1n")
            if b"bc3n" in help_bytes or b"BC3n" in help_bytes: supported_modes.add("bc3n")
            if b"astc" in help_bytes or b"ASTC" in help_bytes:
                for k, v in FMT_MAP.items():
                    if v.startswith("astc"): supported_modes.add(v)
        except Exception:
            return list(FMT_MAP.keys())

        valid_ui_list = []
        for ui_label, format_code in FMT_MAP.items():
            if format_code in supported_modes:
                valid_ui_list.append(ui_label)

        current_selection = self._fmt_var.get()
        self._fmt_cb.configure(values=valid_ui_list)
        
        if current_selection not in valid_ui_list:
            self._fmt_var.set("Auto (BC1/BC3 Fallback)")
            if show_alerts:
                messagebox.showwarning(
                    "Format Reset", 
                    f"The chosen compression profile ('{current_selection}') is not supported by "
                    "your version of nvcompress.\n\nThe layout format drop-down has defaulted to compatible profiles."
                )
                
        return valid_ui_list

    # ──────────────────────────────────────────────────────────────────────────

    def _show_help(self) -> None:
        win = tk.Toplevel(self)
        win.title("Help / Guide")
        win.minsize(600, 500)
        win.transient(self)
        win.grab_set()

        # Container to hold text and scrollbar
        container = ttk.Frame(win)
        container.pack(expand=True, fill="both", padx=10, pady=10)

        # Scrollbar
        sb = ttk.Scrollbar(container, orient="vertical")
        sb.pack(side="right", fill="y")

        # Text area
        txt = tk.Text(container, bg=BG3, fg=FG, font=("Segoe UI", 10), wrap="word", 
                      borderwidth=0, highlightthickness=0, padx=12, pady=10, 
                      yscrollcommand=sb.set)
        txt.pack(side="left", expand=True, fill="both")
        sb.config(command=txt.yview)

        if os.name == "nt":
            cfg_loc = "%APPDATA%\\DDSConverter\\config.json"
        else:
            cfg_loc = "~/.config/DDSConverter/config.json"

        txt.insert("1.0", (
            "DDS ↔ PNG Texture Converter  ·  User Guide\n\n"

            "── Drag & Drop ─────────────────────────────────\n"
            "You can drag files or folders directly onto the converter window instead of using the Browse buttons.\n\n"
            "  • Drop a single folder  →  sets the source field to that folder and scans it for files.\n"
            "  • Drop a single file    →  sets the source field to that file for a one-shot conversion.\n"
            "  • Drop multiple files   →  the converter stages only those specific files as targets, "
            "ignoring everything else in the folder. The source field will show their common parent folder.\n\n"
            "The window detects which tab is active and routes the drop accordingly — PNG files go to "
            "PNG → DDS, DDS files go to DDS → PNG. Drops containing the wrong file type are rejected "
            "with a warning.\n\n"

            "── PNG → DDS ───────────────────────────────────\n"
            "1. Set the source using Browse, File…, or drag & drop. This can be a folder or a single PNG.\n\n"
            "2. Set an Output folder, or leave it blank to write DDS files directly alongside the source PNGs.\n\n"
            "3. Format — Auto picks BC1 for opaque images and BC3 for images with transparency. "
            "You can override this manually. BC7 gives the best quality for RGBA textures. "
            "BC5 is suited for normal maps. The format list is filtered to only show what your "
            "installed version of nvcompress actually supports.\n\n"
            "4. Mirror structure — when enabled alongside Recursive scan, the subfolder layout of "
            "your source is recreated inside the output folder. Without it, all DDS files are written "
            "flat into the output root.\n\n"
            "5. Workers — controls how many files are compressed in parallel. Higher values speed up "
            "large batches but increase CPU and RAM usage. Defaults to half your logical core count.\n\n"
            "6. Dry run — logs what would happen without writing any files. Useful for checking "
            "settings before a large batch.\n\n"
            "7. Delete source PNG — removes the original PNG only after a DDS has been successfully "
            "written and verified as non-zero. Use with care.\n\n"

            "── DDS → PNG ───────────────────────────────────\n"
            "8. Set the source using Browse, File…, or drag & drop. This can be a folder or a single DDS.\n\n"
            "9. The converter first attempts to decode each DDS using nvdecompress for maximum "
            "compatibility, then automatically falls back to Pillow if nvdecompress is unavailable "
            "or fails on a particular file. All output is saved as RGBA PNG.\n\n"
            "10. Mirror structure works the same as in PNG → DDS — the source subfolder hierarchy "
            "is recreated inside the output folder when both Recursive scan and Mirror structure are on.\n\n"
            "11. Delete source DDS — removes the original DDS only after a PNG has been successfully "
            "written and verified as non-zero. Use with care.\n\n"

            "── Log File ────────────────────────────────────\n"
            "12. Enable Save log in the toolbar to write the full conversion log to a file when the "
            "run finishes. Click … to choose a save location, or leave the path blank to have a "
            "timestamped log file generated automatically next to the config file.\n\n"

            "── General ─────────────────────────────────────\n"
            "13. Cancel stops the run as soon as possible. For PNG → DDS, any active nvcompress "
            "processes are force-terminated. For DDS → PNG, the loop stops after the current file.\n\n"
            "14. All settings are saved automatically when a run starts and restored on next launch.\n\n"

            f"── Config file location ─────────────────────────\n"
            f"{cfg_loc}"
        ))
        txt.configure(state="disabled")
        txt.pack(expand=True, fill="both", padx=0, pady=0)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=10)

    def _on_tab_changed(self, event=None) -> None:
        ToolTip.hide_all()
        if self._notebook.index("current") == 0:
            self._go_btn.configure(text="Convert  PNG → DDS")
        else:
            self._go_btn.configure(text="Convert  DDS → PNG")

    def _toggle_mirror(self) -> None:
        state = "normal" if self._recursive_var.get() else "disabled"
        self._mirror_chk.configure(state=state)
        if state == "disabled": self._mirror_var.set(False)

    def _toggle_d2p_mirror(self) -> None:
        state = "normal" if self._d2p_recursive_var.get() else "disabled"
        self._d2p_mirror_chk.configure(state=state)
        if state == "disabled": self._d2p_mirror_var.set(False)

    def _toggle_nomips(self) -> None:
        nomips_on = self._nomips_var.get()
        chk_state = "disabled" if nomips_on else "normal"
        self._use_max_mip_count_chk.configure(state=chk_state)
        self._use_min_mip_size_chk.configure(state=chk_state)
        self._toggle_mip_overrides()

    def _toggle_mip_overrides(self) -> None:
        nomips_on = self._nomips_var.get()
        max_state = "disabled" if nomips_on or not self._use_max_mip_count_var.get() else "normal"
        min_state = "disabled" if nomips_on or not self._use_min_mip_size_var.get() else "normal"
        self._max_mip_count_spin.configure(state=max_state)
        self._min_mip_size_spin.configure(state=min_state)

    def _toggle_dithering(self) -> None:
        state = "normal" if self._dither_var.get() else "disabled"
        self._dither_bits_spin.configure(state=state)

    def _on_filter_changed(self, event=None, load_defaults: bool = True) -> None:
        filter_name = self._mip_var.get()
        meta = FILTER_PARAMS.get(filter_name)
        if meta is None:
            self._use_params_var.set(False)
            self._param_chk.configure(state="disabled")
            self._p1_entry.configure(state="disabled")
            self._p2_entry.configure(state="disabled")
            self._p1_label_var.set("Param 1")
            self._p2_label_var.set("Param 2")
            self._param_note.configure(text="(no params for this filter)")
        else:
            p1l, p1mn, p1mx, p1df, p2l, p2mn, p2mx, p2df = meta
            self._param_chk.configure(state="normal")
            self._p1_label_var.set(f"Param 1 ({p1l})")
            self._p2_label_var.set(f"Param 2 ({p2l})")
            self._param_note.configure(text="")
            self._p1_entry.configure(from_=p1mn, to=p1mx)
            self._p2_entry.configure(from_=p2mn, to=p2mx)
            if load_defaults:
                self._param1_var.set(p1df)
                self._param2_var.set(p2df)
            self._toggle_param_entries()

    def _toggle_param_entries(self) -> None:
        active = self._use_params_var.get() and self._param_chk["state"] != "disabled"
        self._p1_entry.configure(state="normal" if active else "disabled")
        self._p2_entry.configure(state="normal" if active else "disabled")

    def find_nvcompress(self) -> str | None:
        for name in ("nvcompress", "nvcompress.exe"):
            path = shutil.which(name)
            if not path: continue
            try:
                result = subprocess.run([path, "-help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
                output = (result.stderr + result.stdout).lower()
                if b"nvcompress" in output:
                    return path
            except Exception:
                continue
        return None

    def find_nvdecompress(self) -> str | None:
        for name in ("nvdecompress", "nvdecompress.exe"):
            path = shutil.which(name)
            if not path: continue
            try:
                result = subprocess.run([path, "-help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
                output = (result.stderr + result.stdout).lower()
                if b"nvdecompress" in output or b"nvidia texture tools" in output:
                    return path
            except Exception:
                continue
        return None

    def _browse_dir(self) -> None:
        d = filedialog.askdirectory(title="Select source PNG root folder")
        if d: self._dir_var.set(os.path.normpath(d))

    def _browse_out(self) -> None:
        d = filedialog.askdirectory(title="Select DDS output root destination")
        if d: self._out_var.set(os.path.normpath(d))

    def _browse_nv(self) -> None:
        p = filedialog.askopenfilename(title="Locate nvcompress binary", filetypes=[("Executables", "*.exe"), ("All files", "*.*")] if os.name == "nt" else [("All files", "*.*")])
        if p: 
            self._nv_var.set(os.path.normpath(p))
            self._detect_nvcompress_capabilities(show_alerts=True)

    def _browse_nvd(self) -> None:
        p = filedialog.askopenfilename(title="Locate nvdecompress binary", filetypes=[("Executables", "*.exe"), ("All files", "*.*")] if os.name == "nt" else [("All files", "*.*")])
        if p: self._nvd_var.set(os.path.normpath(p))

    def _test_nvcompress(self) -> None:
        exe = self._nv_var.get().strip()
        if exe == "nvcompress":
            resolved = self.find_nvcompress()
            if not resolved:
                messagebox.showerror("Error", "Could not verify 'nvcompress' inside system environment PATH variables.")
                return
            exe = resolved
        try:
            res = subprocess.run([exe, "-help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
            
            valid_modes = self._detect_nvcompress_capabilities(show_alerts=False)
            has_bc7 = "Yes" if "BC7 (High Quality RGBA / Smooth)" in valid_modes else "No"
            
            messagebox.showinfo(
                "Success", 
                f"Executable verified successfully!\n\n"
                f"Path: {exe}\n"
                f"Status: NVIDIA Texture Tools Core Detected\n"
                f"Extended Profiles (BC6/BC7/ASTC) Supported: {has_bc7}"
            )
        except Exception as e:
            messagebox.showerror("Execution Failed", f"Failed to run executable:\n{e}")

    def _test_nvdecompress(self) -> None:
        exe = self._nvd_var.get().strip()
        if exe == "nvdecompress":
            resolved = self.find_nvdecompress()
            if not resolved:
                messagebox.showerror("Error", "Could not verify 'nvdecompress' inside system environment PATH variables.")
                return
            exe = resolved
        try:
            res = subprocess.run([exe, "-help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
            output = (res.stderr or b"") + (res.stdout or b"")
            output_lower = output.lower()
            if b"nvdecompress" in output_lower or b"nvidia texture tools" in output_lower:
                messagebox.showinfo("Success", f"Executable verified successfully!\n\nPath: {exe}\nIntegration status: Active")
            else:
                messagebox.showwarning("Warning", f"Executable executed but output signature did not match expected layout.\n\nPath: {exe}")
        except Exception as e:
            messagebox.showerror("Execution Failed", f"Failed to run executable:\n{e}")

    def _d2p_browse_dir(self) -> None:
        d = filedialog.askdirectory(title="Select DDS source folder")
        if d: self._d2p_dir_var.set(os.path.normpath(d))

    def _d2p_browse_out(self) -> None:
        d = filedialog.askdirectory(title="Select PNG output folder")
        if d: self._d2p_out_var.set(os.path.normpath(d))

    def _browse_src_file(self) -> None:
        p = filedialog.askopenfilename(title="Select source PNG file", filetypes=[("PNG images", "*.png"), ("All files", "*.*")])
        if p:
            normalized = os.path.normpath(p)
            self._dir_var.set(normalized)
            if not self._out_var.get(): self._out_var.set(os.path.dirname(normalized))

    def _browse_d2p_file(self) -> None:
        p = filedialog.askopenfilename(title="Select source DDS file", filetypes=[("DDS textures", "*.dds"), ("All files", "*.*")])
        if p:
            normalized = os.path.normpath(p)
            self._d2p_dir_var.set(normalized)
            if not self._d2p_out_var.get(): self._d2p_out_var.set(os.path.dirname(normalized))

    # ── Log file helpers ──────────────────────────────────────────────────────

    def _toggle_log_path(self) -> None:
        state = "normal" if self._log_file_var.get() else "disabled"
        self._log_path_entry.configure(state=state)
        self._log_browse_btn.configure(state=state)

    def _browse_log_path(self) -> None:
        default = f"conversion_{time.strftime('%Y%m%d_%H%M%S')}.log"
        f = filedialog.asksaveasfilename(
            title="Save log file as",
            initialfile=default,
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if f:
            self._log_path_var.set(f)

    def _write_log_file(self) -> None:
        if not self._log_file_var.get():
            return
        path_str = self._log_path_var.get().strip()
        if not path_str:
            path_str = str(CONFIG_FILE.parent / f"conversion_{time.strftime('%Y%m%d_%H%M%S')}.log")
        try:
            Path(path_str).write_text("\n".join(self._log_buffer), encoding="utf-8")
            self._log_line(f"📄  Log saved → {path_str}", "dim")
        except Exception as e:
            self._log_warn(f"Log file write failed: {e}")

    def _log_line(self, text: str, tag: str = "") -> None:
        self._log_buffer.append(text)                    # ← ADD
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n", tag)
        self._log.configure(state="disabled")
        self._log.see("end")

    def _log_ok(self, msg: str) -> None: self._log_line(f"✔ {msg}", "ok")
    def _log_fail(self, msg: str) -> None: self._log_line(f"✖ {msg}", "fail")
    def _log_warn(self, msg: str) -> None: self._log_line(f"⚠ {msg}", "warn")

    def _clear_log(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        self._bar["value"] = 0
        self._status.configure(text="")

    def _start(self) -> None:
        if self._running: return
        if self._notebook.index("current") == 0:
            self._start_png_to_dds()
        else:
            self._start_dds_to_png()

    def _arm_run(self, total: int) -> None:
        self._log_buffer.clear()                         
        self._log_buffer.append(                         
            f"=== Run started {time.strftime('%Y-%m-%d %H:%M:%S')} ==="
        )
        self._running = True
        self._cancel.clear()
        self._go_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._bar["value"] = 0
        self._bar["maximum"] = total
        self._status.configure(text=f"0 / {total}")

    def _start_png_to_dds(self) -> None:
        directory     = self._dir_var.get().strip()
        out_target    = self._out_var.get().strip()
        nvcompress    = self._nv_var.get().strip()
        fmt_choice    = self._fmt_var.get()
        quality_choice= self._quality_var.get()
        mip_filter    = self._mip_var.get()
        workers       = self._shared_workers_var.get()
        recursive     = self._recursive_var.get()
        mirror_tree   = self._mirror_var.get()
        overwrite     = self._overwrite_var.get()
        delete_source = self._p2p_delete_var.get()
        dithering     = self._dither_var.get()
        dither_bits   = self._dither_bits_var.get()
        gamma         = self._gamma_var.get()
        normal        = self._normal_var.get()
        tonormal      = self._tonormal_var.get()
        noalpha       = self._noalpha_var.get()
        nocuda        = self._nocuda_var.get()
        rangescale    = self._rangescale_var.get()
        rgbm          = self._rgbm_var.get()
        nomips        = self._nomips_var.get()
        max_mip_count = self._max_mip_count_var.get() if self._use_max_mip_count_var.get() else None
        min_mip_size  = self._min_mip_size_var.get() if self._use_min_mip_size_var.get() else None
        wrap_repeat   = (self._wrap_var.get() == "repeat")
        weight_r      = self._weight_r_var.get() if self._use_r_var.get() else None
        weight_g      = self._weight_g_var.get() if self._use_g_var.get() else None
        weight_b      = self._weight_b_var.get() if self._use_b_var.get() else None
        weight_a      = self._weight_a_var.get() if self._use_a_var.get() else None
        dry_run       = self._dryrun_var.get()

        valid_modes = self._detect_nvcompress_capabilities(show_alerts=False)
        if fmt_choice not in valid_modes:
            self._log_fail(f"Execution aborted: Selected format target variant '{fmt_choice}' is completely unsupported.")
            messagebox.showerror("Unsupported Format", f"Your version of nvcompress does not support '{fmt_choice}'. Please use supported modes.")
            return

        fmt   = FMT_MAP[fmt_choice]
        quality = QUALITY_MAP[quality_choice]

        if nvcompress == "nvcompress":
            resolved = self.find_nvcompress()
            if not resolved:
                self._log_fail("nvcompress binary execution targets were not verified in PATH environments.")
                return
            nvcompress = resolved

        mip_params: tuple[float, float] | None = None
        if self._use_params_var.get():
            meta = FILTER_PARAMS.get(mip_filter)
            try:
                p1, p2 = float(self._param1_var.get()), float(self._param2_var.get())
                if meta:
                    p1 = max(meta[1], min(p1, meta[2]))
                    p2 = max(meta[5], min(p2, meta[6]))
                mip_params = (p1, p2)
            except (ValueError, tk.TclError):
                self._log_fail("Invalid filter options configuration — numbers required.")
                return

        if not directory:
            self._log_warn("No input path verified.")
            return

        in_path = Path(directory)
        if not in_path.exists():
            self._log_fail("Input location path does not exist.")
            return

        if in_path.is_file():
            if in_path.suffix.lower() != ".png":
                self._log_fail("Target file choice must be a valid PNG configuration layout.")
                return
            pngs = [in_path]
            source_root = in_path.parent
        else:
            source_root = in_path
            # IF we have explicit files from a drag-and-drop session, use those instead!
            if self._explicit_png_files and in_path == Path(os.path.commonpath([p.parent for p in self._explicit_png_files])):
                pngs = sorted(self._explicit_png_files)
            else:
                pngs = collect_pngs(source_root, recursive)

        if not pngs:
            self._log_fail("No conversion targets found.")
            return

        workers = min(workers, len(pngs))
        self._save_config()
        self._arm_run(len(pngs))

        with self._process_lock: self._active_processes.clear()

        self._log_line(f"▶ Initializing PNG → DDS conversion loop ({len(pngs)} files, Workers: {workers})", "header")
        threading.Thread(
            target=self._run_png_to_dds,
            args=(pngs, source_root, Path(out_target) if out_target else None, mirror_tree,
                  nvcompress, fmt, quality, mip_filter, mip_params, dithering, dither_bits, gamma, normal,
                  tonormal, noalpha, nocuda, rangescale, rgbm, nomips, max_mip_count,
                  min_mip_size, wrap_repeat, weight_r, weight_g, weight_b, weight_a,
                  dry_run, overwrite, delete_source, workers),
            daemon=True,
        ).start()

    def _run_png_to_dds(
        self, pngs: list[Path], source_root: Path, out_dir: Path | None, mirror_tree: bool,
        nvcompress: str, fmt: str, quality: str, mip_filter: str,
        mip_params: tuple[float, float] | None, dithering: bool, dither_bits: int, gamma: bool, normal: bool,
        tonormal: bool, noalpha: bool, nocuda: bool, rangescale: bool, rgbm: bool,
        nomips: bool, max_mip_count: int| None, min_mip_size: int| None, wrap_repeat: bool,
        weight_r: float | None, weight_g: float | None, weight_b: float | None, weight_a: float | None,
        dry_run: bool, overwrite: bool, delete_source: bool, workers: int
    ) -> None:
        total = len(pngs)
        state = {"success": 0, "failed": 0, "deleted": 0, "done": 0}
        failed_names: list[str] = []

        def on_done(ok: bool, msg: str, was_deleted: bool, filename: str) -> None:
            state["done"] += 1
            if ok:
                state["success"] += 1
                if was_deleted: state["deleted"] += 1
                self._log_ok(msg)
            else:
                state["failed"] += 1
                failed_names.append(filename)
                self._log_fail(msg)
            self._tick(state["done"], total)

        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {
                pool.submit(
                    convert_png_file, p, source_root, out_dir, mirror_tree, nvcompress,
                    fmt, quality, mip_filter, mip_params, dithering, dither_bits, gamma, normal,
                    tonormal, noalpha, nocuda, rangescale, rgbm, nomips, max_mip_count,
                    min_mip_size, wrap_repeat, weight_r, weight_g, weight_b, weight_a,
                    dry_run, overwrite, delete_source, self._active_processes,
                    self._process_lock, self._cancel,
                ): p for p in pngs
            }
            while futures:
                if self._cancel.is_set():
                    for f in futures: f.cancel()
                    break
                done_set, _ = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done_set:
                    p = futures.pop(future)
                    try:
                        ok, msg, was_deleted = future.result()
                    except Exception as exc:
                        ok, msg, was_deleted = False, f"{p.name}\n          ↳ [internal tracking crash] {exc}", False
                    self.after(0, on_done, ok, msg, was_deleted, p.name)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

        self.after(0, lambda: self._finish(state["success"], state["failed"], state["done"], total, state["deleted"], self._cancel.is_set(), failed_names))

    def _start_dds_to_png(self) -> None:
        directory     = self._d2p_dir_var.get().strip()
        out_target    = self._d2p_out_var.get().strip()
        nvdecompress  = self._nvd_var.get().strip()
        delete_src    = self._d2p_delete_var.get()
        overwrite     = self._d2p_overwrite_var.get()
        dry_run       = self._d2p_dryrun_var.get()
        recursive     = self._d2p_recursive_var.get()
        mirror        = self._d2p_mirror_var.get()
        workers       = self._shared_workers_var.get()

        if not directory:
            self._log_warn("No input extraction target path confirmed.")
            return

        in_path = Path(directory)
        if not in_path.exists():
            self._log_fail("Specified parsing directory path does not exist.")
            return

        if in_path.is_file():
            if in_path.suffix.lower() != ".dds":
                self._log_fail("Target file path configuration must point to a valid DDS file structure.")
                return
            dds_files = [in_path]
            source_root = in_path.parent
        else:
            source_root = in_path
            # IF we have explicit files from a drag-and-drop session, use those instead!
            if self._explicit_dds_files and in_path == Path(os.path.commonpath([p.parent for p in self._explicit_dds_files])):
                dds_files = sorted(self._explicit_dds_files)
            else:
                dds_files = collect_dds(source_root, recursive)

        if not dds_files:
            self._log_fail("No source DDS arrays located.")
            return

        if nvdecompress == "nvdecompress":
            resolved = self.find_nvdecompress()
            if not resolved:
                self._log_fail("nvdecompress binary execution targets were not verified in PATH environments.")
                return
            nvdecompress = resolved

        workers = min(workers, len(dds_files))
        self._save_config()
        self._arm_run(len(dds_files))

        with self._process_lock: self._active_processes.clear()

        self._log_line(f"▶ Initializing Parallelized DDS → PNG Extraction Track ({len(dds_files)} files, Workers: {workers})", "header")
        threading.Thread(
            target=self._run_dds_to_png,
            args=(dds_files, source_root, Path(out_target) if out_target else None, mirror, nvdecompress, delete_src, overwrite, dry_run, workers),
            daemon=True,
        ).start()

    def _run_dds_to_png(
        self, dds_files: list[Path], source_root: Path, out_dir: Path | None,
        mirror_tree: bool, nvdecompress: str, delete_source: bool, overwrite: bool, dry_run: bool, workers: int
    ) -> None:
        total = len(dds_files)
        state = {"success": 0, "failed": 0, "deleted": 0, "done": 0}
        failed_names: list[str] = []

        def on_done(ok: bool, msg: str, was_deleted: bool, filename: str) -> None:
            state["done"] += 1
            if ok:
                state["success"] += 1
                if was_deleted: state["deleted"] += 1
                self._log_ok(msg)
            else:
                state["failed"] += 1
                failed_names.append(filename)
                self._log_fail(msg)
            self._tick(state["done"], total)

        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {
                pool.submit(
                    convert_dds_file, dds, source_root, out_dir, mirror_tree, nvdecompress,
                    delete_source, overwrite, dry_run, self._active_processes,
                    self._process_lock, self._cancel
                ): dds for dds in dds_files
            }
            while futures:
                if self._cancel.is_set():
                    for f in futures: f.cancel()
                    break
                done_set, _ = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done_set:
                    dds = futures.pop(future)
                    try:
                        ok, msg, was_deleted = future.result()
                    except Exception as exc:
                        ok, msg, was_deleted = False, f"{dds.name}\n          ↳ [internal loop processing crash] {exc}", False
                    self.after(0, on_done, ok, msg, was_deleted, dds.name)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

        self.after(0, lambda: self._finish(state["success"], state["failed"], state["done"], total, state["deleted"], self._cancel.is_set(), failed_names))

# ── Orchestration Infrastructure Links ────────────────────────────────────

    def _clean_dropped_path(self, raw_path: str) -> list[str]:
        path_str = raw_path.strip()
        # Safely parse Tk multi-file string syntax
        paths = re.findall(r'\{([^}]+)\}|(\S+)', path_str)
        extracted_paths = [p[0] if p[0] else p[1] for p in paths if p[0] or p[1]]
        # Normalize all extracted paths
        normalized_paths = []
        for p in extracted_paths:
            if p.startswith('"') and p.endswith('"'): p = p[1:-1]
            elif p.startswith("'") and p.endswith("'"): p = p[1:-1]
            normalized_paths.append(os.path.normpath(p))
        return normalized_paths

    def _on_global_window_drop(self, event) -> None:
        if not event.data:
            return
        cleaned_paths = self._clean_dropped_path(event.data)
        if not cleaned_paths:
            return
        current_tab = self._notebook.index("current")
        # Check if it's a multi-file selection or a single directory
        first_path = cleaned_paths[0]
        is_multi_file = len(cleaned_paths) > 1 or os.path.isfile(first_path)
        if is_multi_file:
            # Find the common directory folder of the dropped items
            common_dir = os.path.dirname(first_path) if os.path.isfile(first_path) else first_path
        else:
            common_dir = first_path

        if current_tab == 0:
            # PNG -> DDS Tab
            valid_files = []
            for p in cleaned_paths:
                if os.path.isfile(p) and os.path.splitext(p)[1].lower() == ".png":
                    valid_files.append(Path(p))
            if os.path.isfile(first_path) and not valid_files:
                self._log_warn("Rejected drop: No valid .png files found in selection.")
                return
            self._dir_var.set(common_dir)
            if not self._out_var.get().strip():
                self._out_var.set(common_dir)
            if len(cleaned_paths) > 1:
                self._explicit_png_files = valid_files
                self._log_line(f"🎯 Staged {len(valid_files)} explicit PNG targets from folder: {os.path.basename(common_dir)}", "header")
            else:
                self._explicit_png_files = [] # Reset to normal behavior if it's a folder/single file
                self._log_line(f"🎯 Dropped target into PNG → DDS workflow: {os.path.basename(first_path)}", "header")
        else:
            # DDS -> PNG Tab
            valid_files = []
            for p in cleaned_paths:
                if os.path.isfile(p) and os.path.splitext(p)[1].lower() == ".dds":
                    valid_files.append(Path(p))
            if os.path.isfile(first_path) and not valid_files:
                self._log_warn("Rejected drop: No valid .dds files found in selection.")
                return
            self._d2p_dir_var.set(common_dir)
            if not self._d2p_out_var.get().strip():
                self._d2p_out_var.set(common_dir)
            if len(cleaned_paths) > 1:
                self._explicit_dds_files = valid_files
                self._log_line(f"🎯 Staged {len(valid_files)} explicit DDS targets from folder: {os.path.basename(common_dir)}", "header")
            else:
                self._explicit_dds_files = []
                self._log_line(f"🎯 Dropped target into DDS → PNG workflow: {os.path.basename(first_path)}", "header")

    def _tick(self, done: int, total: int) -> None:
        self._bar["value"] = done
        self._status.configure(text=f"{done} / {total}")

    def _finish(self, success, failed, done, total, deleted, cancelled, failed_names) -> None:
        self._running = False
        self._go_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        del_note = f"  ({deleted} source items deleted)" if deleted else ""

        if cancelled:
            self._log_warn(f"Batch run cancelled by user context. Converted: {success} | Failed: {failed} {del_note}")
        elif failed:
            self._log_warn(f"Completed with exceptions. Converted: {success} | Failed: {failed} {del_note}")
            self._log_line("\nFailed Items Summary:", "fail")
            for name in failed_names: self._log_line(f"  ↳ {name}", "dim")
        else:
            self._log_line(f"✔ Task sequence complete. {success} files processed successfully.{del_note}", "ok")
        self._status.configure(text=f"{done} / {total}")
        self._write_log_file()

    def _load_config(self) -> None:
        if not CONFIG_FILE.exists():
            self._on_filter_changed(load_defaults=True)
            self._toggle_mirror()
            self._toggle_d2p_mirror()
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if "texture_dir" in cfg:    self._dir_var.set(cfg["texture_dir"])
            if "output_dir" in cfg:     self._out_var.set(cfg["output_dir"])
            if "nvcompress" in cfg:     self._nv_var.set(cfg["nvcompress"])
            if "nvdecompress" in cfg:   self._nvd_var.set(cfg["nvdecompress"])
            if "workers" in cfg:        self._shared_workers_var.set(cfg["workers"])
            if "format" in cfg and cfg["format"] in FMT_MAP:       self._fmt_var.set(cfg["format"])
            if "filter" in cfg and cfg["filter"] in FILTERS:       self._mip_var.set(cfg["filter"])
            if "quality" in cfg and cfg["quality"] in QUALITY_MAP: self._quality_var.set(cfg["quality"])
            if "recursive" in cfg:      self._recursive_var.set(cfg["recursive"])
            if "mirror_tree" in cfg:    self._mirror_var.set(cfg["mirror_tree"])
            if "overwrite" in cfg:      self._overwrite_var.set(cfg["overwrite"])
            if "p2p_delete" in cfg:     self._p2p_delete_var.set(cfg["p2p_delete"])
            if "dithering" in cfg:      self._dither_var.set(cfg["dithering"])
            if "dither_bits" in cfg:    self._dither_bits_var.set(cfg["dither_bits"])
            if "gamma" in cfg:          self._gamma_var.set(cfg["gamma"])
            if "normal" in cfg:         self._normal_var.set(cfg["normal"])
            if "tonormal" in cfg:       self._tonormal_var.set(cfg["tonormal"])
            if "noalpha" in cfg:        self._noalpha_var.set(cfg["noalpha"])
            if "nocuda" in cfg:         self._nocuda_var.set(cfg["nocuda"])
            if "rangescale" in cfg:     self._rangescale_var.set(cfg["rangescale"])
            if "rgbm" in cfg:           self._rgbm_var.set(cfg["rgbm"])
            if "nomips" in cfg:         self._nomips_var.set(cfg["nomips"])
            if "max_mip_count" in cfg:      self._max_mip_count_var.set(cfg["max_mip_count"])
            if "min_mip_size" in cfg:       self._min_mip_size_var.set(cfg["min_mip_size"])
            if "use_max_mip_count" in cfg:  self._use_max_mip_count_var.set(cfg["use_max_mip_count"])
            if "use_min_mip_size" in cfg:   self._use_min_mip_size_var.set(cfg["use_min_mip_size"])
            if "wrap" in cfg:           self._wrap_var.set(cfg["wrap"])
            if "weight_r" in cfg:       self._weight_r_var.set(cfg["weight_r"])
            if "weight_g" in cfg:       self._weight_g_var.set(cfg["weight_g"])
            if "weight_b" in cfg:       self._weight_b_var.set(cfg["weight_b"])
            if "weight_a" in cfg:       self._weight_a_var.set(cfg["weight_a"])
            if "dry_run" in cfg:        self._dryrun_var.set(cfg["dry_run"])
            if "use_params" in cfg:     self._use_params_var.set(cfg["use_params"])
            if "param1" in cfg:         self._param1_var.set(cfg["param1"])
            if "param2" in cfg:         self._param2_var.set(cfg["param2"])
            if "d2p_source_dir" in cfg: self._d2p_dir_var.set(cfg["d2p_source_dir"])
            if "d2p_output_dir" in cfg: self._d2p_out_var.set(cfg["d2p_output_dir"])
            if "d2p_recursive" in cfg:  self._d2p_recursive_var.set(cfg["d2p_recursive"])
            if "d2p_mirror" in cfg:     self._d2p_mirror_var.set(cfg["d2p_mirror"])
            if "d2p_delete" in cfg:     self._d2p_delete_var.set(cfg["d2p_delete"])
            if "d2p_overwrite" in cfg:  self._d2p_overwrite_var.set(cfg["d2p_overwrite"])
            if "d2p_dry_run" in cfg:    self._d2p_dryrun_var.set(cfg["d2p_dry_run"])
            if "save_log" in cfg: self._log_file_var.set(cfg["save_log"])
            if "log_path" in cfg: self._log_path_var.set(cfg["log_path"])
        except Exception as e:
            self._log_warn(f"Config profile parsing mapping failure: {e}")
        self._on_filter_changed(load_defaults=False)
        self._toggle_mirror()
        self._toggle_d2p_mirror()
        self._toggle_dithering()
        self._toggle_log_path()

    def _save_config(self) -> None:
        try:
            cfg = {
                "texture_dir":     self._dir_var.get().strip(),
                "output_dir":      self._out_var.get().strip(),
                "nvcompress":      self._nv_var.get().strip(),
                "nvdecompress":    self._nvd_var.get().strip(),
                "format":          self._fmt_var.get(),
                "filter":          self._mip_var.get(),
                "quality":         self._quality_var.get(),
                "workers":         self._shared_workers_var.get(),
                "recursive":       self._recursive_var.get(),
                "mirror_tree":     self._mirror_var.get(),
                "overwrite":       self._overwrite_var.get(),
                "p2p_delete":      self._p2p_delete_var.get(),
                "dithering":       self._dither_var.get(),
                "dither_bits":     self._dither_bits_var.get(),
                "gamma":           self._gamma_var.get(),
                "normal":          self._normal_var.get(),
                "tonormal":        self._tonormal_var.get(),
                "noalpha":         self._noalpha_var.get(),
                "nocuda":          self._nocuda_var.get(),
                "rangescale":      self._rangescale_var.get(),
                "rgbm":            self._rgbm_var.get(),
                "nomips":          self._nomips_var.get(),
                "max_mip_count":   self._max_mip_count_var.get(),
                "min_mip_size":    self._min_mip_size_var.get(),
                "wrap":            self._wrap_var.get(),
                "weight_r":        self._weight_r_var.get(),
                "weight_g":        self._weight_g_var.get(),
                "weight_b":        self._weight_b_var.get(),
                "weight_a":        self._weight_a_var.get(),
                "dry_run":         self._dryrun_var.get(),
                "use_params":      self._use_params_var.get(),
                "param1":          self._param1_var.get(),
                "param2":          self._param2_var.get(),
                "d2p_source_dir":  self._d2p_dir_var.get().strip(),
                "d2p_output_dir":  self._d2p_out_var.get().strip(),
                "d2p_recursive":   self._d2p_recursive_var.get(),
                "d2p_mirror":      self._d2p_mirror_var.get(),
                "d2p_delete":      self._d2p_delete_var.get(),
                "d2p_overwrite":   self._d2p_overwrite_var.get(),
                "d2p_dry_run":     self._d2p_dryrun_var.get(),
                "save_log":        self._log_file_var.get(),
                "log_path":        self._log_path_var.get().strip(),
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self._log_warn(f"Configuration profile save pass failed: {e}")

    def _cancel_run(self) -> None:
        if not self._running: return
        self._cancel.set()
        self._stop_btn.configure(state="disabled")
        self._log_warn("Aborting execution pipeline processes...")
        with self._process_lock:
            procs = list(self._active_processes)
            self._active_processes.clear()
        for proc in procs: _kill(proc)

    def _on_close(self) -> None:
        if self._running: self._cancel_run()
        ToolTip.hide_all()
        self.destroy()

if __name__ == "__main__":
    app = App() 
    app.mainloop()
