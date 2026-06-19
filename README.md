# DDS ↔ PNG Texture Converter (GUI)

### High-Performance Batch Texture Processing Pipeline

The **DDS ↔ PNG Texture Converter** is a professional-grade, multi-threaded batch utility designed to streamline texture compression and extraction workflows. By providing a robust graphical user interface (GUI) wrapper for the NVIDIA Texture Tools (`nvcompress`) executable, the application exposes granular control over DirectDraw Surface (DDS) encoding, mipmap generation algorithms, and parallelized processing execution.

Engineered originally for high-throughput PNG-to-DDS compilation, the utility features a fully bidirectional workflow supporting:

* **PNG → DDS Compression:** High-fidelity encoding optimized for modern graphics pipelines.
* **DDS → PNG Extraction:** Clean decoding and unpacking of asset structures back into raw image formats.

Standalone, pre-compiled binaries are available for both Windows and Linux environments.

---

## Technical Features

### Standalone Deployment Architecture

The production binaries are fully self-contained executables, eliminating the overhead of environment configuration.

* **Zero External Runtimes:** End-users do not require a local installation of Python, Pillow, or corresponding development libraries.
* **Core Dependency:** The only technical prerequisite for the PNG → DDS compression vector is the availability of the NVIDIA Texture Tools `nvcompress` executable.

### Asynchronous Multi-Threaded Engine

The processing core leverages a dynamically scaled `ThreadPoolExecutor` worker pool to dispatch concurrent conversion subprocesses, maximizing multi-core CPU utilization.

* **Parallel Execution:** Spawns isolated `nvcompress` subprocess instances simultaneously.
* **Optimized Throughput:** Minimizes execution bottlenecks when processing massive structural asset repositories.
* **Resource-Aware Defaults:** Automatically monitors system hardware limitations, defaulting thread allocation to approximately 50% of available logical processors (capped at 4 concurrent workers out-of-the-box).

### Intelligent Channel Transmutation (Auto Mode)

The application integrates an automated metadata parser that evaluates image properties prior to execution, executing intelligent routing based on alpha channel topology:

```
[Input Surface] ──> [Metadata Profiling] ──┬──> Opaque ──────> BC1 Encoding
                                           └──> Transparent ──> BC3 Fallback
```

This automated pipeline guarantees optimal VRAM footprint compression without requiring manual batch sorting from technical artists.

### Advanced Compression & Profile Switching

The application provides direct programmatic access to native Block Compression (BC) formats and specialized texture profiles:

* **Standard Formats:** BC1 / DXT1 (including BC1a), BC2 / DXT3, BC3 / DXT5, and raw uncompressed RGBA layouts.
* **High-Fidelity Profiles:** Advanced support for BC4, BC5 / ATI2, BC6s (HDR Signed/Unsigned), and BC7 surface constraints.
* **Adaptive Normal Map Handling:** Profiles assigned to BC1n, BC3n, BC5, and ATI2 automatically pass the native `-normal` modifier to the backend compiler, ensuring proper vector normalization.

### Granular Mipmap Filtering Engine

Provides low-level access to the downsampling parameters of the NVIDIA Texture Tools pipeline.

* **Mathematical & Convoluted Filters:** Supports Box, Triangle, Min, Max, Kaiser, and Mitchell-Netravali sampling kernels.
* **Native Kernel Parameter Overrides:** Advanced configuration fields expose internal tuning vectors, such as Width and Stretch for Kaiser filters, or B and C balance coefficients for Mitchell-Netravali functions.

### DDS Unpacking & Asset Extraction

The reverse pipeline features a robust DDS-to-PNG extraction matrix designed to safely deconstruct pre-compressed assets:

* Deep recursive directory scanning for automated asset discovery.
* Lossless RGBA PNG output derivation.
* Destructive asset cleanup options (optional auto-deletion of source DDS files post-extraction).
* Integrity constraints, including strict overwrite protection and dry-run validation logs.

### Process Management & Asynchronous Tree-Killing

