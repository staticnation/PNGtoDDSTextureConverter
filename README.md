# DDS ↔ PNG Texture Converter (GUI)

A multi-threaded batch texture conversion utility with a graphical interface.

This application provides a frontend for NVIDIA Texture Tools' `nvcompress` utility, exposing detailed control over DDS compression formats, mipmap generation, and batch processing workflows.

Originally developed as a PNG-to-DDS conversion utility, the project has been expanded into a complete bidirectional texture pipeline supporting:

- PNG → DDS compression
- DDS → PNG extraction

Standalone binaries are provided for Windows and Linux.

---

# Features

## PNG → DDS Conversion

Uses NVIDIA Texture Tools (`nvcompress`) for DDS texture compression.

Supported formats include:

- BC1 / DXT1
- BC1a
- BC2 / DXT3
- BC3 / DXT5
- BC4
- BC5 / ATI2
- BC6 HDR
- BC6 Signed HDR
- BC7
- ASTC formats (depending on `nvcompress` support)
- Uncompressed RGBA

### Automatic Format Selection

The converter can automatically determine an appropriate compression format by analyzing texture alpha data.

```
Opaque texture
    -> BC1

Alpha texture
    -> BC3
```

---

## DDS → PNG Conversion

Uses Pillow for DDS decoding.

Features:

- Recursive DDS scanning
- RGBA PNG output
- Optional output directory
- Optional DDS deletion after successful conversion
- Overwrite protection
- Dry-run mode

---

# Compression Controls

## Quality Profiles

Available compression presets:

- Fastest
- Normal
- Production
- Highest

Higher quality settings increase processing time.

---

## Mipmap Filtering

Supports multiple mipmap generation filters:

- Kaiser
- Mitchell-Netravali
- Box
- Triangle
- Min
- Max

Advanced filter parameters can be manually overridden.

Examples:

```
Kaiser:
    Width
    Stretch

Mitchell-Netravali:
    B
    C
```

---

# Batch Processing

## Multi-threaded Conversion

PNG → DDS conversion uses a configurable worker pool.

Multiple `nvcompress` instances can run simultaneously to improve throughput during large texture conversions.

---

## Recursive Processing

The converter can scan nested directories.

Example:

```
Textures/
├── Armor/
│   └── iron.png
└── Weapons/
    └── sword.png
```

With mirror mode enabled:

```
Output/
├── Armor/
│   └── iron.dds
└── Weapons/
    └── sword.dds
```

---

# Conversion Options

| Option | Description |
|---|---|
| Recursive Scan | Search subdirectories for textures |
| Mirror Structure | Preserve source folder hierarchy in output |
| Overwrite Existing | Replace existing files instead of skipping |
| Alpha Dithering | Reduce alpha banding artifacts |
| Dry Run | Validate conversion without writing files |
| Workers | Control parallel conversion jobs |

---

# Process Management

The application tracks active conversion processes and provides safe cancellation.

On cancellation:

Windows:

```
taskkill /F /T
```

Linux:

```
process group termination
```

This prevents orphaned `nvcompress` processes from remaining after interrupted conversions.

---

# Requirements

## Standalone Releases

The distributed binaries do not require Python.

The only external requirement is:

```
nvcompress
```

`nvcompress` must either:

- Be available in the system PATH
- Be selected manually through the application interface

---

## Supported Platforms

- Windows 10 / Windows 11 (64-bit)
- Linux (64-bit)

---

# Usage

## PNG → DDS

1. Select the texture source folder.
2. Select an output folder, or leave blank for in-place conversion.
3. Configure compression settings.
4. Start conversion.

Example:

Input:

```
textures/
├── armor.png
├── weapon.png
└── icon.png
```

Output:

```
textures/
├── armor.dds
├── weapon.dds
└── icon.dds
```

---

## DDS → PNG

1. Select the DDS source folder.
2. Select an output folder if desired.
3. Configure overwrite/delete options.
4. Start conversion.

---

# Credits

Built with:

- Python
- Tkinter
- Pillow
- NVIDIA Texture Tools (`nvcompress`)
