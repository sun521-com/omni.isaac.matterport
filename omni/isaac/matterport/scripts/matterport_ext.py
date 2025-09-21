# Copyright (c) 2024 ETH Zurich
# SPDX-License-Identifier: BSD-3-Clause

import asyncio
import os
from typing import Optional

import carb
import omni
import omni.ext
import omni.usd

# Isaac Sim 5.0 namespaces
import isaacsim.core.utils.prims as prim_utils
import isaacsim.core.utils.stage as stage_utils
from isaaclab.sim import SimulationCfg, SimulationContext
import isaaclab.sim as sim_utils

# UI helpers (5.0 GUI component library)
import omni.ui as ui
from omni.kit.async_engine import run_coroutine
from isaacsim.gui.components.ui_utils import (
    btn_builder,
    get_style,
    setup_ui_headers,
    str_builder,
)
import omni.kit.notification_manager as nm

# Local importer/config
from ..config.importer_cfg import MatterportImporterCfg
from ..domains.matterport_importer import MatterportImporter

EXTENSION_NAME = "Matterport Importer"
MATTERPORT_CHILD_PRIM_NAME = "Matterport"


def _get_stage():
    ctx = omni.usd.get_context()
    stage = ctx.get_stage()
    if stage is None:
        raise RuntimeError("No active USD stage")
    return stage


def _ensure_container_prim(stage, prim_path: str):
    from pxr import Sdf

    if not stage.GetPrimAtPath(prim_path):
        stage.DefinePrim(Sdf.Path(prim_path), "Xform")
    child_path = f"{prim_path}/{MATTERPORT_CHILD_PRIM_NAME}"
    if not stage.GetPrimAtPath(child_path):
        stage.DefinePrim(Sdf.Path(child_path), "Xform")
    return child_path


def import_matterport_usd_reference(prim_path: str, usd_path: str) -> str:
    """Import a USD file by referencing it under the given prim path."""

    from pxr import Sdf

    stage = _get_stage()
    child_path = _ensure_container_prim(stage, prim_path)
    prim = stage.GetPrimAtPath(child_path)
    prim.GetReferences().ClearReferences()
    prim.GetReferences().AddReference(usd_path)
    return child_path


def apply_matterport_collision(prim_path: str) -> str:
    """Apply a basic collider to the imported Matterport prim.

    Returns the path to the Matterport prim.
    """

    stage = _get_stage()
    child_path = f"{prim_path}/{MATTERPORT_CHILD_PRIM_NAME}"
    if not stage.GetPrimAtPath(child_path):
        raise RuntimeError(f"Matterport prim not found at '{child_path}'. Import USD first.")

    collider_cfg = sim_utils.CollisionPropertiesCfg(collision_enabled=True)
    sim_utils.define_collision_properties(child_path, collider_cfg)
    return child_path


def ensure_hidden_ground_plane(path: str = "/World/GroundPlane") -> None:
    """Create or update a hidden ground plane that provides collision."""

    from pxr import UsdGeom, Sdf, Gf, Usd

    stage = _get_stage()
    plane_path = f"{path}/Plane"

    if not stage.GetPrimAtPath(Sdf.Path(path)):
        UsdGeom.Xform.Define(stage, Sdf.Path(path))

    created = False
    if not stage.GetPrimAtPath(Sdf.Path(plane_path)):
        cube = UsdGeom.Cube.Define(stage, Sdf.Path(plane_path))
        xform = UsdGeom.XformCommonAPI(cube.GetPrim())
        try:
            xform.SetScale(Gf.Vec3f(1000.0, 1000.0, 0.1), Usd.TimeCode.Default())
        except Exception as exc:
            carb.log_warn(f"[{EXTENSION_NAME}] Ground plane SetScale note: {exc}")
        try:
            xform.SetTranslate(Gf.Vec3d(0.0, 0.0, -0.05), Usd.TimeCode.Default())
        except Exception as exc:
            carb.log_warn(f"[{EXTENSION_NAME}] Ground plane SetTranslate note: {exc}")
        created = True
    else:
        cube = UsdGeom.Cube(stage.GetPrimAtPath(Sdf.Path(plane_path)))

    try:
        UsdGeom.Imageable(cube.GetPrim()).MakeInvisible()
    except Exception:
        pass

    try:
        collider_cfg = sim_utils.CollisionPropertiesCfg(collision_enabled=True)
        sim_utils.define_collision_properties(plane_path, collider_cfg)
    except Exception as exc:
        carb.log_warn(f"[{EXTENSION_NAME}] Ground plane collision note: {exc}")

    status = "created" if created else "ready"
    carb.log_info(f"[{EXTENSION_NAME}] Ground plane {status} at {plane_path}")


