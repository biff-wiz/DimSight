# DimSight

[![Blender 4.2+ | 5.x](https://img.shields.io/badge/Blender-4.2%2B%20%7C%205.x-E87D0D?logo=blender&logoColor=white)](https://www.blender.org/)
[![Version](https://img.shields.io/badge/Version-1.2.2-green.svg)](blender_manifest.toml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

> **Real-time, zero-overhead HUD dimensioning and angle inspection for the Blender 3D Viewport.**

DimSight brings effortless CAD-like dimensioning directly into Blender. Simply hover over edges or vertices to immediately inspect exact lengths, vertex angles, and connected edge paths with clean, non-intrusive GPU-rendered HUD badges.

No ruler objects to delete. No scene clutter. No undo stack pollution.

---

## Features

### 📏 Real-Time Hover Dimensioning
- **Instant Edge Lengths**: Hover over any edge in Object or Edit Mode to see its live length formatted in your scene's chosen measurement units.
- **Corner Apex Angles**: Hover near vertices to reveal the internal or external angle formed by adjacent edges, accompanied by a clean visual arc.
- **Combined Angle & Edge Lengths**: When inspecting a corner, view the apex angle and both adjacent edge lengths simultaneously with intelligent anti-overlap positioning.
- **Multi-Edge Corner Intelligence**: Intelligently resolves vertices connected to 3 or more edges (e.g. cube corners, poles). DimSight calculates the approach vector of your cursor in 2D screen space and highlights the exact face/edges facing your pointer.

### 🔗 Curve, Loop & Chain Analytics (Edit Mode)
- **Continuous Path Analysis**: Select any sequence of connected edges in Edit Mode to see total arc length, edge count, and deflection angles.
- **Loop vs. Curve Detection**: Distinguishes closed loops from open curves and straight polylines.
- **Corner Discontinuity Splitting**: Automatically differentiates smooth curves from sharp corners (> 45° threshold by default, configurable).

### 👁️ Occlusion-Aware & Camera-Ready
- **Smart Line-of-Sight Raycasting**: Deep ray-casting ensures hidden back-facing edges and occluded interior geometry are never falsely detected.
- **Full Viewport Support**: Operates seamlessly in Perspective, Orthographic, Camera View (`Numpad 0`), and Wireframe/X-Ray modes.
- **Base Cage vs. Evaluated Modifiers**: Toggle whether measurements reflect base un-modified polygon geometry or geometry after modifier evaluation (Subdivision Surface, Booleans, Solidify, Wireframe, etc.).

### 🪟 Viewport-Clamped HUD Badges
- **Zero Viewport Drift**: When an edge or corner recedes outside your current camera view, labels smoothly clamp to the viewport margins rather than vanishing off-screen.
- **Adaptive Contrast & Styling**: Fully customizable text, badges, line weights, and edge/angle colors.

### ⚡ Non-Destructive & Pure GPU Shaders
- **Zero Scene Footprint**: DimSight draws exclusively using Blender's modern GPU overlay pipelines (`POST_VIEW` and `POST_PIXEL`).
- **Clean Blend Files**: Absolutely nothing is written into your blend file, vertex groups, or scene graph, keeping your project files clean and your undo history pristine.

---

## Installation

### Method 1: Blender 4.2+ Extension (Recommended)
1. Download `DimSight.zip` from the latest [GitHub Release](https://github.com/biff-wiz/DimSight/releases).
2. Open Blender and go to **Edit > Preferences > Get Extensions**.
3. Click the top-right menu icon (downward chevron) and select **Install from Disk...**.
4. Choose the downloaded `DimSight.zip` file.
5. Enable **DimSight** and enjoy!

### Method 2: Manual Installation
1. Clone or download this repository.
2. Copy the repository contents into your Blender extensions folder:
   - **Windows**: `%APPDATA%\Blender Foundation\Blender\<version>\extensions\user_default\dimsight\`
   - **macOS**: `~/Library/Application Support/Blender/<version>/extensions/user_default/dimsight/`
   - **Linux**: `~/.config/blender/<version>/extensions/user_default/dimsight/`
3. Restart Blender and enable DimSight under **Edit > Preferences > Add-ons**.

---

## How to Use

### ⌨️ Default Shortcuts & Modes

| Control | Action |
|---|---|
| **Hold `D`** *(Default)* | Hold to inspect dimensions under the mouse cursor. Release to hide. |
| **Always On** | Toggle in the N-panel to keep DimSight active continuously without holding a key. |
| **Selection Mode** | In Edit Mode, selected edges automatically display length or curve chains. |

> 💡 *The hold key can be rebound to any keyboard key (e.g. `Shift`, `Alt`, `Space`, function keys) from **3D View > Sidebar > DimSight** or **Preferences**.*

### 🛠️ Sidebar (N-Panel) Controls

Open the 3D Viewport sidebar by pressing <kbd>N</kbd> and navigate to the **DimSight** tab:

| Setting | Description |
|---|---|
| **Measure Scope** | Measure all visible objects or restrict strictly to the active object. |
| **Edge Length** | Toggle edge length dimension pills. |
| **Vertex Angle** | Toggle corner angle dimension pills and arcs. |
| **Angle Edge Lengths** | Show adjacent edge lengths simultaneously when hovering near a corner. |
| **Show Angle Arc** | Display the curved visual arc and wedge highlight inside corners. |
| **Angle End Zone** | Distance from vertex (0–50%) where edge hover transitions into corner angle hover. |
| **Include Occluded** | Enable to measure through solid surfaces (useful for x-ray/transparent workflows). |
| **Use Modifiers** | Toggle between measuring original mesh geometry vs post-modifier geometry. |
| **Selection Display** | Display selected geometry as `Individual` edges, continuous `Chains`, or `Both`. |
| **Max Curve Angle** | Deflection threshold beyond which connected edges count as sharp corners. |
| **Units & Decimals** | Choose metric, imperial, or raw unit formatting and configure precision (1–4 decimals). |
| **Save as Default** | Store your current settings as the global default for all future Blender sessions. |

---

## Project Structure

```text
DimSight/
├── .github/
│   └── workflows/
│       └── release.yml        # Automated GitHub Actions packaging and release workflow
├── assets/
│   └── branding/              # Source logo (.af) and branding project (.blend)
├── tests/
│   └── DimSightTest.blend     # Multi-case test scene for angles, curves, and occlusion
├── __init__.py                # Add-on entrypoint, lifecycle, and bl_info registration
├── blender_manifest.toml      # Blender 4.2+ extension manifest specification
├── geometry.py                # Pure NumPy projection, spatial search, and angle math
├── meshdata.py                # BMesh extraction, vertex arrays, and topology caching
├── operators.py               # Modal hover session, keymap bindings, and hold operator
├── overlay.py                 # GPU 2D/3D shaders, line/fan draw routines, and HUD badges
├── props.py                   # Scene properties, addon preferences, and setting syncing
├── ui.py                      # Viewport Sidebar (N-panel) interface
├── package.py                 # Self-contained build script for distribution zips
├── LICENSE                    # GNU General Public License v3.0
└── README.md                  # Documentation and user manual
```

---

## Building from Source

To package the extension into a clean, ready-to-distribute ZIP file, run:

```bash
python package.py
```

This creates `dist/dimsight-1.2.2.zip` and `dist/DimSight.zip` containing only the necessary runtime files.

---

## Contributing

Contributions, bug reports, and feature suggestions are welcome!
1. Fork the repository.
2. Create your feature branch (`git checkout -b feature/my-feature`).
3. Commit your changes (`git commit -m "Add my feature"`).
4. Push to the branch (`git push origin feature/my-feature`).
5. Open a Pull Request.

---

## License

DimSight is free and open-source software licensed under the **GNU General Public License v3.0 or later** ([GPL-3.0-or-later](LICENSE)).
