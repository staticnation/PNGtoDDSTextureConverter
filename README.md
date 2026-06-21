# DDS ↔ PNG Texture Converter (GUI)

A multi-threaded batch texture converter with a dark-themed GUI, supporting bidirectional conversion between PNG and DDS formats.

- **PNG → DDS** via NVIDIA Texture Tools (`nvcompress`)
- **DDS → PNG** via `nvdecompress` with automatic Pillow fallback

Standalone pre-compiled binaries are available for Windows and Linux — no Python installation required.

---

## Requirements

- `nvcompress` — required for PNG → DDS compression
- `nvdecompress` — optional but recommended for DDS → PNG; Pillow is used as a fallback if unavailable or if decoding fails

Both executables must be either on your system `PATH` or pointed to manually via the application's path fields.

---

## Features

### Drag & Drop

Files and folders can be dragged directly onto the converter window instead of using the Browse buttons.

- **Drop a folder** — sets the source field and scans it for convertible files
- **Drop a single file** — targets that file for a one-shot conversion
- **Drop multiple files** — stages only those specific files as conversion targets, ignoring everything else in their parent folder

The window detects which tab is active and routes drops accordingly. PNG files are accepted on the PNG → DDS tab; DDS files on the DDS → PNG tab. Drops containing the wrong file type are rejected with a warning in the log.

### PNG → DDS Compression

- Parallel compression using a `ThreadPoolExecutor` worker pool — spawns multiple `nvcompress` subprocesses simultaneously
- **Auto format** — detects alpha channel presence and automatically selects BC1 (opaque) or BC3 (transparent) per file
- Format list is dynamically filtered to only show formats your installed version of `nvcompress` actually supports
- Full BC format support: BC1, BC1a, BC2, BC3, BC4, BC5, BC6, BC6s, BC7, ATI2, BC1n, BC3n, BC5s, BC3-RGBM, all ASTC LDR block sizes, and uncompressed RGBA
- Normal map formats (BC1n, BC3n, BC5, ATI2) automatically pass `-normal` to `nvcompress`
- BC6, BC6s, BC7, and ASTC formats automatically use the DDS10 header extension
- Mipmap filter selection: Box, Triangle, Min, Max, Kaiser, Mitchell — with optional manual parameter overrides for Kaiser (Width/Stretch) and Mitchell (B/C coefficients)
- Quality presets: Fastest, Normal, Production, Highest
- Alpha dithering for BC1a / BC2 / BC3
- Gamma correction flag
- Recursive folder scan with optional folder structure mirroring in the output
- Overwrite protection (skip existing DDS files by default)
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
| Alpha dithering | Reduce banding on transparent edges (BC1a / BC2 / BC3) |
| Gamma correction | Apply gamma correction for linear color space output |
| Dry run mode | Simulate conversion without writing any files |
| Override filter params | Manually set mipmap filter math parameters |

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

---

## Workers & Performance

The worker count defaults to half your logical core count on most systems. On machines with more than 32 logical cores (e.g. Threadripper), the default is capped at 32 to avoid spinning up an excessive number of subprocesses on first launch. The spinner lets you go higher if needed.

Each worker spawns an independent `nvcompress` or `nvdecompress` subprocess, so higher worker counts increase both throughput and CPU/RAM usage proportionally.

---

## Settings Persistence

All settings are saved automatically when a run starts and restored on next launch.

Config file location:

- **Windows:** `%APPDATA%\DDSConverter\config.json`
- **Linux:** `~/.config/DDSConverter/config.json`

---

## Tech Stack

| Component | Role |
|---|---|
| Python | File I/O, threading, subprocess management |
| Tkinter + tkinterdnd2 | GUI and drag & drop support |
| Pillow | Alpha channel detection, DDS fallback decoding, TGA→PNG conversion |
| NVIDIA Texture Tools | `nvcompress` for compression, `nvdecompress` for extraction |
