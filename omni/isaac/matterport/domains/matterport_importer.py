# Copyright (c) 2024 ETH Zurich (Robotic Systems Lab)
# Author: Pascal Roth
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import carb

# -- Isaac Sim 5.0 namespaces (preferred) --
import isaacsim.core.utils.prims as prim_utils
import isaacsim.core.utils.stage as stage_utils
"""
Use Isaac Lab's SimulationContext singleton to avoid mixing two different
implementations (isaacsim.core.api.simulation_context vs isaaclab.sim).
This ensures the importer sees the same SimulationContext created by the
extension/UI layer.
"""
from isaaclab.sim import SimulationContext

# -- Isaac Lab helpers --
import isaaclab.sim as sim_utils
from isaaclab.terrains import TerrainImporter

# Omniverse / Kit
from isaacsim.core.utils import extensions
extensions.enable_extension("omni.kit.asset_converter")
import omni.kit.asset_converter as converter
import omni.kit.app
import omni

if TYPE_CHECKING:
    # Local typing only to avoid import cycles at import time
    from .importer_cfg import MatterportImporterCfg


class MatterportConverter:
    """Thin wrapper around omni.kit.asset_converter for OBJ->USD."""
    def __init__(self, input_obj: str, context) -> None:
        self._input_obj = input_obj
        self._context = context
        # Use public singleton in 5.0/4.x; avoids extension-internal classes
        self.task_manager = converter.get_instance()

    async def convert_asset_to_usd(self) -> None:
        base_path, _ = os.path.splitext(self._input_obj)
        dst = base_path + ".usd"
        task = self.task_manager.create_converter_task(self._input_obj, dst, None, self._context)
        success = await task.wait_until_finished()
        if not success:
            detailed_status_code = task.get_status()
            detailed_status_error_string = task.get_error_message()
            carb.log_error(
                f"[AssetConverter] Failed to convert {self._input_obj} -> {dst} "
                f"(status={detailed_status_code}): {detailed_status_error_string}"
            )


class MatterportImporter(TerrainImporter):
    """Matterport terrain importer with async handling and 5.0-first APIs."""

    cfg: MatterportImporterCfg

    def __init__(self, cfg: MatterportImporterCfg) -> None:
        self._matterport_cfg = cfg
        self._is_terrain_imported = False

        # Prepare config for TerrainImporter compatibility
        self._prepare_terrain_config(cfg)

        # Converter (kept optional; usd path preferred)
        self.converter = MatterportConverter(cfg.obj_filepath, cfg.asset_converter)

        # Bypass TerrainImporter auto-import by temporarily nulling terrain_type
        original_terrain_type = getattr(cfg, "terrain_type", None)
        cfg.terrain_type = None
        try:
            self._minimal_terrain_importer_init(cfg)
        finally:
            cfg.terrain_type = original_terrain_type

        carb.log_info("[MatterportImporter] Initialized. Call setup_async() to import terrain.")

    def _minimal_terrain_importer_init(self, cfg):
        if not cfg.prim_path:
            raise ValueError("prim_path must be specified in TerrainImporterCfg")
        self.cfg = cfg
        # SimulationContext singleton device
        self.device = SimulationContext.instance().device
        # buffers expected by TerrainImporter
        self.terrain_prim_paths = []
        self.terrain_origins = None
        self.env_origins = None
        self._terrain_flat_patches = dict()

    def _prepare_terrain_config(self, cfg: MatterportImporterCfg):
        if not hasattr(cfg, "env_spacing") or cfg.env_spacing is None:
            if getattr(cfg, "num_envs", 1) > 1:
                cfg.env_spacing = 3.0
            else:
                cfg.env_spacing = 1.0
        if not hasattr(cfg, "num_envs") or cfg.num_envs is None:
            cfg.num_envs = 1

    async def setup_async(self):
        if self._is_terrain_imported:
            return
        await self._import_matterport_terrain_async()
        self.configure_env_origins()
        self.set_debug_vis(getattr(self.cfg, "debug_vis", False))
        await stage_utils.update_stage_async()
        self._is_terrain_imported = True
        carb.log_info("[MatterportImporter] async setup complete.")

    async def _import_matterport_terrain_async(self):
        base_path, ext = os.path.splitext(self._matterport_cfg.obj_filepath)
        usd_path = base_path + ".usd" if ext.lower() == ".obj" else self._matterport_cfg.obj_filepath

        # Convert if needed and permitted
        if not os.path.exists(usd_path) and ext.lower() == ".obj":
            carb.log_info("[MatterportImporter] USD not found; converting OBJ->USD...")
            await self.converter.convert_asset_to_usd()
            carb.log_info("[MatterportImporter] Conversion finished.")

        if not os.path.exists(usd_path):
            raise FileNotFoundError(f"USD file not found: {usd_path}")

        # Cooperatively yield to the event loop without forcing Kit to step
        # other tasks from within this task's context (avoids re-entrancy).
        await asyncio.sleep(0)

        # Import as a Terrain (Isaac Lab TerrainImporter API)
        self.import_usd("Matterport", usd_path)
        await stage_utils.update_stage_async()
        carb.log_info(f"[MatterportImporter] Imported USD: {usd_path}")

        await self._apply_physics_async()

    async def _apply_physics_async(self):
        # Imported prim will live at {prim_path}/Matterport in 5.0 TerrainImporter
        matterport_prim_path = f"{self.cfg.prim_path}/Matterport"
        if matterport_prim_path in self.terrain_prim_paths:
            # Collider
            collider_cfg = sim_utils.CollisionPropertiesCfg(collision_enabled=True)
            sim_utils.define_collision_properties(matterport_prim_path, collider_cfg)

            # Optional ground plane
            if getattr(self._matterport_cfg, "groundplane", False):
                gp_cfg = sim_utils.GroundPlaneCfg()
                ground = gp_cfg.func("/World/GroundPlane", gp_cfg)
                ground.visible = False

        await stage_utils.update_stage_async()

    # Compatibility helpers
    @property
    def is_terrain_imported(self) -> bool:
        return self._is_terrain_imported

    def ensure_terrain_imported(self):
        if not self._is_terrain_imported:
            carb.log_warn("[MatterportImporter] Terrain not imported. Use setup_async() in async context.")

    async def load_world_async(self) -> None:
        await self.setup_async()
        await stage_utils.update_stage_async()

    def load_world(self) -> None:
        self.ensure_terrain_imported()

    async def load_matterport(self) -> None:
        await self.setup_async()

    def load_matterport_sync(self) -> None:
        self.ensure_terrain_imported()

    def cleanup(self):
        # TerrainImporter may define cleanup in certain Lab versions
        super_cleanup = getattr(super(), "cleanup", None)
        if callable(super_cleanup):
            super_cleanup()
        carb.log_info("[MatterportImporter] cleanup complete.")