async def import_matterport_asset_async(
    prim_path: str,
    input_path: str,
    *,
    groundplane: bool = False,
    manage_simulation: bool = True,
    resolve_relative_to: Optional[str] = None,
) -> str:
    """Programmatic entry-point to import a Matterport USD/OBJ into the stage.

    Returns the prim path of the imported Matterport root.
    """

    if not input_path:
        raise ValueError("input_path must be provided")

    resolved_path = input_path
    if not os.path.isabs(resolved_path) and resolve_relative_to:
        candidate = os.path.join(resolve_relative_to, resolved_path)
        if os.path.isfile(candidate):
            resolved_path = candidate

    sim = None
    if manage_simulation:
        if SimulationContext.instance():
            SimulationContext.clear_instance()
        sim = SimulationContext(SimulationCfg())
        await sim.initialize_simulation_context_async()

    if resolved_path.lower().endswith(".usd"):
        import_matterport_usd_reference(prim_path, resolved_path)
        if groundplane:
            ensure_hidden_ground_plane()
    else:
        cfg = MatterportImporterCfg(prim_path=prim_path, obj_filepath=resolved_path, groundplane=groundplane)
        importer = MatterportImporter(cfg)
        await importer.load_world_async()

    try:
        apply_matterport_collision(prim_path)
    except Exception as exc:
        carb.log_warn(f"[{EXTENSION_NAME}] Matterport collision application note: {exc}")

    if sim:
        await sim.reset_async()
        await sim.pause_async()

    return f"{prim_path}/{MATTERPORT_CHILD_PRIM_NAME}"


