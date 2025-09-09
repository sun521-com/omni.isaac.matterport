# Copyright (c) 2024 ETH Zurich (Robotic Systems Lab)
# Author: Pascal Roth
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

from dataclasses import MISSING

from isaacsim.core.utils import extensions
# Local import: avoid broken legacy path and circulars
from .matterport_importer import MatterportImporter
from isaaclab.terrains import TerrainImporterCfg
from isaaclab.utils import configclass
from typing_extensions import Literal

# Ensure asset converter is available (5.0 and 4.x)
extensions.enable_extension("omni.kit.asset_converter")
from omni.kit.asset_converter.impl import AssetConverterContext

# NOTE: hope to be changed to dataclass later; we configure a default context now.
asset_converter_cfg: AssetConverterContext = AssetConverterContext()
asset_converter_cfg.ignore_materials = False
asset_converter_cfg.ignore_animations = False
asset_converter_cfg.ignore_camera = False
asset_converter_cfg.ignore_light = False
asset_converter_cfg.single_mesh = False
asset_converter_cfg.smooth_normals = True
asset_converter_cfg.export_preview_surface = False
asset_converter_cfg.use_meter_as_world_unit = True
asset_converter_cfg.create_world_as_default_root_prim = True
asset_converter_cfg.embed_textures = True
asset_converter_cfg.convert_fbx_to_y_up = False
asset_converter_cfg.convert_fbx_to_z_up = True
asset_converter_cfg.keep_all_materials = False
asset_converter_cfg.merge_all_meshes = False
asset_converter_cfg.use_double_precision_to_usd_transform_op = False
asset_converter_cfg.ignore_pivots = False
asset_converter_cfg.disabling_instancing = False
asset_converter_cfg.export_hidden_props = False
asset_converter_cfg.baking_scales = False


@configclass
class MatterportImporterCfg(TerrainImporterCfg):
    class_type: type = MatterportImporter
    """Importer class that will be constructed by Isaac Lab."""

    terrain_type: Literal["generator", "plane", "usd", "matterport"] = "matterport"
    """The type of terrain to generate/import. Defaults to "matterport"."""

    prim_path: str = "/World/terrain"

    env_spacing: float = 3.0

    # Accept .usd directly; if .obj is provided we attempt conversion.
    obj_filepath: str = ""

    asset_converter: AssetConverterContext = asset_converter_cfg

    # Add a switch to spawn a hidden ground plane for stability (optional)
    groundplane: bool = True
