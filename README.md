# PNG to DDS Texture Converter (GUI)

An advanced, multi-threaded batch conversion tool built with a sleek dark-themed user interface. This application acts as a high-performance front-end for NVIDIA's `nvcompress` binary, providing meticulous control over the DirectDraw Surface (DDS) block compression spectrum and mipmap downsampling mechanics. 

Distributed as a standalone Windows executable (`.exe`) compiled via `auto-py-to-exe` for zero-dependency deployment.

---

## 🚀 Key Features

* **Zero Python Dependencies:** Packaged neatly into a standalone executable file. Users do not need Python, Pillow, or any external libraries installed on their system to run the application.
* **Dynamic Threading Pool:** Leverages a `ThreadPoolExecutor` worker pool allowing simultaneous parallel executions of `nvcompress` subprocesses to maximize CPU utilization.
* **Intelligent Input Transmutation (`Auto` Mode):** Safely parses image metadata. It profiles alpha channels dynamically, auto-routing opaque structures to **BC1** and transparent surfaces to **BC3** fallback algorithms.
* **Granular Profile Switching:** Automatically flags specialized normal map compressions (`BC1n`, `BC3n`, `BC5`, `ATI2`) with the `-normal` profile modifier, and handles high-fidelity modern structures like **BC7** or **BC6/BC6s (HDR)** under exact color/alpha boundaries.
* **Custom Mipmap Engine Parameters:** Exposes full native overrides for filter kernels (such as Kaiser width/stretch parameters or Mitchell-Netravali B/C balances) alongside standard mathematical downsizers (`box`, `triangle`, `min`, `max`).
* **Asynchronous Subprocess Tree-Killing:** Uses low-level system process mapping (`taskkill /F /T` on Windows) to instantly force-terminate active threads when processing is cancelled by the user.
* **Automated State Persistence:** Automatically saves paths, formats, threading scales, and engine configurations to a local `convert_textures_config.json` file on execution.

---

## 📋 Interface Overview

| Control Element | Functionality |
| :--- | :--- |
| **Texture Folder** | Base directory tracking down target PNG inputs. |
| **Output Folder** | Defines destination directory. *If left blank, files generate directly next to their source targets*. |
| **Workers** | Allocates execution parallelism. (Defaults to half of available hardware threads up to 4). |
| **Recursive Scan** | Scans nested subdirectory trees for target image sequences. |
| **Mirror Structure** | Recreates exact sub-folder trees inside your output directory when scanning recursively. |
| **Alpha Dithering** | Minimizes color gradient banding over narrow bit layouts (`BC1a`, `BC2`, `BC3`). |
| **Dry Run Mode** | Validates structural targets, path resolutions, and pipeline configurations without writing files to disk. |

---

## 📂 Output Behavior Mechanics

The app adapts its file-writing logic based on your destination setup:

* **Explicit Output Directory:** When a destination folder is chosen, all converted `.dds` files are funneled there. If **Recursive Scan** and **Mirror Structure** are both active, the app dynamically builds and replicates your source folder tree inside the destination.
* **In-Place (No Output Folder Selected):** If you leave the **Output folder** field empty, the converter falls back to an in-place routine. Every `.dds` file is created inside the exact same subdirectory as its parent `.png` file. This is perfect for modding setups where textures need to remain integrated within their native folder structures.

---

## 🛠️ Dependencies & Requirements

The standalone executable eliminates the need for any language runtime or environment dependencies. There is **only one requirement** to use this application:

1. **NVIDIA Texture Tools (`nvcompress`)**: The execution binary must either exist on your system's environment `PATH` variables or be explicitly specified using the executable file browser built into the application interface.

*Supported OS: Windows 10 / 11 (64-bit)*

---

## 💻 How To Use

### 1. Launch the Application
Simply double-click your compiled executable file (e.g., `convert_textures_gui.exe`) to launch the interface.

### 2. Configure Pipelines & Run
1. **Paths:** Select your source **Texture folder**. Choose an **Output folder** if you want to export elsewhere, or leave it blank for in-place conversion.
2. **Validation:** Click the **Test** button next to your `nvcompress` path. The tool will ping the utility framework (`nvcompress -profile`) to verify alignment.
3. **Options:** Select your compression format profile (e.g., *Auto*, *BC5* for separate normal maps, or *BC7* for modern assets) and pick a downsampling filter.
4. **Execute:** Click **Convert Textures**. The runtime bar updates synchronously, logging output errors or successful conversions into the lower interactive workspace text buffer.

### 3. Graceful Interruption
If an execution loop hangs due to an input disk locking error or massive asset footprints, click the red **Cancel** button. This intercepts the active pool, sends an explicit termination flag downstream to all subprocess PIDs, safely cleans memory spaces, and prints a final failure summary.