def import_matterport_asset(
    prim_path: str,
    input_path: str,
    *,
    groundplane: bool = False,
    manage_simulation: bool = True,
    resolve_relative_to: Optional[str] = None,
):
    """Schedule the asynchronous Matterport import helper via Kit's async engine."""

    return run_coroutine(
        import_matterport_asset_async(
            prim_path,
            input_path,
            groundplane=groundplane,
            manage_simulation=manage_simulation,
            resolve_relative_to=resolve_relative_to,
        )
    )


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
            # Yield cooperatively; avoid calling Kit frame stepper here
            await asyncio.sleep(0)
            target = ui.Workspace.get_window("Viewport")
            if target:
                w = ui.Workspace.get_window(EXTENSION_NAME)
                if w:
                    w.dock_in(target, ui.DockPosition.LEFT, 0.33)
        run_coroutine(_dock())

        # Import task state (driven by update callback, not awaits)
        self._import_running = False
        self._import_state = None
        self._import_future = None
        self._sim = None
        self._importer = None

        # Per-frame driver to avoid re-entrancy: we never await inside this
        def _on_update(e):
            if not self._import_running:
                return
            try:
                if self._import_state == "init_sim":
                    carb.log_info(f"[{EXTENSION_NAME}] init_sim")
                    if SimulationContext.instance():
                        SimulationContext.clear_instance()
                    self._sim = SimulationContext(SimulationCfg())
                    self._import_future = run_coroutine(self._sim.initialize_simulation_context_async())
                    self._import_state = "wait_init"
                elif self._import_state == "wait_init":
                    if self._import_future and self._import_future.done():
                        exc = self._import_future.exception()
                        if exc:
                            raise exc
                        self._import_future = None
                        carb.log_info(f"[{EXTENSION_NAME}] sim initialized")
                        self._import_state = "create_importer"
                elif self._import_state == "create_importer":
                    carb.log_info(f"[{EXTENSION_NAME}] create_importer")
                    cfg = MatterportImporterCfg(
                        prim_path=self._prim_path, obj_filepath=self._input_file, groundplane=False
                    )
                    self._importer = MatterportImporter(cfg)
                    self._import_future = run_coroutine(self._importer.load_world_async())
                    self._import_state = "wait_import"
                elif self._import_state == "wait_import":
                    if self._import_future and self._import_future.done():
                        exc = self._import_future.exception()
                        if exc:
                            raise exc
                        self._import_future = None
                        carb.log_info(f"[{EXTENSION_NAME}] world loaded")
                        self._import_state = "reset"
                elif self._import_state == "reset":
                    carb.log_info(f"[{EXTENSION_NAME}] reset")
                    self._import_future = run_coroutine(self._sim.reset_async())
                    self._import_state = "wait_reset"
                elif self._import_state == "wait_reset":
                    if self._import_future and self._import_future.done():
                        exc = self._import_future.exception()
                        if exc:
                            raise exc
                        self._import_future = None
                        carb.log_info(f"[{EXTENSION_NAME}] pause")
                        self._import_state = "pause"
                elif self._import_state == "pause":
                    self._import_future = run_coroutine(self._sim.pause_async())
                    self._import_state = "wait_pause"
                elif self._import_state == "wait_pause":
                    if self._import_future and self._import_future.done():
                        exc = self._import_future.exception()
                        if exc:
                            raise exc
                        self._import_future = None
                        carb.log_info(
                            f"[{EXTENSION_NAME}] Imported scene at {self._prim_path} from {self._input_file}"
                        )
                        self._import_state = "done"
                elif self._import_state == "done":
                    # cleanup and re-enable UI
                    self._import_running = False
                    if hasattr(self, "_import_btn"):
                        self._import_btn.enabled = True
            except Exception as exc:
                carb.log_error(f"[{EXTENSION_NAME}] Import failed: {exc}")
                self._import_running = False
                if hasattr(self, "_import_btn"):
                    self._import_btn.enabled = True

        self._update_sub = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_push(_on_update)

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

                # Apply Physics button (synchronous, safe)
                self._physics_btn = btn_builder(
                    "Apply Physics", text="Apply Physics", on_clicked_fn=self._apply_physics_sync
                )
                self._physics_btn.enabled = True

                # Add Ground Plane button (synchronous, hidden by default)
                self._ground_btn = btn_builder(
                    "Add Ground Plane", text="Add Ground Plane", on_clicked_fn=self._add_ground_plane_sync
                )
                self._ground_btn.enabled = True

                # Status label
                self._status_label = ui.Label("Ready", name="matterport_status", height=0)
                
    def _set_status(self, text: str):
        try:
            if hasattr(self, "_status_label") and self._status_label:
                self._status_label.text = text
            try:
                nm.post_notification(text, duration=3)
            except Exception:
                pass
        except Exception:
            pass

    # ---------------- Import logic ----------------

    def _start_import(self):
        if not self._input_file:
            carb.log_warn("No input file selected.")
            print(f"[{EXTENSION_NAME}] No input file selected.")
            self._set_status("No input file selected")
            return

        # If the user selected a relative extension path, try to resolve against extension dir
        if not os.path.isabs(self._input_file):
            ext_path = omni.kit.app.get_app().get_extension_manager().get_extension_path(self._ext_id)
            candidate = os.path.join(ext_path, "data", self._input_file)
            if os.path.isfile(candidate):
                self._input_file = candidate

        # USD-only fast path (no asyncio, safest to avoid re-entrancy)
        if self._input_file.lower().endswith(".usd"):
            try:
                self._simple_import_usd(self._input_file)
                carb.log_info(f"[{EXTENSION_NAME}] Simple USD import done: {self._input_file}")
                print(f"[{EXTENSION_NAME}] Simple USD import done: {self._input_file}")
                self._set_status("USD imported successfully")
            except Exception as exc:
                carb.log_error(f"[{EXTENSION_NAME}] Simple USD import failed: {exc}")
                print(f"[{EXTENSION_NAME}] Simple USD import failed: {exc}")
                self._set_status(f"Import failed: {exc}")
            return

        # prevent overlapping imports for advanced path
        if self._import_running:
            carb.log_warn("Import already running; ignoring request.")
            return
        self._import_running = True
        self._import_state = "init_sim"
        self._import_future = None
        if hasattr(self, "_import_btn"):
            self._import_btn.enabled = False

    async def _load_matterport_async(self):
        # Legacy path retained for API stability; now unused.
        carb.log_warn(
            f"[{EXTENSION_NAME}] _load_matterport_async is deprecated; using frame-driven import instead."
        )

    # ---------------- Simple USD import (no asyncio) ----------------
    def _simple_import_usd(self, usd_path: str) -> None:
        """Import a USD by adding a reference under prim_path/Matterport.

        This path avoids any async calls to completely sidestep Kit's
        task stepper re-entrancy.
        """
        import_matterport_usd_reference(self._prim_path, usd_path)
        self._set_status("Reference added to stage")

    # ---------------- Physics application (no asyncio) ----------------
    def _apply_physics_sync(self) -> None:
        """Apply basic collision properties to the imported Matterport prim.

        This runs synchronously to avoid async re-entrancy. It requires that
        the USD has already been imported under self._prim_path/Matterport.
        """
        try:
            matterport_prim_path = apply_matterport_collision(self._prim_path)
            carb.log_info(f"[{EXTENSION_NAME}] Applied collision to {matterport_prim_path}")
            print(f"[{EXTENSION_NAME}] Applied collision to {matterport_prim_path}")
            self._set_status("Collision applied")
        except Exception as exc:
            carb.log_error(f"[{EXTENSION_NAME}] Apply Physics failed: {exc}")
            print(f"[{EXTENSION_NAME}] Apply Physics failed: {exc}")
            self._set_status(f"Apply Physics failed: {exc}")

    def _add_ground_plane_sync(self) -> None:
        """Create a hidden ground plane at /World/GroundPlane synchronously.

        To avoid dependencies on SimulationContext and async helpers, we
        define a large thin cube as the plane, make it invisible, and enable
        collision on it. This works in a single frame and avoids re-entrancy.
        """
        try:
            ensure_hidden_ground_plane()
            msg = "Ground plane ready at /World/GroundPlane/Plane (hidden/collidable)"
            carb.log_info(f"[{EXTENSION_NAME}] {msg}")
            print(f"[{EXTENSION_NAME}] {msg}")
            self._set_status("Ground plane added (hidden)")
        except Exception as exc:
            carb.log_error(f"[{EXTENSION_NAME}] Add Ground Plane failed: {exc}")
            print(f"[{EXTENSION_NAME}] Add Ground Plane failed: {exc}")
            self._set_status(f"Add Ground Plane failed: {exc}")
