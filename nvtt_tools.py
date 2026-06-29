"""
nvtt_tools.py  –  NVIDIA Texture Tools panels (extension toolset)

Front-ends the NVTT 3 command-line programs, reusing the shared ToolPanel base
from directx_texture_tools.py so they look and behave like every other tab:

  • Nvtt Export – the flagship nvtt_export (formats incl. ASTC/UASTC/ETC1S/KTX2,
                  quality, full mip + image-processing + normal-map options,
                  AI super-resolution)
  • DDS Info    – nvddsinfo: print DDS metadata to the log
  • Image Diff  – nvimgdiff: compare two images, optional difference image

(nvcompress / nvdecompress already power the main PNG→DDS / DDS→PNG tabs, and
nvbatchcompress is just the batch form of nvcompress, so they aren't duplicated
here.)

Run standalone (python nvtt_tools.py) or embed via convert_textures_integrated.py.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk

from directx_texture_tools import (
    ToolPanel, ToolTip, apply_styles, run_proc, _collect,
    IMAGE_EXTS, _HAS_DND, TkinterDnD, BG,
)

# Module logger. Set NVTT_LOGLEVEL=DEBUG (standalone) or DDSCONVERTER_LOGLEVEL=DEBUG
# (integrated app) for a full execution trace.
log = logging.getLogger(__name__)

# nvtt_export -f enum names (CLI11 accepts the names).
NVTT_FORMATS = [
    "bc1", "bc1a", "bc2", "bc3", "bc3n", "bc3n-rxgb", "bc4", "bc5",
    "bc6u", "bc6s", "bc7", "rgba8", "bgra8", "bgrx8", "bgr8", "rgb8",
    "rgba16f", "rgba32f", "rg16f", "rg32f", "r16f", "r32f", "l8", "a8",
    "uastc", "etc1s-rgb", "etc1s-rgba",
    "astc-ldr-4x4", "astc-ldr-5x4", "astc-ldr-5x5", "astc-ldr-6x5", "astc-ldr-6x6",
    "astc-ldr-8x5", "astc-ldr-8x6", "astc-ldr-8x8", "astc-ldr-10x5", "astc-ldr-10x6",
    "astc-ldr-10x8", "astc-ldr-10x10", "astc-ldr-12x10", "astc-ldr-12x12",
]
NVTT_QUALITY = ["fastest", "normal", "production", "highest"]
NVTT_TEXTYPE = ["2d", "cubemap"]
NVTT_MIPFILTER = ["box", "kaiser", "triangle", "mitchell", "min", "max"]
NVTT_NORMALFILTER = ["4sample", "3x3", "5x5", "7x7", "9x9", "dudv"]
NVTT_HEIGHT = ["average", "alpha", "red", "green", "blue", "max", "screen"]
NVTT_NORMALALPHA = ["unchanged", "height", "set-to-1"]
NVTT_TRANSFER = ["default", "linear", "srgb"]
NVTT_NORMAL_MODE = ["off", "tangent-space", "object-space"]


# ══════════════════════════════════════════════════════════════════════════════
#  NVTT EXPORT
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class NvttExportOpts:
    """Immutable snapshot of every nvtt_export setting, taken on the main thread.

    String fields are pre-stripped so the builder can treat "" as "unset", and
    weight/bias fields are resolved floats. _build_cmd reads only this object, so
    it never touches Tk and is unit-testable without a display.
    """
    exe: str
    fmt: str
    quality: str
    textype: str
    nocuda: bool
    mips: bool
    mipfilter: str
    maxmip: str
    minmip: str
    mipwidth: str
    mipp1: str
    mipp2: str
    gamma: bool
    mipprealpha: bool
    grayscale: bool
    wr: float
    wg: float
    wb: float
    wa: float
    br: float
    bg: float
    bb: float
    ba: float
    wraprange: bool
    alphathresh: str
    cutout: bool
    scalealpha: bool
    cutoutdither: bool
    saveflip: bool
    readflip: bool
    prealpha: bool
    dx10: bool
    transfer: str
    superres: str
    normal_mode: str
    normalfilter: str
    height: str
    normalalpha: str
    nclamp: bool
    ninvx: bool
    ninvy: bool
    slopespace: bool
    nminz: str
    nscale: str


NVTT_EXPORT_HELP = """\
Nvtt Export · Guide

nvtt_export is the NVIDIA Texture Tools Exporter CLI — a GPU-accelerated image →
DDS compressor with strong BC7/BC6 quality, AI super-resolution and rich mip /
normal-map controls. This tab front-ends the whole CLI.

── Getting started ──
1. nvtt_export path — point at the executable. Test probes it with --help so it
   never pops the GUI. The "Open" button launches the native exporter app
   (OS-aware) if you want the full graphical tool.
2. Source target — a folder or single image; drag & drop works (log pane too).
3. Output folder — blank writes next to the source; with Recursive scan on, the
   subfolder layout is mirrored.
4. Pick a Format and Quality, set options, click "Export → DDS".

── Format (-f) & Quality (-q) ──
bc1/bc1a (small), bc3 (alpha), bc4/bc5 (1- & 2-channel, normals), bc6 (HDR),
bc7 (best RGBA), plus uncompressed rgba8/rgba16f and ASTC/UASTC/ETC1S. Quality
fastest → normal → production → highest trades speed for fewer block artefacts.
No CUDA forces CPU compression.

