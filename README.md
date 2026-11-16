# DimSight

[![Blender 4.2+ | 5.x](https://img.shields.io/badge/Blender-4.2%2B%20%7C%205.x-E87D0D?logo=blender&logoColor=white)](https://www.blender.org/)
[![Version](https://img.shields.io/badge/Version-1.2.2-green.svg)](blender_manifest.toml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

> **Real-time, hover-driven dimensioning and angle inspection for the Blender 3D Viewport.**

DimSight brings CAD-like dimensioning directly into Blender. Hover over mesh edges or vertices to inspect lengths, corner angles, face bends, and selected edge chains in the 3D Viewport.

No measurement objects to create or remove; DimSight settings are stored with their scene in the blend file.

---

## Features

### 📏 Real-Time Hover Dimensioning
- **Edge Lengths**: Hover over a mesh edge in Object or Edit Mode to see its length in scene units, or in raw Blender units when scene-unit formatting is off.
- **Corner Angles**: Hover near a vertex or edge endpoint to measure the angle between two connected edges.
- **Face Bend Angles**: Optionally measure the angle between two face planes across a shared edge. A flat surface is **0°** and perpendicular faces are **90°**; boundary and non-manifold edges have no face-angle value. The adjacent faces are highlighted.
- **Object Names**: Optionally show the hovered object's Outliner name beside the cursor while holding the shortcut. Long names are shortened.
- **Adjacent Edge Lengths**: Independently show both connected edge lengths with Corner Angle.
- **Multi-Edge Corner Intelligence**: Intelligently resolves vertices connected to 3 or more edges (e.g. cube corners, poles). DimSight calculates the approach vector of your cursor in 2D screen space and highlights the exact face/edges facing your pointer.

### 🔗 Connected Mesh Chain Analytics (Edit Mode)
- **Continuous Path Analysis**: Select mesh edges in Edit Mode to see connected-chain lengths, edge counts, and bend angles.
- **Loop Classification**: Distinguishes closed loops from open connected mesh chains and straight polylines; Curve objects are not measured.
- **Corner Discontinuity Splitting**: Automatically differentiates smooth curves from sharp corners (> 45° threshold by default, configurable).

### 👁️ Occlusion-Aware & Camera-Ready
- **Occlusion Controls**: Choose whether hover measurements include geometry behind visible surfaces. Blender-hidden geometry remains excluded; X-Ray and wireframe modes already measure through surfaces.
- **Base Cage vs. Evaluated Modifiers**: The modifier option applies to hover measurements. Edit Mode selection measurements always use the base mesh. If modifier evaluation fails or exceeds the vertex limit, the object is skipped with a warning instead of silently switching geometry.

### 🪟 Viewport-Clamped HUD Badges
- **Collision-aware HUD Labels**: Labels are clamped to the viewport and placed with shared collision avoidance. When the viewport cannot fit every label, lower-priority labels are omitted rather than drawn over one another.
- **Adaptive Contrast & Styling**: Fully customizable text, badges, line weights, and edge/angle colors.

### ⚡ Non-Destructive & Pure GPU Shaders
- **No Added Scene Geometry**: DimSight does not add measurement objects or geometry to the scene. Per-scene settings are stored in the blend file; global defaults are stored in Blender preferences.

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
| **Selection Mode** | In Edit Mode, selected mesh edges can show individual measurements, connected chains, or both. |

> 💡 *The hold shortcut can be rebound from **3D View > Sidebar > DimSight** or **Preferences**. It is installed in Blender's 3D View, Object Mode, and Mesh keymaps; existing user keymaps are not changed, and possible conflicts are reported.*

### 🛠️ Sidebar (N-Panel) Controls

Open the 3D Viewport sidebar by pressing <kbd>N</kbd> and navigate to the **DimSight** tab:

| Setting | Description |
|---|---|
| **Object Name** | Show the hovered object's Outliner name beside the cursor while holding the shortcut. |
| **Edge Length / Corner Angle / Face Angle** | Choose which hover measurements are shown. Face bend angle is flat at 0° and perpendicular at 90° and requires exactly two adjacent faces. |
| **Adjacent Edge Lengths** | With Corner Angle enabled, independently show the two connected edge lengths. This does not depend on the Edge Length toggle. |
| **Objects** | Measure all visible mesh objects or only the active mesh object. |
| **Use Modifiers** | Use evaluated modifier geometry for hover measurements only; Edit Mode selection uses base-mesh geometry. |
| **Measure Through Surfaces** | Include geometry occluded by other surfaces. Blender-hidden geometry remains excluded; X-Ray and wireframe already override occlusion. |
| **Show Measurements in Edit Mode Selection** | Choose when selected mesh measurements are visible. This setting is available outside Edit Mode and applies when editing a mesh. |
| **Display As** | Show selected mesh edges as `Individual Edges`, `Connected Chains`, or `Both`; this does not measure Curve objects. |
| **Chain Split Angle** | A direction change greater than this angle starts a new connected chain. |
| **Use Scene Units** | Format lengths with the scene unit system; when off, values use raw Blender units without conversion. |
| **Corner Detection Zone** | Screen-space percentage of an edge near each endpoint reserved for Corner Angle detection (5–25%). |
| **Decimals** | Display precision from 0 to 8 decimal places. |
| **Advanced limits** | Configure hover radius, label limit, and mesh vertex limit. Label-limit suppression applies to the whole affected category. |
| **Defaults** | Save scene settings to Blender preferences, apply saved preferences to the current scene, or reset only the current scene. Reset leaves Always On and the shortcut unchanged. |

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
│   ├── DimSightTest.blend     # Multi-case test scene for angles, chains, and occlusion
│   ├── test_geometry.py       # Pure NumPy geometry regression tests
│   └── test_blender_runtime.py # Blender registration, UI-layout, and mesh-data tests
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