To prevent system instability or orphaned background processes, the application actively tracks the process identifier (PID) tree of all spawned subprocesses.

* **Abrupt Cancellation:** If a batch sequence is aborted by the user, the application invokes explicit low-level system calls (`taskkill /F /T` on Windows environments; process-group termination via signals on Linux environments).
* **Resource Integrity:** Guarantees instant release of system memory and processor handles upon user cancellation.

---

## GUI Control Interface Matrix

| Parameter Control | Functional Description |
| --- | --- |
| **Texture Folder** | Targets the root source directory containing source PNG or DDS assets. |
| **Output Folder** | Defines the target destination directory. Leaving this blank flags an in-place configuration. |
| **Workers** | Manually sets the upper boundary for parallel subprocess thread allocation. |
| **Recursive Scan** | Instructs the parser to traverse nested subdirectory structures. |
| **Mirror Structure** | Replicates the absolute source directory topology inside the target output folder. |
| **Compression Format** | Selects the target DDS block compression layout (BC1 through BC7). |
| **Quality** | Calibrates the trade-off calculation between compression speed and block encoding precision. |
| **Alpha Dithering** | Minimizes quantization banding artifacts across limited-bit alpha channels. |
| **Dry Run Mode** | Validates structural paths and checks execution arguments without writing data to disk. |
| **Cancel** | Terminates all active child processes and clears the executor queue instantly. |

---

## Output Routing Behaviors

The system dynamically adapts its file system operations depending on the explicit destination settings configured by the user.

### 1. Explicit Output Redirection

When a distinct destination path is targeted, output files are directed away from the source files. When coupled with Recursive Scan and Mirror Structure, the application mirrors the source asset trees flawlessly.

```
Source Asset Hierarchy:
Textures/
├── Armor/
│   └── iron.png
└── Weapons/
    └── sword.png

Mirrored Destination Output:
Converted/
├── Armor/
│   └── iron.dds
└── Weapons/
    └── sword.dds
```

### 2. In-Place Asset Compilation

If the destination path is left blank, target files are compiled directly inside the source directory beside their respective ancestors.

```
Textures/
└── armor.png

Compiled Result:
Textures/
├── armor.png
└── armor.dds
```

*Note: This execution methodology is highly optimized for game modification and production environments that mandate strict structural maintenance of game-ready virtual file systems.*

---

## Deployment Prerequisites

### Pre-Compiled Binaries

The standalone distribution requires no localized Python installation or runtime configuration.

* **Core Dependency:** The system requires access to `nvcompress`.
* **Pathing Requirements:** The `nvcompress` executable must either be mapped inside the global system environment `PATH` variable, or targeted explicitly via the application's configuration parameters.

### Supported Environments

* **Windows:** Windows 10 / Windows 11 (64-bit Architecture)
* **Linux:** Modern Linux Distributions (64-bit GLIBC Core)

---

## Operating Procedures

### PNG → DDS Production Pipeline

1. Input the target path into the **Texture Folder** field.
2. Specify an **Output Folder** path, or leave it blank to execute an in-place build.
3. Select the required **Compression Profile**, quality parameters, and mipmap filter characteristics.
4. Execute the sequence by clicking the **Start** action.

### DDS → PNG Extraction Pipeline

1. Input the source directory path into the **Texture Folder** field.
2. Establish a target destination folder if data separation is required.
3. Configure extraction conditions (e.g., toggle overwrite guards or post-conversion source deletion preferences).
4. Execute the extraction array by clicking the **Start** action.

---

## Technical Stack Credentials

Engineered utilizing industry-standard automation frameworks:

* **Python Backend Engine:** Handles file system I/O operations, structural parsing, and asynchronous threading routines.
* **Tkinter User Interface:** Lightweight, native UI wrapper layer ensuring minimal memory footprints.
* **Pillow Library Integration:** Facilitates fast, low-level image metadata analysis and alpha channel bitmask profiling.
* **NVIDIA Texture Tools Core:** Utilizes the industry-standard `nvcompress` processing matrix for high-fidelity texture compilation.
