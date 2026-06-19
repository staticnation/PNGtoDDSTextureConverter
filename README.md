<h1>DDS &harr; PNG Texture Converter (GUI)</h1>
<h3>High-Performance Batch Texture Processing Pipeline</h3>

<p>The <strong>DDS &harr; PNG Texture Converter</strong> is a professional-grade, multi-threaded batch utility designed to streamline texture compression and extraction workflows. By providing a robust graphical user interface (GUI) wrapper for the NVIDIA Texture Tools (<code>nvcompress</code>) executable, the application exposes granular control over DirectDraw Surface (DDS) encoding, mipmap generation algorithms, and parallelized processing execution.</p>

<p>Engineered originally for high-throughput PNG-to-DDS compilation, the utility features a fully bidirectional workflow supporting:</p>
<ul>
    <li><strong>PNG &rarr; DDS Compression:</strong> High-fidelity encoding optimized for modern graphics pipelines.</li>
    <li><strong>DDS &rarr; PNG Extraction:</strong> Clean decoding and unpacking of asset structures back into raw image formats.</li>
</ul>

<p>Standalone, pre-compiled binaries are available for both Windows and Linux environments.</p>

<hr>

<h2>Technical Features</h2>

<h3>Standalone Deployment Architecture</h3>
<p>The production binaries are fully self-contained executables, eliminating the overhead of environment configuration.</p>
<ul>
    <li><strong>Zero External Runtimes:</strong> End-users do not require a local installation of Python, Pillow, or corresponding development libraries.</li>
    <li><strong>Core Dependency:</strong> The only technical prerequisite for the PNG &rarr; DDS compression vector is the availability of the NVIDIA Texture Tools <code>nvcompress</code> executable.</li>
</ul>

<h3>Asynchronous Multi-Threaded Engine</h3>
<p>The processing core leverages a dynamically scaled <code>ThreadPoolExecutor</code> worker pool to dispatch concurrent conversion subprocesses, maximizing multi-core CPU utilization.</p>
<ul>
    <li><strong>Parallel Execution:</strong> Spawns isolated <code>nvcompress</code> subprocess instances simultaneously.</li>
    <li><strong>Optimized Throughput:</strong> Minimizes execution bottlenecks when processing massive structural asset repositories.</li>
    <li><strong>Resource-Aware Defaults:</strong> Automatically monitors system hardware limitations, defaulting thread allocation to approximately 50% of available logical processors (capped at 4 concurrent workers out-of-the-box).</li>
</ul>

<h3>Intelligent Channel Transmutation (Auto Mode)</h3>
<p>The application integrates an automated metadata parser that evaluates image properties prior to execution, executing intelligent routing based on alpha channel topology:</p>

<pre><code>[Input Surface] ──> [Metadata Profiling] ──┬──> Opaque ──────> BC1 Encoding
                                           └──> Transparent ──> BC3 Fallback</code></pre>

<p>This automated pipeline guarantees optimal VRAM footprint compression without requiring manual batch sorting from technical artists.</p>

<h3>Advanced Compression &amp; Profile Switching</h3>
<p>The application provides direct programmatic access to native Block Compression (BC) formats and specialized texture profiles:</p>
<ul>
    <li><strong>Standard Formats:</strong> BC1 / DXT1 (including BC1a), BC2 / DXT3, BC3 / DXT5, and raw uncompressed RGBA layouts.</li>
    <li><strong>High-Fidelity Profiles:</strong> Advanced support for BC4, BC5 / ATI2, BC6s (HDR Signed/Unsigned), and BC7 surface constraints.</li>
    <li><strong>Adaptive Normal Map Handling:</strong> Profiles assigned to BC1n, BC3n, BC5, and ATI2 automatically pass the native <code>-normal</code> modifier to the backend compiler, ensuring proper vector normalization.</li>
</ul>

<h3>Granular Mipmap Filtering Engine</h3>
<p>Provides low-level access to the downsampling parameters of the NVIDIA Texture Tools pipeline.</p>
<ul>
    <li><strong>Mathematical &amp; Convoluted Filters:</strong> Supports Box, Triangle, Min, Max, Kaiser, and Mitchell-Netravali sampling kernels.</li>
    <li><strong>Native Kernel Parameter Overrides:</strong> Advanced configuration fields expose internal tuning vectors, such as Width and Stretch for Kaiser filters, or B and C balance coefficients for Mitchell-Netravali functions.</li>
</ul>

<h3>DDS Unpacking &amp; Asset Extraction</h3>
<p>The reverse pipeline features a robust DDS-to-PNG extraction matrix designed to safely deconstruct pre-compressed assets:</p>
<ul>
    <li>Deep recursive directory scanning for automated asset discovery.</li>
    <li>Lossless RGBA PNG output derivation.</li>
    <li>Destructive asset cleanup options (optional auto-deletion of source DDS files post-extraction).</li>
    <li>Integrity constraints, including strict overwrite protection and dry-run validation logs.</li>
</ul>

<h3>Process Management &amp; Asynchronous Tree-Killing</h3>
<p>To prevent system instability or orphaned background processes, the application actively tracks the process identifier (PID) tree of all spawned subprocesses.</p>
<ul>
    <li><strong>Abrupt Cancellation:</strong> If a batch sequence is aborted by the user, the application invokes explicit low-level system calls (<code>taskkill /F /T</code> on Windows environments; process-group termination via signals on Linux environments).</li>
    <li><strong>Resource Integrity:</strong> Guarantees instant release of system memory and processor handles upon user cancellation.</li>
