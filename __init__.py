"""DimSight: hover to inspect mesh dimensions, corner angles, and face bends."""

bl_info = {
    "name": "DimSight",
    "author": "biff-wiz",
    "version": (1, 2, 2),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > DimSight",
    "description": "Hover to inspect mesh lengths, corner angles, and face bends in the 3D viewport.",
    "category": "3D View",
}

if "bpy" in locals():   # "Reload Scripts": pick up edits in the sub-modules
    import importlib
    for _name in ("geometry", "meshdata", "overlay", "props", "operators", "ui"):
        importlib.reload(globals()[_name])

import bpy  # noqa: E402,F401
from . import geometry, meshdata, overlay, props, operators, ui  # noqa: E402,F401


def register():
    props.register()
    overlay.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    overlay.unregister()
    props.unregister()
