# Copyright (c) 2024 ETH Zurich
# SPDX-License-Identifier: BSD-3-Clause

import asyncio
import os

import carb
import omni
import omni.ext
import omni.usd

# Isaac Sim 5.0 namespaces
import isaacsim.core.utils.prims as prim_utils
import isaacsim.core.utils.stage as stage_utils
from isaaclab.sim import SimulationCfg, SimulationContext

# UI helpers (5.0 GUI component library)
import omni.ui as ui
from isaacsim.gui.components.ui_utils import (
    btn_builder,
    get_style,
    setup_ui_headers,
    str_builder,
)

# Local importer/config
from .importer_cfg import MatterportImporterCfg
from .matterport_importer import MatterportImporter

EXTENSION_NAME = "Matterport Importer"


def _is_mesh_file(path: str) -> bool:
    _, ext = os.path.splitext(path.lower())
    return ext in [".obj", ".usd"]


def _on_filter_mesh_item(item) -> bool:
    if not item or item.is_folder:
        return not (item.name == "Omniverse" or item.path.startswith("omniverse:"))
    return _is_mesh_file(item.path)


class MatterPortExtension(omni.ext.IExt):
    """Minimal extension to import a Matterport USD/OBJ into the stage."""

    def on_startup(self, ext_id):
        self._ext_id = ext_id
        self._usd_context = omni.usd.get_context()
        self._window = omni.ui.Window(
            EXTENSION_NAME, width=380, height=280, visible=True, dockPreference=ui.DockPreference.LEFT_BOTTOM
        )

        # UI state
        self._prim_path = "/World/terrain"
        self._input_file = ""

        # Build UI
        self._build_ui()

        # Dock next to viewport (best-effort)
        async def _dock():
            await omni.kit.app.get_app().next_update_async()
            target = ui.Workspace.get_window("Viewport")
            if target:
                w = ui.Workspace.get_window(EXTENSION_NAME)
                if w:
                    w.dock_in(target, ui.DockPosition.LEFT, 0.33)
        asyncio.ensure_future(_dock())

    def on_shutdown(self):
        if self._window:
            self._window = None
        # Avoid clearing the whole stage here to not surprise users

    # ---------------- UI ----------------

    def _build_ui(self):
        with self._window.frame:
            with ui.VStack(spacing=5, height=0):
                self._build_info_ui()
                self._build_import_ui()

    def _build_info_ui(self):
        title = EXTENSION_NAME
        doc_link = "https://developer.nvidia.com/isaac-sim"
        overview = (
            "Import a Matterport USD directly, or select an OBJ and let Asset Converter create USD first."
        )
        setup_ui_headers(self._ext_id, __file__, title, doc_link, overview)

    def _build_import_ui(self):
        frame = ui.CollapsableFrame(
            title="Import",
            height=0,
            collapsed=False,
            style=get_style(),
            style_type_name_override="CollapsableFrame",
            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
        )
        with frame:
            with ui.VStack(style=get_style(), spacing=6, height=0):
                # prim path input
                prim_model = str_builder(
                    "Environment Prim Path",
                    tooltip="Prim path under which the terrain will be imported",
                    default_val=self._prim_path,
                )
                prim_model.add_value_changed_fn(lambda m: setattr(self, "_prim_path", m.get_value_as_string()))

                # file path picker
                def _on_file_change(model=None):
                    val = model.get_value_as_string()
                    if _is_mesh_file(val):
                        self._input_file = val
                        self._import_btn.enabled = True
                    else:
                        self._import_btn.enabled = False
                        carb.log_warn(f"Invalid mesh path: {val}")

                self._file_model = str_builder(
                    "Input File",
                    default_val=self._input_file,
                    tooltip="Pick a .usd or .obj",
                    use_folder_picker=True,
                    item_filter_fn=_on_filter_mesh_item,
                    folder_dialog_title="Select .usd or .obj",
                    folder_button_title="Select",
                )
                self._file_model.add_value_changed_fn(_on_file_change)

                self._import_btn = btn_builder("Import", text="Import", on_clicked_fn=self._start_import)
                self._import_btn.enabled = False

    # ---------------- Import logic ----------------

    def _start_import(self):
        if not self._input_file:
            carb.log_warn("No input file selected.")
            return

        # If the user selected a relative extension path, try to resolve against extension dir
        if not os.path.isabs(self._input_file):
            ext_path = omni.kit.app.get_app().get_extension_manager().get_extension_path(self._ext_id)
            candidate = os.path.join(ext_path, "data", self._input_file)
            if os.path.isfile(candidate):
                self._input_file = candidate

        asyncio.ensure_future(self._load_matterport_async())

    async def _load_matterport_async(self):
        # (Re)create SimulationContext if needed
        if SimulationContext.instance():
            SimulationContext.clear_instance()

        sim = SimulationContext(SimulationCfg())
        await sim.initialize_simulation_context_async()

        cfg = MatterportImporterCfg(prim_path=self._prim_path, obj_filepath=self._input_file, groundplane=False)
        importer = MatterportImporter(cfg)
        await importer.load_world_async()

        await sim.reset_async()
        await sim.pause_async()

        carb.log_info(f"[{EXTENSION_NAME}] Imported scene at {self._prim_path} from {self._input_file}")