</ul>

<hr>

<h2>GUI Control Interface Matrix</h2>

<table>
    <thead>
        <tr>
            <th>Parameter Control</th>
            <th>Functional Description</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>Texture Folder</strong></td>
            <td>Targets the root source directory containing source PNG or DDS assets.</td>
        </tr>
        <tr>
            <td><strong>Output Folder</strong></td>
            <td>Defines the target destination directory. Leaving this blank flags an in-place configuration.</td>
        </tr>
        <tr>
            <td><strong>Workers</strong></td>
            <td>Manually sets the upper boundary for parallel subprocess thread allocation.</td>
        </tr>
        <tr>
            <td><strong>Recursive Scan</strong></td>
            <td>Instructs the parser to traverse nested subdirectory structures.</td>
        </tr>
        <tr>
            <td><strong>Mirror Structure</strong></td>
            <td>Replicates the absolute source directory topology inside the target output folder.</td>
        </tr>
        <tr>
            <td><strong>Compression Format</strong></td>
            <td>Selects the target DDS block compression layout (BC1 through BC7).</td>
        </tr>
        <tr>
            <td><strong>Quality</strong></td>
            <td>Calibrates the trade-off calculation between compression speed and block encoding precision.</td>
        </tr>
        <tr>
            <td><strong>Alpha Dithering</strong></td>
            <td>Minimizes quantization banding artifacts across limited-bit alpha channels.</td>
        </tr>
        <tr>
            <td><strong>Dry Run Mode</strong></td>
            <td>Validates structural paths and checks execution arguments without writing data to disk.</td>
        </tr>
        <tr>
            <td><strong>Cancel</strong></td>
            <td>Terminates all active child processes and clears the executor queue instantly.</td>
        </tr>
    </tbody>
</table>

<hr>

<h2>Output Routing Behaviors</h2>
<p>The system dynamically adapts its file system operations depending on the explicit destination settings configured by the user.</p>

<h3>1. Explicit Output Redirection</h3>
<p>When a distinct destination path is targeted, output files are directed away from the source files. When coupled with Recursive Scan and Mirror Structure, the application mirrors the source asset trees flawlessly.</p>

<pre><code>Source Asset Hierarchy:
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
    └── sword.dds</code></pre>

<h3>2. In-Place Asset Compilation</h3>
<p>If the destination path is left blank, target files are compiled directly inside the source directory beside their respective ancestors.</p>

<pre><code>Textures/
└── armor.png

Compiled Result:
Textures/
├── armor.png
└── armor.dds</code></pre>

<p><em>Note: This execution methodology is highly optimized for game modification and production environments that mandate strict structural maintenance of game-ready virtual file systems.</em></p>

<hr>

<h2>Deployment Prerequisites</h2>

<h3>Pre-Compiled Binaries</h3>
<p>The standalone distribution requires no localized Python installation or runtime configuration.</p>
<ul>
    <li><strong>Core Dependency:</strong> The system requires access to <code>nvcompress</code>.</li>
    <li><strong>Pathing Requirements:</strong> The <code>nvcompress</code> executable must either be mapped inside the global system environment <code>PATH</code> variable, or targeted explicitly via the application's configuration parameters.</li>
</ul>

<h3>Supported Environments</h3>
<ul>
    <li><strong>Windows:</strong> Windows 10 / Windows 11 (64-bit Architecture)</li>
    <li><strong>Linux:</strong> Modern Linux Distributions (64-bit GLIBC Core)</li>
</ul>

<hr>

<h2>Operating Procedures</h2>

<h3>PNG &rarr; DDS Production Pipeline</h3>
<ol>
    <li>Input the target path into the <strong>Texture Folder</strong> field.</li>
    <li>Specify an <strong>Output Folder</strong> path, or leave it blank to execute an in-place build.</li>
    <li>Select the required <strong>Compression Profile</strong>, quality parameters, and mipmap filter characteristics.</li>
    <li>Execute the sequence by clicking the <strong>Start</strong> action.</li>
</ol>

<h3>DDS &rarr; PNG Extraction Pipeline</h3>
<ol>
    <li>Input the source directory path into the <strong>Texture Folder</strong> field.</li>
    <li>Establish a target destination folder if data separation is required.</li>
    <li>Configure extraction conditions (e.g., toggle overwrite guards or post-conversion source deletion preferences).</li>
    <li>Execute the extraction array by clicking the <strong>Start</strong> action.</li>
</ol>

<hr>

<h2>Technical Stack Credentials</h2>
<p>Engineered utilizing industry-standard automation frameworks:</p>
<ul>
    <li><strong>Python Backend Engine:</strong> Handles file system I/O operations, structural parsing, and asynchronous threading routines.</li>
    <li><strong>Tkinter User Interface:</strong> Lightweight, native UI wrapper layer ensuring minimal memory footprints.</li>
    <li><strong>Pillow Library Integration:</strong> Facilitates fast, low-level image metadata analysis and alpha channel bitmask profiling.</li>
    <li><strong>NVIDIA Texture Tools Core:</strong> Utilizes the industry-standard <code>nvcompress</code> processing matrix for high-fidelity texture compilation.</li>
</ul>