── Super-resolution ──
Super-res 2× / 4× (--super-res) AI-upscales the image before compressing.
Requires an NVIDIA Turing or newer GPU.

── Mipmaps ──
Mipmaps on/off (--mips / --no-mips); Mip filter chooses box / kaiser / mitchell /
etc. Max mips, Min mip size and Filter width cap and shape the chain; "Filter
params" exposes the kaiser/mitchell P1/P2 coefficients. Mip gamma correct keeps
downsampling in linear light; Mip pre-alpha stops transparent edges bleeding dark.

── Alpha-test (cutout) ──
For alpha-tested art: Cutout alpha (--cutout-alpha) treats alpha as a hard mask,
Scale alpha (--scale-alpha) keeps the cutout coverage constant down the mips (the
nvtt equivalent of texconv's --keep-coverage), Alpha threshold sets the
opaque/transparent split, and Cutout dither softens the edge.

── Image processing ──
To grayscale, Wrap to range, Export pre-alpha, and per-channel Weights / Bias
(each a grouped toggle) bias the compressor. Save / Read flip-Y flip vertically.

── Normal maps ──
Normal map → tangent-space or object-space generates normals from a height input;
Normal filter, Height from and Normal alpha control the derivation; Clamp,
Invert X/Y, Slope-space, Min Z and Scale fine-tune the result.

── Batch behaviour ──
Threads sets parallelism; Dry run previews commands; the Collision guard refuses
runs where two sources would write the same .dds. Show command previews the
invocation; Save log writes the run log to disk.

Value fields apply only when their checkbox is ticked. Hover any control for the
flag it maps to.
"""


class NvttExportPanel(ToolPanel):
    TOOL = "nvtt_export"
    CONFIG = "nvtt_export.json"
    RUN_LABEL = "Export  →  DDS (nvtt_export)"
    PROBE_ARGS = ["--help"]   # no-args launches the GUI, so probe with --help
    HELP_TITLE = "Nvtt Export · Guide"
    HELP_TEXT = NVTT_EXPORT_HELP

    def _make_vars(self):
        self._dir_var = tk.StringVar(); self._out_var = tk.StringVar()
        self._fmt_var = tk.StringVar(value="bc7")
        self._quality_var = tk.StringVar(value="normal")
        self._textype_var = tk.StringVar(value="2d")
        self._nocuda_var = tk.BooleanVar(value=False)
        self._recursive_var = tk.BooleanVar(value=True)
        self._overwrite_var = tk.BooleanVar(value=False)
        self._dryrun_var = tk.BooleanVar(value=False)
        self._workers_var = tk.IntVar(value=self._default_workers)
        # mips
        self._mips_var = tk.BooleanVar(value=True)
        self._minmip_var = tk.StringVar(); self._maxmip_var = tk.StringVar()
        self._mipfilter_var = tk.StringVar(value="box")
        self._mipwidth_var = tk.StringVar()
        self._mipp1_var = tk.StringVar(); self._mipp2_var = tk.StringVar()
        self._gamma_var = tk.BooleanVar(value=True)        # --no-mip-gamma-correct when False
        self._mipprealpha_var = tk.BooleanVar(value=True)  # --no-mip-pre-alpha when False
        # image processing
        self._grayscale_var = tk.BooleanVar(value=False)
        self._wr_var = tk.DoubleVar(value=1.0); self._wg_var = tk.DoubleVar(value=1.0)
        self._wb_var = tk.DoubleVar(value=1.0); self._wa_var = tk.DoubleVar(value=1.0)
        self._br_var = tk.DoubleVar(value=0.0); self._bg_var = tk.DoubleVar(value=0.0)
        self._bb_var = tk.DoubleVar(value=0.0); self._ba_var = tk.DoubleVar(value=0.0)
        self._wraprange_var = tk.BooleanVar(value=False)
        self._alphathresh_var = tk.StringVar()
        self._cutout_var = tk.BooleanVar(value=False)
        self._scalealpha_var = tk.BooleanVar(value=False)
        self._cutoutdither_var = tk.BooleanVar(value=False)
        self._saveflip_var = tk.BooleanVar(value=False)
        self._readflip_var = tk.BooleanVar(value=False)
        self._prealpha_var = tk.BooleanVar(value=False)
        self._dx10_var = tk.BooleanVar(value=False)
        self._transfer_var = tk.StringVar(value="default")
        self._superres_var = tk.StringVar(value="")        # "", "2", "4"
        # normal map
        self._normal_mode_var = tk.StringVar(value="off")
        self._normalfilter_var = tk.StringVar(value="4sample")
        self._nclamp_var = tk.BooleanVar(value=False)      # --clamp when True
        self._ninvx_var = tk.BooleanVar(value=False); self._ninvy_var = tk.BooleanVar(value=False)
        self._nminz_var = tk.StringVar(); self._nscale_var = tk.StringVar()
        self._height_var = tk.StringVar(value="average")
        self._normalalpha_var = tk.StringVar(value="unchanged")
        self._slopespace_var = tk.BooleanVar(value=False)  # --slope-space when True
        # Enable toggles for value fields (off → field disabled, flag omitted).
        self._maxmip_en_var = tk.BooleanVar(value=False)
        self._minmip_en_var = tk.BooleanVar(value=False)
        self._mipwidth_en_var = tk.BooleanVar(value=False)
        self._fparams_en_var = tk.BooleanVar(value=False)   # gates P1 + P2 together
        self._alphathresh_en_var = tk.BooleanVar(value=False)
        self._weights_en_var = tk.BooleanVar(value=False)   # gates R/G/B/A weights
        self._bias_en_var = tk.BooleanVar(value=False)      # gates R/G/B/A biases
        self._nminz_en_var = tk.BooleanVar(value=False)
        self._nscale_en_var = tk.BooleanVar(value=False)
        self._cfg_map = {k: getattr(self, k) for k in vars(self) if k.endswith("_var")}

    def _build_controls(self, parent):
        cfg = ttk.Frame(parent); cfg.pack(fill="x", padx=10, pady=(10, 4)); cfg.columnconfigure(1, weight=1)
        self._dir_entry = self._path_row(cfg, 0, "Source target", self._dir_var,
                                        on_folder=lambda: self._browse_into(self._dir_var, "dir", "Source folder"),
                                        on_file=lambda: self._browse_into(self._dir_var, "file", "Source image"))
        self._path_row(cfg, 1, "Output folder", self._out_var,
                       browse=lambda: self._browse_into(self._out_var, "dir", "Output folder"))
        self._path_row(cfg, 2, "nvtt_export path", self._exe_var,
                       test=self._test_exe, launch=self._launch_native,
                       browse=lambda: self._browse_exe_into(self._exe_var, "Locate nvtt_export"))
        self._setup_dnd(self._dir_entry, self._dir_var)

        opt = ttk.Frame(parent); opt.pack(fill="x", padx=10, pady=(6, 0))
        def row():
            r = ttk.Frame(opt); r.pack(fill="x", pady=(0, 6)); return r

        r = row()
        self._combo(r, "Format", self._fmt_var, NVTT_FORMATS, 16,
            "Output format. bc1/bc1a = small opaque or 1-bit alpha, bc3 = full alpha, bc4/bc5 = 1- and 2-channel "
            "(normals), bc6 = HDR, bc7 = highest-quality RGBA, plus uncompressed rgba8/rgba16f and ASTC variants (-f).")
        self._combo(r, "Quality", self._quality_var, NVTT_QUALITY, 12,
            "Compressor effort: fastest → normal → production → highest. Higher is slower but reduces block artefacts (-q).")
        self._combo(r, "Type", self._textype_var, NVTT_TEXTYPE, 9, "Whether the input is a flat 2D texture or a cubemap (-t).")
        self._chk(r, "No CUDA", self._nocuda_var, "Disable GPU (CUDA) compression and run on the CPU only (--no-cuda).")
        self._workers_spin = ttk.Spinbox(r, from_=1, to=self._cpu_limit, textvariable=self._workers_var, width=4)
        self._workers_spin.pack(side="right"); ToolTip(self._workers_spin, "How many images to convert in parallel when the input is a folder.")
        ttk.Label(r, text="Threads").pack(side="right", padx=(6, 0))

        r = row()
        self._chk(r, "Recursive scan", self._recursive_var, "Search every subfolder of the source for images, not just the top level.")
        self._chk(r, "Overwrite existing", self._overwrite_var, "Replace output files that already exist instead of skipping them.")
        self._chk(r, "Dry run", self._dryrun_var, "Show the command that would run for each file without writing any output.")
        self._chk(r, "DX10 header", self._dx10_var, "Write the extended DXT10/DX10 DDS header — required for BC6/BC7 and arrays (--dx10).")
        self._combo(r, "Transfer fn", self._transfer_var, NVTT_TRANSFER, 9, "Tag the output with a transfer function (linear or sRGB) instead of the format default (--export-transfer-function).")
        self._combo(r, "Super-res", self._superres_var, ["", "2", "4"], 4, "AI-upscale the image 2× or 4× before compressing — needs an NVIDIA Turing or newer GPU (--super-res).")

        r = row()
        self._chk(r, "Mipmaps", self._mips_var, "Generate a full mipmap chain. Off writes only the base image (--mips / --no-mips).")
        self._combo(r, "Mip filter", self._mipfilter_var, NVTT_MIPFILTER, 10, "Filter used when downsampling each mip: box, triangle, kaiser, mitchell, min or max (--mip-filter).")
        self._opt_entry(r, "Max mips", self._maxmip_en_var, self._maxmip_var, 5, "Cap the number of mip levels generated (--max-mip-count).")
        self._opt_entry(r, "Min mip size", self._minmip_en_var, self._minmip_var, 5, "Stop generating mips once a level reaches this size in pixels (--min-mip-size).")
        self._opt_entry(r, "Filter width", self._mipwidth_en_var, self._mipwidth_var, 5, "Width of the mip filter kernel — larger is smoother and blurrier (--mip-filter-width).")
        self._chk(r, "Filter params", self._fparams_en_var, "Override the shape parameters of the kaiser/mitchell mip filters set below (--mip-filter-param-1/-2).", self._sync_gates)
        self._gate_extra(self._entry(r, "P1", self._mipp1_var, 5, "First mip-filter shape parameter — e.g. Kaiser alpha or Mitchell B (--mip-filter-param-1)."), self._fparams_en_var)
        self._gate_extra(self._entry(r, "P2", self._mipp2_var, 5, "Second mip-filter shape parameter — e.g. Kaiser stretch or Mitchell C (--mip-filter-param-2)."), self._fparams_en_var)

        r = row()
        self._chk(r, "Mip gamma correct", self._gamma_var, "Downsample mips in linear light for correct brightness. Turn off to mip in gamma space (--no-mip-gamma-correct).")
        self._chk(r, "Mip pre-alpha", self._mipprealpha_var, "Premultiply by alpha while downsampling so transparent edges don't bleed dark. Off disables it (--no-mip-pre-alpha).")
        self._chk(r, "To grayscale", self._grayscale_var, "Convert the image to grayscale before compressing (--to-grayscale).")
        self._chk(r, "Wrap to range", self._wraprange_var, "Scale values to fit the output format's representable range (--wrap-to-output-range).")
        self._chk(r, "Export pre-alpha", self._prealpha_var, "Write colour premultiplied by alpha (--export-pre-alpha).")

        r = row()
        self._chk(r, "Weights R/G/B/A", self._weights_en_var, "Override how much each channel's error counts during compression — raise a channel to protect its detail (--weight-*).", self._sync_gates)
        for v in (self._wr_var, self._wg_var, self._wb_var, self._wa_var):
            self._gate_extra(self._spin(r, "", v, 0.0, 8.0, 0.1, "%.2f", 5, "Per-channel compression weight (default 1; higher protects that channel)."), self._weights_en_var)
        self._chk(r, "Bias", self._bias_en_var, "Add a constant offset to each channel before compressing (--bias-*).", self._sync_gates)
        for v in (self._br_var, self._bg_var, self._bb_var, self._ba_var):
            self._gate_extra(self._spin(r, "", v, -1.0, 1.0, 0.05, "%.2f", 5, "Per-channel additive bias (default 0)."), self._bias_en_var)

        r = row()
        self._chk(r, "Cutout alpha", self._cutout_var, "Treat alpha as a hard alpha-test mask (cutout) rather than smooth transparency (--cutout-alpha).")
        self._chk(r, "Scale alpha", self._scalealpha_var, "Rescale alpha per mip so the cutout coverage stays constant down the chain (--scale-alpha).")
        self._chk(r, "Cutout dither", self._cutoutdither_var, "Dither the alpha cutout edge to soften aliasing (--cutout-alpha-dither).")
        self._opt_entry(r, "Alpha threshold", self._alphathresh_en_var, self._alphathresh_var, 5, "Alpha value (0–255, default 127) that divides opaque from transparent for the cutout (--alpha-threshold).")
        self._chk(r, "Save flip-Y", self._saveflip_var, "Flip the image vertically when writing the output (--save-flip-y).")
        self._chk(r, "Read flip-Y", self._readflip_var, "Flip the image vertically when reading a DDS input (--read-flip-y).")

        r = row()
        self._combo(r, "Normal map", self._normal_mode_var, NVTT_NORMAL_MODE, 14, "Generate a normal map from the input: off, tangent-space, or object-space.")
        self._combo(r, "Normal filter", self._normalfilter_var, NVTT_NORMALFILTER, 9, "Kernel used to derive normals from height: 4-sample, 3x3, 5x5, 7x7, 9x9 or du/dv (--normal-filter).")
        self._combo(r, "Height from", self._height_var, NVTT_HEIGHT, 9, "Which channel supplies the height/bump data when generating normals (--height).")
        self._combo(r, "Normal alpha", self._normalalpha_var, NVTT_NORMALALPHA, 10, "What to store in the normal map's alpha channel: unchanged, the height, or set to 1 (--normal-alpha).")

        r = row()
        self._chk(r, "Clamp normals", self._nclamp_var, "Clamp the height map's edges instead of wrapping them when generating normals (--clamp).")
        self._chk(r, "Invert X", self._ninvx_var, "Flip the red (X) channel of the generated normal map (--normal-invert-x).")
        self._chk(r, "Invert Y", self._ninvy_var, "Flip the green (Y) channel — switches the OpenGL ↔ DirectX normal convention (--normal-invert-y).")
        self._chk(r, "Slope-space", self._slopespace_var, "Leave the normals in slope space (un-normalised) for specialised workflows (--slope-space).")
        self._opt_entry(r, "Min Z", self._nminz_en_var, self._nminz_var, 5, "Clamp the minimum Z (blue) component of generated normals, 0–1 (--normal-min-z).")
        self._opt_entry(r, "Scale", self._nscale_en_var, self._nscale_var, 5, "Bump strength when generating normals — higher gives steeper slopes (--normal-scale).")

    def _post_init(self):
        pass

    def _gather_opts(self) -> NvttExportOpts:
        """Snapshot all Tk variables into a frozen NvttExportOpts on the MAIN
        thread. Strings are pre-stripped; weights/biases go through the safe
        float reader so a cleared spinbox falls back to its default."""
        v = self
        def s(var):
            return (var.get() or "").strip()
        return NvttExportOpts(
            exe=v._exe_var.get().strip() or "nvtt_export",
            fmt=v._fmt_var.get(), quality=v._quality_var.get(), textype=v._textype_var.get(),
            nocuda=v._nocuda_var.get(),
            mips=v._mips_var.get(), mipfilter=v._mipfilter_var.get(),
            maxmip=(s(v._maxmip_var) if v._maxmip_en_var.get() else ""),
            minmip=(s(v._minmip_var) if v._minmip_en_var.get() else ""),
            mipwidth=(s(v._mipwidth_var) if v._mipwidth_en_var.get() else ""),
            mipp1=(s(v._mipp1_var) if v._fparams_en_var.get() else ""),
            mipp2=(s(v._mipp2_var) if v._fparams_en_var.get() else ""),
            gamma=v._gamma_var.get(), mipprealpha=v._mipprealpha_var.get(),
            grayscale=v._grayscale_var.get(),
            wr=(self._float_or(v._wr_var, 1.0) if v._weights_en_var.get() else 1.0),
            wg=(self._float_or(v._wg_var, 1.0) if v._weights_en_var.get() else 1.0),
            wb=(self._float_or(v._wb_var, 1.0) if v._weights_en_var.get() else 1.0),
            wa=(self._float_or(v._wa_var, 1.0) if v._weights_en_var.get() else 1.0),
            br=(self._float_or(v._br_var, 0.0) if v._bias_en_var.get() else 0.0),
            bg=(self._float_or(v._bg_var, 0.0) if v._bias_en_var.get() else 0.0),
            bb=(self._float_or(v._bb_var, 0.0) if v._bias_en_var.get() else 0.0),
            ba=(self._float_or(v._ba_var, 0.0) if v._bias_en_var.get() else 0.0),
            wraprange=v._wraprange_var.get(),
            alphathresh=(s(v._alphathresh_var) if v._alphathresh_en_var.get() else ""),
            cutout=v._cutout_var.get(), scalealpha=v._scalealpha_var.get(),
            cutoutdither=v._cutoutdither_var.get(), saveflip=v._saveflip_var.get(),
            readflip=v._readflip_var.get(), prealpha=v._prealpha_var.get(), dx10=v._dx10_var.get(),
            transfer=v._transfer_var.get(), superres=s(v._superres_var),
            normal_mode=v._normal_mode_var.get(), normalfilter=v._normalfilter_var.get(),
            height=v._height_var.get(), normalalpha=v._normalalpha_var.get(),
            nclamp=v._nclamp_var.get(), ninvx=v._ninvx_var.get(), ninvy=v._ninvy_var.get(),
            slopespace=v._slopespace_var.get(),
            nminz=(s(v._nminz_var) if v._nminz_en_var.get() else ""),
            nscale=(s(v._nscale_var) if v._nscale_en_var.get() else ""),
        )

    @staticmethod
    def _build_cmd(o: NvttExportOpts, src, out_path) -> list:
        """Pure command builder: a function of (opts, src, out_path) only — no Tk,
        no instance state. Flag order matches nvtt_export's expectations."""
        cmd = [o.exe, "-o", str(out_path), "-f", o.fmt, "-q", o.quality]
        if o.textype != "2d":
            cmd += ["-t", o.textype]
        if o.nocuda:
            cmd.append("--no-cuda")
        # mips
        if not o.mips:
            cmd.append("--no-mips")
        else:
            cmd += ["--mip-filter", o.mipfilter]
            if o.maxmip: cmd += ["--max-mip-count", o.maxmip]
            if o.minmip: cmd += ["--min-mip-size", o.minmip]
            if o.mipwidth: cmd += ["--mip-filter-width", o.mipwidth]
            if o.mipp1: cmd += ["--mip-filter-param-1", o.mipp1]
            if o.mipp2: cmd += ["--mip-filter-param-2", o.mipp2]
        if not o.gamma:
            cmd.append("--no-mip-gamma-correct")
        if not o.mipprealpha:
            cmd.append("--no-mip-pre-alpha")
        # image processing
        if o.grayscale: cmd.append("--to-grayscale")
        for flag, val, default in (("--weight-r", o.wr, 1.0), ("--weight-g", o.wg, 1.0),
                                   ("--weight-b", o.wb, 1.0), ("--weight-a", o.wa, 1.0),
                                   ("--bias-r", o.br, 0.0), ("--bias-g", o.bg, 0.0),
                                   ("--bias-b", o.bb, 0.0), ("--bias-a", o.ba, 0.0)):
            if abs(val - default) > 1e-9:
                cmd += [flag, f"{val:.3f}"]
        if o.wraprange: cmd.append("--wrap-to-output-range")
        if o.alphathresh: cmd += ["--alpha-threshold", o.alphathresh]
        if o.cutout: cmd.append("--cutout-alpha")
        if o.scalealpha: cmd.append("--scale-alpha")
        if o.cutoutdither: cmd.append("--cutout-alpha-dither")
        if o.saveflip: cmd.append("--save-flip-y")
        if o.readflip: cmd.append("--read-flip-y")
        if o.prealpha: cmd.append("--export-pre-alpha")
        if o.dx10: cmd.append("--dx10")
        if o.transfer != "default":
            cmd += ["--export-transfer-function", o.transfer]
        if o.superres:
            cmd += ["--super-res", o.superres]
        # normal map
        mode = o.normal_mode
        if mode == "tangent-space":
            cmd.append("--to-normal")
        elif mode == "object-space":
            cmd.append("--to-normal-os")
        if mode != "off":
            cmd += ["--normal-filter", o.normalfilter,
                    "--height", o.height,
                    "--normal-alpha", o.normalalpha]
            if o.nclamp: cmd.append("--clamp")
            if o.ninvx: cmd.append("--normal-invert-x")
            if o.ninvy: cmd.append("--normal-invert-y")
            if o.slopespace: cmd.append("--slope-space")
            if o.nminz: cmd += ["--normal-min-z", o.nminz]
            if o.nscale: cmd += ["--normal-scale", o.nscale]
        cmd.append(str(src))
        return cmd

    def _preview_command(self):
        sample = Path(self._dir_var.get().strip() or "example.png")
        if sample.suffix.lower() not in IMAGE_EXTS:
            sample = sample / "example.png"
        out = Path(self._out_var.get().strip() or sample.parent) / (sample.stem + ".dds")
        cmd = self._build_cmd(self._gather_opts(), sample, out)
        self._head("Preview command:")
        self._log_line("  " + " ".join(f'"{c}"' if " " in c else c for c in cmd), "dim")

    def _start(self):
        if self._running:
            return
        exe = self._resolve_exe()
        if not exe:
            self._fail("nvtt_export not found. Set its path or put it on PATH."); return
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
            files = _collect(source_root, IMAGE_EXTS, self._recursive_var.get())
        if not files:
            self._fail("No image files found."); return
        out_target = self._out_var.get().strip()
        out_dir = Path(out_target) if out_target else None
        overwrite = self._overwrite_var.get(); dry = self._dryrun_var.get()
        # Snapshot every Tk variable ONCE on the main thread; workers use only the
        # resulting frozen opts + prebuilt command lists, never Tk.
        recursive = self._recursive_var.get()
        opts = self._gather_opts()
        fmt = opts.fmt
        specs = []
        for src in files:
            tgt_dir = out_dir if out_dir else src.parent
            if out_dir and recursive and src.is_relative_to(source_root):
                tgt_dir = out_dir / src.relative_to(source_root).parent
            out_path = tgt_dir / (src.stem + ".dds")
            specs.append((src, tgt_dir, out_path, self._build_cmd(opts, src, out_path)))

        # Don't overwrite a source with its own output (a .dds re-encoded in place).
        _n0 = len(specs)
        specs = [s for s in specs if os.path.normcase(str(s[2])) != os.path.normcase(str(s[0]))]
        if len(specs) < _n0:
            self._warn(f"Skipped {_n0 - len(specs)} file(s) whose output would overwrite the source in place.")
        if not specs:
            self._fail("Nothing to convert — every output would overwrite its source."); return

        # Heads-up if the output sits inside a recursively-scanned source: a re-run
        # would pick these outputs back up (.dds is itself an input type here).
        if out_dir and recursive:
            try:
                if out_dir.resolve().is_relative_to(source_root.resolve()):
                    self._warn("Output folder is inside the source — a re-run may re-convert these outputs.")
            except (ValueError, OSError):
                pass

        # Refuse to run if two sources map to the same .dds (e.g. tex.png and
        # tex.tga in one folder) — parallel workers would clobber each other. A
        # dry run writes nothing, so let it through (warned) to preview the commands.
        dupes = self._flat_collisions([s[2] for s in specs])
        if dupes and not dry:
            self._clear_log()
            self._fail(f"{len(dupes)} output-name collision(s) — sources would overwrite each other:")
            for p, n in dupes[:6]:
                self._log_line(f"    {n}× → {Path(p).name}", "warn")
            self._warn("Rename the inputs or convert them separately.")
            return

        workers = max(1, min(int(self._float_or(self._workers_var, self._default_workers)), self._cpu_limit, len(specs)))
        log.debug("nvtt_export: start — source=%s, %d file(s), out=%s, workers=%d, fmt=%s",
                  source_root, len(specs), out_dir, workers, fmt)
        self._arm(len(specs))
        self._head(f"▶ nvtt_export · {len(specs)} files · {workers} threads · {fmt}")
        if dupes:   # dry run only — a real run with collisions already returned above
            self._warn(f"{len(dupes)} output-name collision(s) — a real run would overwrite; dry run previews only.")

        def job(spec):
            src, tgt_dir, out_path, cmd = spec
            label = f"{src.name} → {out_path.name} [{fmt}]"
            if out_path.exists() and not overwrite and not dry:
                return False, f"{src.name}  [skipped: exists]"
            if dry:
                return True, f"[dry] {label}"
            tgt_dir.mkdir(parents=True, exist_ok=True)
            rc, out = run_proc(cmd, self._active, self._lock, self._cancel)
            if rc == 0 and out_path.exists():
                return True, label
            return False, f"{label}\n      ↳ {(out.strip().splitlines() or ['failed'])[-1]}"

        self._run_parallel(specs, job, workers)


# ══════════════════════════════════════════════════════════════════════════════
#  NVDDSINFO
# ══════════════════════════════════════════════════════════════════════════════
NVDDSINFO_HELP = """\
DDS Info (nvddsinfo) · Guide

nvddsinfo prints the header and metadata of DDS files — format, dimensions, mip
count, flags and more. It is read-only; nothing is written.

── Using it ──
1. nvddsinfo path — set and Test the executable.
2. DDS file / folder — a single .dds or a folder; drag & drop works (log pane too).
3. Recursive scan — include subfolders when the input is a folder.
4. Threads — how many files are read in parallel.
5. Click "Show DDS info".

── Output ──
Files are read in parallel for speed, but each file's report is collected and
printed in sorted file order at the end as one clean block (green header = ok,
red = failed), so worker output never interleaves. Use Save log to keep a copy.
"""


class NvddsinfoPanel(ToolPanel):
    TOOL = "nvddsinfo"
    CONFIG = "nvddsinfo.json"
    RUN_LABEL = "Show DDS info"
    HELP_TITLE = "DDS Info · Guide"
    HELP_TEXT = NVDDSINFO_HELP

    def _make_vars(self):
        self._dir_var = tk.StringVar()
        self._recursive_var = tk.BooleanVar(value=True)
        self._workers_var = tk.IntVar(value=self._default_workers)
        self._cfg_map = {k: getattr(self, k) for k in vars(self) if k.endswith("_var")}

    def _build_controls(self, parent):
        cfg = ttk.Frame(parent); cfg.pack(fill="x", padx=10, pady=(10, 4)); cfg.columnconfigure(1, weight=1)
        self._dir_entry = self._path_row(cfg, 0, "DDS file / folder", self._dir_var,
                                        on_folder=lambda: self._browse_into(self._dir_var, "dir", "Folder"),
                                        on_file=lambda: self._browse_into(self._dir_var, "file", "DDS file"))
        self._path_row(cfg, 1, "nvddsinfo path", self._exe_var,
                       test=self._test_exe, browse=lambda: self._browse_exe_into(self._exe_var, "Locate nvddsinfo"))
        self._setup_dnd(self._dir_entry, self._dir_var)
        opt = ttk.Frame(parent); opt.pack(fill="x", padx=10, pady=(6, 0))
        r = ttk.Frame(opt); r.pack(fill="x")
        self._chk(r, "Recursive scan", self._recursive_var, "When the input is a folder, search its subfolders for .dds files too.")
        self._workers_spin = ttk.Spinbox(r, from_=1, to=self._cpu_limit, textvariable=self._workers_var, width=4)
        self._workers_spin.pack(side="right"); ToolTip(self._workers_spin, "How many DDS files to read in parallel.")
        ttk.Label(r, text="Threads").pack(side="right", padx=(6, 0))

    def _post_init(self):
        pass

    def _start(self):
        if self._running:
            return
        exe = self._resolve_exe()
        if not exe:
            self._fail("nvddsinfo not found."); return
        self._exe_var.set(exe)
        directory = self._dir_var.get().strip()
        if not directory:
            self._warn("No input."); return
        in_path = Path(directory)
        if in_path.is_file():
            files = [in_path]
        else:
            files = _collect(in_path, {".dds"}, self._recursive_var.get())
        if not files:
            self._fail("No DDS files found."); return
        workers = max(1, min(int(self._float_or(self._workers_var, self._default_workers)), self._cpu_limit, len(files)))
        log.debug("nvddsinfo: start — input=%s, %d file(s), workers=%d", directory, len(files), workers)
        self._arm(len(files))
        self._head(f"▶ nvddsinfo · {len(files)} files")

        # Workers read files in parallel for speed but finish in nondeterministic
        # order. To keep the log clean (no interleaving) AND responsive on large
        # batches, stream the results in sorted order *incrementally*: each finished
        # file unblocks the contiguous in-order prefix, flushed a few at a time on
        # the main thread (yielding to the UI between chunks) — never one giant
        # synchronous dump at the end that would freeze the window. `files` is sorted.
        results: dict[Path, tuple[bool, str]] = {}
        nxt = [0]                       # index of the next file to flush, in order
        self._info_records = []         # reset the run's records (expand + Save-log backup)

        def flush():
            shown = 0
            while nxt[0] < len(files) and files[nxt[0]] in results:
                f = files[nxt[0]]
                ok, txt = results[f]
                # One compact summary line; double-click it to expand the full output.
                self._post_info_summary(f.name, ok, txt)
                nxt[0] += 1
                shown += 1
                if shown >= 40:                # 1 line each, so larger chunks are fine
                    self._safe_after(flush)
                    return

        def job(f: Path):
            cached = self._info_cache_get(f)    # unchanged file → instant, no subprocess
            if cached is not None:
                results[f] = cached
            else:
                rc, out = run_proc([exe, str(f)], self._active, self._lock, self._cancel)
                results[f] = (rc == 0, out.strip())
                if results[f][0]:               # only cache successful reads
                    self._info_cache_put(f, results[f][0], results[f][1])
            self._safe_after(flush)             # flush whatever in-order prefix is now ready
            return results[f][0], f.name

        self._run_parallel(files, job, workers, log_each=False, on_finish=flush)


# ══════════════════════════════════════════════════════════════════════════════
#  NVIMGDIFF
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class NvimgdiffOpts:
    """Immutable snapshot of nvimgdiff settings, taken on the main thread."""
    exe: str
    normal: bool
    alpha: bool
    rangescale: bool
    a: str
    b: str
    out: str


NVIMGDIFF_HELP = """\
Image Diff (nvimgdiff) · Guide

nvimgdiff compares two images and reports how different they are, optionally
writing a visual difference image. Useful for checking compression loss or
before/after edits.

── Using it ──
1. nvimgdiff path — set and Test the executable.
2. Original file — the reference image (drag & drop works).
3. Updated file — the image to compare against it.
4. Diff image (optional) — a path (e.g. .tga) to write a visual diff to; leave
   blank to only print the metrics.
5. Click "Compare images"; results appear in the log.

── Options ──
  • Normal map (-normal) — compare as normal maps, measuring angular error
    between normals instead of raw RGB.
  • Alpha weighted (-alpha) — weight the comparison by alpha so transparent
    regions count for less.
  • Range scale (-rangescale) — scale the 2nd image into the 1st's value range
    before comparing; handy for HDR.
"""


class NvimgdiffPanel(ToolPanel):
    TOOL = "nvimgdiff"
    CONFIG = "nvimgdiff.json"
    RUN_LABEL = "Compare images"
    HELP_TITLE = "Image Diff · Guide"
    HELP_TEXT = NVIMGDIFF_HELP

    def _make_vars(self):
        self._a_var = tk.StringVar(); self._b_var = tk.StringVar(); self._out_var = tk.StringVar()
        self._normal_var = tk.BooleanVar(value=False)
        self._alpha_var = tk.BooleanVar(value=False)
        self._rangescale_var = tk.BooleanVar(value=False)
        self._cfg_map = {k: getattr(self, k) for k in vars(self) if k.endswith("_var")}

    def _build_controls(self, parent):
        cfg = ttk.Frame(parent); cfg.pack(fill="x", padx=10, pady=(10, 4)); cfg.columnconfigure(1, weight=1)
        self._a_entry = self._path_row(cfg, 0, "Original file", self._a_var,
                                      on_file=lambda: self._browse_into(self._a_var, "file", "Original"))
        self._path_row(cfg, 1, "Updated file", self._b_var,
                       browse=lambda: self._browse_into(self._b_var, "file", "Updated"))
        self._path_row(cfg, 2, "Diff image (optional)", self._out_var,
                       browse=lambda: self._browse_into(self._out_var, "file", "Diff output (e.g. .tga)"))
        self._path_row(cfg, 3, "nvimgdiff path", self._exe_var,
                       test=self._test_exe, browse=lambda: self._browse_exe_into(self._exe_var, "Locate nvimgdiff"))
        self._setup_dnd(self._a_entry, self._a_var)
        opt = ttk.Frame(parent); opt.pack(fill="x", padx=10, pady=(6, 0))
        r = ttk.Frame(opt); r.pack(fill="x")
        self._chk(r, "Normal map", self._normal_var, "Compare the two images as normal maps, measuring angular error between normals rather than raw RGB (-normal).")
        self._chk(r, "Alpha weighted", self._alpha_var, "Weight the comparison by alpha so transparent regions count for less (-alpha).")
        self._chk(r, "Range scale", self._rangescale_var, "Scale the second image into the first's value range before comparing, useful for HDR (-rangescale).")

    def _post_init(self):
        pass

    def _gather_opts(self) -> NvimgdiffOpts:
        """Snapshot all Tk variables into a frozen NvimgdiffOpts (main thread)."""
        v = self
        return NvimgdiffOpts(
            exe=v._exe_var.get().strip() or "nvimgdiff",
            normal=v._normal_var.get(), alpha=v._alpha_var.get(),
            rangescale=v._rangescale_var.get(),
            a=v._a_var.get().strip(), b=v._b_var.get().strip(),
            out=v._out_var.get().strip(),
        )

    @staticmethod
    def _build_cmd(o: NvimgdiffOpts) -> list:
        """Pure command builder: a function of opts only — no Tk."""
        cmd = [o.exe]
        if o.normal: cmd.append("-normal")
        if o.alpha: cmd.append("-alpha")
        if o.rangescale: cmd.append("-rangescale")
        cmd += [o.a, o.b]
        if o.out:
            cmd.append(o.out)
        return cmd

    def _preview_command(self):
        self._head("Preview command:")
        self._log_line("  " + " ".join(f'"{c}"' if " " in c else c for c in self._build_cmd(self._gather_opts())), "dim")

    def _start(self):
        if self._running:
            return
        exe = self._resolve_exe()
        if not exe:
            self._fail("nvimgdiff not found."); return
        self._exe_var.set(exe)
        if not self._a_var.get().strip() or not self._b_var.get().strip():
            self._warn("Pick both files to compare."); return
        opts = self._gather_opts()      # opts.exe is the resolved path (set above)
        log.debug("nvimgdiff: start — a=%s, b=%s, diff=%s", opts.a, opts.b, opts.out or "(none)")
        self._head("▶ nvimgdiff")
        self._run_single(self._build_cmd(opts),
                         success_check=(lambda: Path(opts.out).exists()) if opts.out else None)


# ── Standalone suite ───────────────────────────────────────────────────────────
def main():
    logging.basicConfig(level=os.environ.get("NVTT_LOGLEVEL", "WARNING").upper())
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    root.title("NVIDIA Texture Tools")
    root.configure(bg=BG)
    root.minsize(1040, 840)
    apply_styles(root)
    ttk.Label(root, text="NVIDIA Texture Tools", style="Title.TLabel").pack(side="top", anchor="w", padx=18, pady=12)
    ttk.Separator(root).pack(fill="x")

    paned = ttk.PanedWindow(root, orient="vertical")
    paned.pack(fill="both", expand=True, padx=12, pady=12)
    nb = ttk.Notebook(paned); paned.add(nb, weight=0)
    bottoms = {}
    for cls, title in ((NvttExportPanel, "  Nvtt Export  "),
                       (NvddsinfoPanel, "  DDS Info  "),
                       (NvimgdiffPanel, "  Image Diff  ")):
        b = ttk.Frame(paned)
        p = cls(nb, bottom_host=b)
        nb.add(p, text=title)
        bottoms[nb.index(p)] = b
    paned.add(list(bottoms.values())[0], weight=1)
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
