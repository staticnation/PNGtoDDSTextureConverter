# DDS ↔ PNG Texture Converter (GUI)

A multi-threaded batch texture converter with a dark-themed GUI, supporting bidirectional conversion between PNG and DDS formats.

- **PNG → DDS** via NVIDIA Texture Tools (`nvcompress`)
- **DDS → PNG** via `nvdecompress` with automatic Pillow fallback

It also ships an optional **extended toolset** that front-ends the DirectXTex and NVIDIA Texture Tools command-line programs (texconv, texassemble, texdiag, nvtt_export, nvddsinfo, nvimgdiff) as extra tabs sharing the same UI. Run `convert_textures_integrated.py` to get every tab in one window, or run a suite on its own. See [Extended Toolset](#extended-toolset) below.

Standalone pre-compiled binaries are available for Windows and Linux — no Python installation required.

---

## Requirements

### External tools

- `nvcompress` — required for PNG → DDS compression
- `nvdecompress` — optional but recommended for DDS → PNG; Pillow is used as a fallback if unavailable or if decoding fails

Both executables must be either on your system `PATH` or pointed to manually via the application's path fields.

### Running from source

The standalone binaries bundle everything, but to run the script directly you need:

- **Python 3.10 or newer** (with `tkinter`, which ships with most installs)
- **`Pillow`** — required by the PNG ↔ DDS converter (alpha detection, DDS fallback decoding). The standalone DirectXTex/NVTT suites don't need it.
- **`tkinterdnd2`** — *optional*; enables drag-and-drop. Without it the app still runs — just use the **Folder…/File…** buttons. (A log line notes when DnD is disabled.)

```
pip install Pillow            # required for the converter
pip install tkinterdnd2       # optional: drag-and-drop

python convert_textures_gui.py        # just the PNG ↔ DDS converter
python convert_textures_integrated.py # converter + the full DirectXTex/NVTT toolset
python directx_texture_tools.py       # standalone DirectXTex suite only (no Pillow/tkinterdnd2 needed)
python nvtt_tools.py                  # standalone NVTT suite only (no Pillow/tkinterdnd2 needed)
```

### Debug tracing

Every module uses a named `logging` logger and is silent by default. Set the level
to `DEBUG` to get a full execution trace — each tool resolution, every subprocess
command and its return code, run start/finish with file counts and worker counts,
cancellations and process kills, config load/save, drag-and-drop targets, and any
best-effort failure that would otherwise be swallowed:

```
# integrated app (covers the converter + every suite tab)
DDSCONVERTER_LOGLEVEL=DEBUG python convert_textures_integrated.py

# standalone suites
DXTEX_LOGLEVEL=DEBUG  python directx_texture_tools.py
NVTT_LOGLEVEL=DEBUG   python nvtt_tools.py
```

The trace goes to the console (stderr); tick **Save log** in any tab to also capture
that tab's run log to a file.

### Source files

| File | Contents |
|---|---|
| `convert_textures_gui.py` | The PNG ↔ DDS converter (nvcompress / nvdecompress) — standalone app |
| `directx_texture_tools.py` | DirectXTex suite: shared `ToolPanel` base + Texconv, Texassemble, Texdiag panels |
| `nvtt_tools.py` | NVTT suite: Nvtt Export, DDS Info, Image Diff panels (reuses `ToolPanel`) |
| `convert_textures_integrated.py` | Launcher that imports `App` and adds every suite panel as a Notebook tab |

---

## Features

### Drag & Drop

Files and folders can be dragged directly onto the converter window instead of using the Browse buttons.

- **Drop a folder** — sets the source field and scans it for convertible files
- **Drop a single file** — targets that file for a one-shot conversion
- **Drop multiple files** — stages only those specific files as conversion targets, ignoring everything else in their parent folder
- **Drop onto the output field** — sets the **output folder** from a dropped folder (or a dropped file's parent). This is confined to the output field itself, so it never disturbs the source selection.

The window detects which tab is active and routes source drops accordingly. PNG files are accepted on the PNG → DDS tab; DDS files on the DDS → PNG tab. Drops containing the wrong file type are rejected with a warning in the log.

**Pasting a list of paths.** The source field also accepts a pasted list — newline- or `;`-separated, or Windows "Copy as path" (quoted). Entries may be **files or folders** (folders are expanded honouring Recursive scan, and the combined list is de-duplicated), and the list may span drives. This is the practical way to batch files from more than one drive, since a single drag comes from one location.

When you drop multiple files, the exact selection is remembered and used for the run as long as the source field still points at the folder shown when they were staged. Picking a folder or file with the Browse/File buttons, or dropping a single new target, clears a previous multi-file selection so it can't carry over into a later run.

A multi-file drop deliberately leaves the **output folder blank**, which means each converted file is written next to its own source — so files keep their original locations and nothing collides, no matter how many folders the selection came from. Set an output folder explicitly only if you want to collect the results elsewhere.

**Multi-file selections spanning different drives** are handled too. Every dropped file is converted. With the output left blank, each result is written next to its source as usual. If you do set an output folder, output is **keyed by drive** so identically named files from different drives can't overwrite each other — e.g. `C:\tex\1.png` and `D:\tex\1.png` become `output\c_drive\tex\1.dds` and `output\d_drive\tex\1.dds` (with Mirror structure on; with it off, the file lands directly under its drive folder). The log notes when a selection crosses drives.

### PNG → DDS Compression

- Parallel compression using a `ThreadPoolExecutor` worker pool — spawns multiple `nvcompress` subprocesses simultaneously
- **Auto format** — detects alpha channel presence and automatically selects BC1 (opaque) or BC3 (transparent) per file
- Format list is dynamically filtered to only show formats your installed version of `nvcompress` actually supports
- Full BC format support: BC1, BC1a, BC2, BC3, BC4, BC5, BC6, BC6s, BC7, ATI2, BC1n, BC3n, BC5s, BC3-RGBM, all ASTC LDR block sizes, and uncompressed RGBA
- Normal map formats (BC1n, BC3n, BC5, ATI2) automatically pass `-normal` to `nvcompress`
- BC6, BC6s, BC7, and ASTC formats automatically use the DDS10 header extension
- Mipmap filter selection: Box, Triangle, Min, Max, Kaiser, Mitchell — with optional manual parameter overrides for Kaiser (Width/Stretch) and Mitchell (B/C coefficients)
- Quality presets: Fast, Production, Highest
- Alpha dithering for BC1a / BC2 / BC3
- Toggle to disable mip gamma correction (`-no-mip-gamma-correct`), plus normal-map, alpha, range-scale, RGBM, CUDA, and per-channel weighting flags
- Recursive folder scan with optional folder structure mirroring in the output
- Overwrite protection (skip existing DDS files by default)
- Output-collision guard: if two sources would resolve to the same output file (mirror off + recursive + identically named files in different subfolders), the run is refused with the offenders listed rather than letting parallel workers race and silently overwrite — enable Mirror structure or use distinct output folders (a dry run previews instead). Applies to both conversion directions.
- Optional deletion of source PNG after successful DDS write
- Dry run mode — logs what would happen without writing any files

### DDS → PNG Extraction

- Parallel extraction using the same shared worker pool
- Primary decoder: `nvdecompress` (converts to an intermediate TGA, then saves as PNG via Pillow)
- Automatic fallback to direct Pillow decoding if `nvdecompress` is unavailable or fails on a file
- Output is always lossless RGBA PNG
- Recursive folder scan with optional folder structure mirroring
- Overwrite protection
- Optional deletion of source DDS after successful PNG write
- Dry run mode

### Log File

The full run log can be saved to a file when a conversion finishes. Enable **Save log** in the toolbar, then optionally choose a save path with the **…** button. If no path is set, a timestamped log file is generated automatically next to the config file.

### Process Management

All spawned subprocesses are tracked by PID. Clicking **Cancel** force-terminates active `nvcompress` / `nvdecompress` processes immediately:

- **Windows** — `taskkill /F /T`
- **Linux** — process group signal (`SIGKILL`)

---

## GUI Controls

### PNG → DDS Tab

| Control | Description |
|---|---|
| Source target | Folder or single PNG file to convert |
| Output folder | Destination for DDS files. Blank = write alongside source PNGs |
| nvcompress path | Path to the nvcompress executable |
| Format | DDS block compression format |
| Mip filter | Downsampling filter used during mipmap generation |
| Quality | Compression speed vs. quality trade-off |
| Workers | Number of parallel nvcompress jobs |
| Recursive scan | Search all subdirectories for PNG files |
| Mirror structure | Recreate source folder hierarchy in the output folder (requires Recursive scan) |
| Overwrite existing | Replace existing DDS files instead of skipping them |
| Delete source PNG | ⚠ Remove source PNG after successful DDS write |
| Dry run mode | Simulate conversion without writing any files |
| Alpha dithering | Reduce banding on transparent edges, with a bit-depth spinner (BC1a / BC2 / BC3) |
| No mip gamma correction | Disable gamma correction during mipmap generation (`-no-mip-gamma-correct`) |
| Normalization per mip | Renormalize normal-map vectors at each mip level (`-normal`) |
| Convert to normal | Convert the input image into a normal map before compression (`-tonormal`) |
| Ignore alpha | Treat the image as opaque even if it has an alpha channel (`-noalpha`) |
| Force alpha | Override auto-detection and force the alpha input hint (`-alpha`); mutually exclusive with Force color |
| Force color | Override auto-detection and force the color (no-alpha) input hint (`-color`); mutually exclusive with Force alpha |
| Range scale | Scale the image to the full color range before compression (`-rangescale`) |
| No CUDA | Disable CUDA acceleration and use the CPU compressor only (`-nocuda`) |
| RGBM encode | Pre-encode the image into RGBM before compression (`-rgbm`) |
| No mipmaps | Disable mipmap generation entirely (`-nomips`) |
| Max mip count | Cap the number of generated mip levels (`-max-mip-count`) |
| Min mip size | Skip mip levels smaller than this size (`-min-mip-size`) |
| Wrap | Edge sampling mode for mipmaps: clamp or repeat (`-clamp` / `-repeat`) |
| Override filter params | Manually set mipmap filter math parameters (Kaiser Width/Stretch, Mitchell B/C) |
| Weights (R/G/B/A) | Per-channel error weighting during compression (`-weight_r/g/b/a`) |

### DDS → PNG Tab

| Control | Description |
|---|---|
| Source target | Folder or single DDS file to convert |
| Output folder | Destination for PNG files. Blank = write alongside source DDS files |
| nvdecompress path | Path to the nvdecompress executable (optional) |
| Recursive scan | Search all subdirectories for DDS files |
| Mirror structure | Recreate source folder hierarchy in the output folder (requires Recursive scan) |
| Overwrite existing | Replace existing PNG files instead of skipping them |
| Delete source DDS | ⚠ Remove source DDS after successful PNG write |
| Dry run mode | Simulate extraction without writing any files |
| Workers | Number of parallel extraction jobs |

### Toolbar

| Control | Description |
|---|---|
| Save log | Write the full run log to a file when the conversion finishes |
| … | Choose where to save the log file |
| Clear log | Clear the log output and reset the progress bar |

---

## Output Routing

### With an output folder set

Output files are written to the specified destination. When **Recursive scan** and **Mirror structure** are both enabled, the source subfolder hierarchy is recreated inside the output folder.

```
Source:
Textures/
├── Armor/
│   └── iron.png
└── Weapons/
    └── sword.png

Output (mirrored):
Converted/
├── Armor/
│   └── iron.dds
└── Weapons/
    └── sword.dds
```

### With output folder left blank

Files are written directly alongside their source files.

```
Textures/
├── armor.png
└── armor.dds      ← written next to the source
```

This is also the default for a multi-file drag-and-drop selection (the output field is intentionally left blank), so every dropped file is converted in place regardless of how many folders it came from.

### Multi-drive selections with an output folder set

When a selection spans more than one drive there is no shared root to mirror from, so output is **keyed by drive** to keep identically named files from colliding:

```
Sources:
C:\tex\1.png
D:\tex\1.png

Output (Converted\, Mirror structure on):
Converted/
├── c_drive/
│   └── tex/
│       └── 1.dds
└── d_drive/
    └── tex/
        └── 1.dds
```

With Mirror structure off, each file lands directly under its drive folder (`Converted\c_drive\1.dds`, `Converted\d_drive\1.dds`).

**Cross-platform.** "Spans more than one drive" is detected by physical device id (`st_dev`), not by drive letter, so it works on Linux too — e.g. two SD cards on a Steam Deck mounted at `/run/media/deck/<uuid-A>` and `/run/media/deck/<uuid-B>`. There the "drive" folder is the **mount-point name** (`uuid-A`, or a sanitised label like `my_sd_card`) rather than `c_drive`/`d_drive`.

**How a cross-drive selection is assembled.** A single drag-and-drop comes from one location, so the realistic way to batch files from several drives is to **paste a list of paths** into the source field — newline- or `;`-separated, or Windows "Copy as path" output (quoted). The app stages those exactly like a multi-file drop. (However the list is assembled, the device-based detection classifies each file correctly.) Even if two same-named files would still land on one output path, the [collision guard](#features) refuses the run rather than overwriting.

---

## Workers & Performance

The worker count defaults to half your logical core count, capped at **4** on first launch. This conservative default avoids GPU memory contention, since simultaneous `nvcompress` jobs compete for VRAM (especially with BC7). The spinner lets you raise it up to a maximum of `min(16, logical cores)`.

Worker counts loaded from a saved config are clamped to the current machine's range, so a config copied from a higher core-count machine won't exceed the local limit.

Each worker spawns an independent `nvcompress` or `nvdecompress` subprocess, so higher worker counts increase both throughput and CPU/RAM usage proportionally.

**Global concurrency cap.** In the integrated app every tab shares one budget of simultaneous subprocesses (`min(16, logical cores)`), enforced by a shared semaphore. So running the converter *and* several suite tabs at once can't oversubscribe the GPU/CPU — extra jobs simply queue for a slot (and the wait stays cancellable). Standalone, each app caps itself.

**Large batches.** The visible log is bounded (oldest lines are trimmed once it grows past ~6000 lines) so a huge run can't balloon memory or slow the UI; the full log is still kept for **Save log**. Config files are written atomically (temp + rename), so a crash or a second instance can't leave a half-written, corrupt config.

---

## Settings Persistence

All settings are saved automatically when a run starts and restored on next launch.

Config file location:

- **Windows:** `%APPDATA%\DDSConverter\config.json`
- **Linux:** `~/.config/DDSConverter/config.json`

---

## Extended Toolset

`convert_textures_integrated.py` adds the following tabs alongside the two built-in PNG↔DDS tabs. Each tab front-ends a command-line program: point its **path field** at the executable (or leave the default name if it's on `PATH`), then use **Test** to verify it and (where available) **Show command** to preview the exact invocation. Every tool is optional — a tab simply reports "not found" if its binary is missing.

The tools are **binary-agnostic**: the DirectXTex tabs work with either Microsoft's official builds or a cross-platform build (e.g. matyalatte's Texconv-Custom-DLL on Linux), since the flags match. Settings for each tool persist to their own JSON file next to the main config.

### DirectXTex suite (`directx_texture_tools.py`)

| Tab | Tool | Purpose |
|---|---|---|
| Texconv | `texconv` | Full image → DDS converter. Every `texconv` flag is exposed (formats, filters, mips, BC options, resize, transforms, normal-map, naming, compute). Headline feature: **`--keep-coverage`** preserves alpha-test coverage across mips so alpha-tested foliage/fences don't thin out at distance. |
| Texassemble | `texassemble` | Build cubemaps, arrays, volumes, strips/crosses, merges and GIF arrays from input images. |
| Texdiag | `texdiag` | Inspect (`info`/`analyze`), `compare`/`diff`, and `dumpbc`/`dumpdds`. info/analyze print to the log per file. |

### NVTT suite (`nvtt_tools.py`)

| Tab | Tool | Purpose |
|---|---|---|
| Nvtt Export | `nvtt_export` | The NVIDIA Texture Tools Exporter CLI, fully front-ended: all formats (BC1–7, ASTC, UASTC, ETC1S, HDR float), quality, the full mipmap / image-processing / normal-map option groups, AI **super-resolution**, and **cutout-alpha + scale-alpha** for alpha-test coverage. An **Open** button launches the native executable (OS-aware: `os.startfile` on Windows, `open` for macOS `.app`, detached `Popen` on Linux). |
| DDS Info | `nvddsinfo` | Print DDS metadata to the log, per file. |
| Image Diff | `nvimgdiff` | Compare two images (normal/alpha/range-scale modes) with an optional difference image. |

> `nvcompress` and `nvdecompress` are not duplicated here — they already power the built-in PNG→DDS / DDS→PNG tabs. `nvbatchcompress` is omitted as it's just the batch form of `nvcompress`.

### Control reference

Every suite tab also has the shared path fields (source/input, output, and the tool's executable path with **Test**), a **Threads** spinner for parallel jobs, **Show command**, **Save log**, and a **? Guide** button that opens a full in-app guide for that tool (the same depth as the main converter's Help). The tables below cover each tab's tool-specific options, with the CLI flag it maps to. Value fields marked with an enable checkbox (see Notes) only emit their flag when ticked.

#### Texconv (`texconv`)

| Control | Description |
|---|---|
| Format | DDS pixel format: BC1 opaque/1-bit, BC3 full alpha, BC4/BC5 1- & 2-channel (normals), BC6H HDR, BC7 best RGBA (`-f`) |
| Filter | Resampling/mip filter — FANT, LINEAR, CUBIC, TRIANGLE (`-if`) |
| Out type | Output container: dds, or tga/hdr/png to export the decoded image (`-ft`) |
| Mips | Mip levels: 0 = full chain, 1 = base only (`-m`) |
| Colour | Colour-space handling: sRGB / sRGB in / sRGB out / Linear (`-srgb` / `-srgbi` / `-srgbo`) |
| Ignore sRGB meta | Treat pixels as-is, ignoring any sRGB tag (`--ignore-srgb`) |
| Premultiply alpha | Multiply colour by alpha before compressing (`-pmalpha`) |
| Straight alpha | Convert premultiplied alpha back to straight (`-alpha`) |
| Expand luminance | Expand legacy L8/L16/A8P8 to RGBA (`-xlum`) |
| Preserve alpha coverage | Keep alpha-test coverage constant across mips (`--keep-coverage`) |
| Alpha ref | Alpha-test cutoff used by coverage and written as the reference (`-at`) |
| Separate alpha | Mip the alpha channel independently for crisp edges (`-sepalpha`) |
| BC dither / uniform / quick / max | Block-compression options: dithering, uniform weighting, fast, max quality (`-bc d/u/q/x`) |
| BC7 alpha weight | Spend more BC7 bits on alpha (BC7 only) (`-aw`) |
| Width / Height | Resize output; off = source size (`-w` / `-h`) |
| Fit pow-of-2 | Round dimensions up to a power of two (`-pow2`) |
| Feature lvl | Clamp max size to a Direct3D feature level (`-fl`) |
| Header | DDS header: DX10 (extended) or legacy DX9 (`-dx10` / `-dx9`) |
| DWORD align | Align scanlines to 4 bytes in legacy DDS (`-dword`) |
| H-flip / V-flip | Mirror horizontally / vertically (`-hflip` / `-vflip`) |
| Invert Y | Flip green channel — OpenGL ↔ DirectX normals (`--invert-y`) |
| Reconstruct Z | Rebuild normal-map Z from R/G for BC5 (`--reconstruct-z`) |
| ×2−1 bias | Remap 0..1 to −1..1 for normals (`--x2-bias`) |
| Swizzle | Reorder/duplicate channels with a 4-letter mask (`--swizzle`) |
| Height → normal | Generate a tangent-space normal map from a height map (`-nmap`) |
| nmap opts / Amplitude | Normal channels/options and bump strength (`-nmap` / `-nmapamp`) |
| Rotate colour | Convert HDR colour primaries, e.g. Rec.709 ↔ Rec.2020 (`--rotate-color`) |
| Tonemap / Paper-white nits | Reinhard tone-map for HDR→SDR and its paper-white level (`--tonemap` / `-nits`) |
| Typeless→UNORM / →FLOAT | Read typeless source as UNORM / FLOAT (`-tu` / `-tf`) |
| Colour key | Make a hex RGB colour transparent (`-c`) |
| Prefix / Suffix / Lowercase | Output filename prefix, suffix, lowercase (`-px` / `-sx` / `-l`) |
| Addressing | Edge addressing: clamp / wrap / mirror (`-wrap` / `-mirror`) |
| Bad tails / Permissive / Ignore mips / Fix BC 4x4 | DDS-input fix-ups (`--bad-tails` / `--permissive` / `--ignore-mips` / `--fix-bc-4x4`) |
| No GPU / GPU # | CPU-only compression, or pick a GPU adapter (`-nogpu` / `-gpu`) |
| Single-proc / Timing / Non-WIC | Single-threaded, print timing, built-in loaders (`--single-proc` / `--timing` / `-nowic`) |

#### Texassemble (`texassemble`)

| Control | Description |
|---|---|
| Command | Operation: cube/cubearray, array, volume, merge, gif, and cube-from-* layouts |
| Format / Filter / Colour / Feature lvl | Assembled DDS format, resize filter, colour space, size clamp (`-f` / `-if` / `-fl`) |
| Width / Height | Force each input to this size before assembling (`-w` / `-h`) |
| Mips | Mip levels per input — *-from-mips commands only (`-m`) |
| Addressing | Edge addressing when filtering (`-wrap` / `-mirror`) |
| Swizzle | Channel-select mask for the merge command (`--swizzle`) |
| Recursive | Search subfolders when the input is a folder (`-r`) |
| Overwrite / Lowercase | Replace existing output; lowercase the name (`-y` / `-l`) |
| Separate alpha | Resize alpha separately from colour (`-sepalpha`) |
| DX10 header | Extended header — required for arrays/cube arrays (`-dx10`) |
| Straight alpha | Treat input alpha as non-premultiplied (`-alpha`) |
| Tonemap (gif) | Tone-map HDR inputs when building a GIF (`-tonemap`) |
| GIF bg colour | Composite transparent GIF frames over a background (`--gif-bg-color`) |
| Strip mips | Drop input mipmaps before assembling (`--strip-mips`) |
| Non-WIC | Built-in image loaders instead of WIC (`-nowic`) |

#### Texdiag (`texdiag`)

| Control | Description |
|---|---|
| Command | info, analyze, compare, diff, dumpbc, dumpdds |
| Diff format | Pixel format of the diff image (`-f`) |
| Diff colour / Threshold | Highlight colour and difference threshold for diff (`-c` / `-t`) |
| Target X / Target Y | Block coordinates for dumpbc (`--target-x` / `--target-y`) |
| Overwrite / Lowercase | Replace existing output; lowercase the name (`-y` / `-l`) |
| Typeless→UNORM / →FLOAT | Read typeless source as UNORM / FLOAT (`-tu` / `-tf`) |
| DWORD align | Assume legacy DWORD-aligned scanlines (`-dword`) |
| Bad tails / Permissive / Ignore mips | DDS-input fix-ups (`--bad-tails` / `--permissive` / `--ignore-mips`) |
| Expand luminance | Expand L8/L16/A8P8 to RGBA before analysing (`-xlum`) |

#### Nvtt Export (`nvtt_export`)

| Control | Description |
|---|---|
| Format | bc1–bc7, uncompressed rgba8/rgba16f, ASTC variants (`-f`) |
| Quality | fastest / normal / production / highest (`-q`) |
| Type | 2D texture or cubemap (`-t`) |
| No CUDA | CPU-only compression (`--no-cuda`) |
| DX10 header | Extended DXT10 header — required for BC6/BC7/arrays (`--dx10`) |
| Transfer fn | Tag output transfer function: linear or sRGB (`--export-transfer-function`) |
| Super-res | AI-upscale 2× or 4× (Turing+ GPU) (`--super-res`) |
| Mipmaps / Mip filter | Generate mip chain; filter box/kaiser/mitchell/… (`--mips` / `--no-mips` / `--mip-filter`) |
| Max mips / Min mip size / Filter width | Cap level count, stop size, filter kernel width (`--max-mip-count` / `--min-mip-size` / `--mip-filter-width`) |
| Filter params (P1/P2) | Kaiser/Mitchell shape parameters (`--mip-filter-param-1` / `-2`) |
| Mip gamma correct | Downsample in linear light; off mips in gamma space (`--no-mip-gamma-correct`) |
| Mip pre-alpha | Premultiply while downsampling so edges don't bleed (`--no-mip-pre-alpha`) |
| To grayscale / Wrap to range / Export pre-alpha | Grayscale, fit output range, premultiplied export (`--to-grayscale` / `--wrap-to-output-range` / `--export-pre-alpha`) |
| Weights R/G/B/A | Per-channel compression error weight (`--weight-*`) |
| Bias R/G/B/A | Per-channel additive bias (`--bias-*`) |
| Cutout alpha / Scale alpha / Cutout dither | Alpha-test cutout, keep coverage in mips, dither the edge (`--cutout-alpha` / `--scale-alpha` / `--cutout-alpha-dither`) |
| Alpha threshold | Opaque/transparent split for cutout, 0–255 (`--alpha-threshold`) |
| Save flip-Y / Read flip-Y | Flip vertically on write / on DDS read (`--save-flip-y` / `--read-flip-y`) |
| Normal map | off / tangent-space / object-space (`--to-normal` / `--to-normal-os`) |
| Normal filter / Height from / Normal alpha | Normal kernel, height source, alpha contents (`--normal-filter` / `--height` / `--normal-alpha`) |
| Clamp normals / Invert X / Invert Y / Slope-space | Edge clamp, flip X/Y, leave un-normalised (`--clamp` / `--normal-invert-x` / `--normal-invert-y` / `--slope-space`) |
| Min Z / Scale | Min Z component and bump strength for normals (`--normal-min-z` / `--normal-scale`) |

#### DDS Info (`nvddsinfo`)

| Control | Description |
|---|---|
| DDS file / folder | A single `.dds` or a folder of them to inspect |
| Recursive scan | Search subfolders for `.dds` when the input is a folder |

#### Image Diff (`nvimgdiff`)

| Control | Description |
|---|---|
| Original / Updated file | The two images to compare |
| Diff image (optional) | Where to write a visual difference image, e.g. `.tga` |
| Normal map | Compare as normal maps (angular error) (`-normal`) |
| Alpha weighted | Weight the comparison by alpha (`-alpha`) |
| Range scale | Scale the 2nd image into the 1st's range, for HDR (`-rangescale`) |

### Notes

- **Drag & drop** works on every suite tab too — drop a file or folder anywhere on the tab, **including onto the log pane**, to fill its source field (requires `tkinterdnd2`; without it, use the Folder…/File… buttons).
- **Optional value fields** — every option value field sits behind an enable checkbox, exactly like the PNG↔DDS tabs' *Max mip count* override: spinboxes and numeric entries (Mips, Width/Height, GPU#, mip params, RGBA weights/biases, alpha threshold, diff threshold, target X/Y) and the text fields (swizzle, colour key, prefix/suffix, diff colour). The field is disabled until ticked, and its flag is omitted from the command while off, so you only send the switches you mean to. Weights, biases and the two filter params share one grouped toggle each. Only the always-needed Threads count is ungated.
- Tools that open a GUI when run with no arguments (nvtt_export) are probed for verification with `--help`, so **Test** never launches the GUI. An **Open** button on the Nvtt Export tab launches the native executable (OS-aware).
- Each suite panel snapshots its Tk variables into a frozen `*Opts` dataclass on the main thread (`_gather_opts()`), then its `_build_cmd(opts, …)` builds the command list from that snapshot alone. Worker threads therefore never touch Tk, and the command builders are pure functions — unit-testable without a display.
- **Save log** — every suite tab has a *Save log* checkbox in its action bar. Tick it (optionally pick a path; blank writes a timestamped file to the config folder) and the full run log is written to disk when the run finishes.
- **Collision guard** — before a folder conversion runs, Texconv and Nvtt Export check whether two sources would resolve to the same output file (e.g. `a/tex.png` and `b/tex.png` with mirroring off, or `tex.png` and `tex.tga` in one folder). If so the run is refused with the offending names listed, rather than silently overwriting — enable *Mirror subfolders* or disambiguate with a prefix/suffix.
- **Worker count** is clamped to this machine's CPU range on load, so a config copied from a higher-core machine can't request more threads than are available.
- **Per-file inspection (DDS Info, texdiag info/analyze/dumpbc/dumpdds)** reads files in parallel and streams results **in sorted order, incrementally** (a few at a time, yielding to the UI between chunks) — so a big folder (hundreds of files) never freezes the window and output appears as it goes, in order. Each file is shown as a **compact one-line summary**; **double-click a line to expand its full output** in a popup. The full raw output is held in a **session cache** keyed by `(path, mtime, size)` — re-running skips files that haven't changed (instant), and because the cache is in-memory only and revalidated on every read, it can never serve stale results. Tick **Save log** to write the **complete raw output** (the permanent backup) to a file, even though the live view only shows summaries. (Read-only commands are cached; `dumpdds`, which writes files, always runs.)

---

## Tech Stack

| Component | Role |
|---|---|
| Python | File I/O, threading, subprocess management |
| Tkinter + tkinterdnd2 | GUI and drag & drop support |
| Pillow | Alpha channel detection, DDS fallback decoding, TGA→PNG conversion |
| NVIDIA Texture Tools | `nvcompress`/`nvdecompress` (core converter), plus `nvtt_export`, `nvddsinfo`, `nvimgdiff` (extended toolset) |
| DirectXTex | `texconv`, `texassemble`, `texdiag` (extended toolset) |
