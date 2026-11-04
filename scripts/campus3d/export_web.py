# -*- coding: utf-8 -*-
"""The web form of the campus miniature (docs/CAMPUS_MAP.md), run after build_model.py in the same
Blender session:

    blender -b --factory-startup -P scripts/campus3d/build_model.py -P scripts/campus3d/export_web.py -- \\
        inputs/campus3d/campus.json clay .local/campus/unused.png 256 --web data/campus

Writes into the --web folder:
  campus.glb        ground (one mesh, a material per surface), island sides, buildings (one mesh;
                    vertex attributes _bid = 1 + the building's row in buildings.json, 0 without a code,
                    and _style = 0 plain, 1 glass, 2 brick, 3 metal from buildings-extra.json `styles`),
                    landmarks (the gate, the carillon, fountains; a material per colour),
                    rooftop plant, three tree shapes and the hero camera; Draco-compressed
  ground-light.webp the light on the ground, baked top-down (sun shadows of buildings and trees, sky
                    occlusion): the browser multiplies the ground colours by it and needs no shadows
  poster.webp       the same view rendered in full (Cycles, 1200 x 750, transparent around the island),
                    shown first and whenever 3D is not available
  model.json        palette, sun, camera, tree instances (x, z, scale, turn, shape) and the ground's
                    lightmap frame, in the browser's axes (x east, y up, z south)
"""
import json
import math
import os
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = Path(argv[argv.index("--web") + 1]).resolve()
SRC = Path(argv[0]).resolve()
ROOT = SRC.parents[2]
TABLE = json.loads((ROOT / "data" / "campus" / "buildings.json").read_text(encoding="utf-8"))
BID = {row["code"]: i + 1 for i, row in enumerate(TABLE["buildings"])}
LIGHT_SIZE = 2048
POSTER = (1200, 750)
OUT.mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
ns = bpy.app.driver_namespace["campus"]          # left by build_model.py: palette, trees, sun, camera


def to_web(x, y, z):
    """Blender (x east, y north, z up) to the browser's (x east, y up, z south)."""
    return [round(x, 2), round(z, 2), round(-y, 2)]


# --- 1. the poster: the full scene from the hero camera ------------------------------------------------
cam = scene.camera
cam.data.dof.use_dof = False
scene.render.resolution_x, scene.render.resolution_y = POSTER
scene.render.image_settings.file_format = "WEBP"
scene.render.image_settings.color_mode = "RGBA"
scene.render.image_settings.quality = 78
scene.render.filepath = str(OUT / "poster.webp")
bpy.ops.render.render(write_still=True)

# --- 2. meshes ---------------------------------------------------------------------------------------
bpy.ops.object.select_all(action="DESELECT")
for ob in list(scene.objects):
    if ob.type == "CURVE":
        ob.select_set(True)
bpy.context.view_layer.objects.active = next(o for o in scene.objects if o.select_get())
bpy.ops.object.convert(target="MESH")
bpy.ops.object.select_all(action="DESELECT")
for ob in scene.objects:
    if ob.type == "MESH" and ob.modifiers:
        bpy.context.view_layer.objects.active = ob
        for m in list(ob.modifiers):
            bpy.ops.object.modifier_apply(modifier=m.name)


def is_building(name):
    return len(name) > 1 and name[0] == "b" and name[1].isdigit()


def join(names, into):
    obs = [o for o in scene.objects if o.type == "MESH"
           and (is_building(o.name) if names == ["b"] else any(o.name.startswith(n) for n in names))]
    bpy.ops.object.select_all(action="DESELECT")
    for o in obs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = obs[0]
    bpy.ops.object.join()
    ob = bpy.context.active_object
    ob.name = into
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return ob


# Buildings carry their row in the table, so the browser can colour today's.
for ob in scene.objects:
    if ob.type == "MESH" and is_building(ob.name):
        code = ob.name.split("_", 1)[1]
        attr = ob.data.attributes.new("_bid", "FLOAT", "POINT")
        attr.data.foreach_set("value", [float(BID.get(code, 0))] * len(ob.data.vertices))
buildings = join(["b"], "buildings")
units = join(["Cube"], "units")
landmarks = join(["lm_"], "landmarks")
ground = join(["base", "parking", "track", "pitch", "grass", "wood", "water", "roads", "paths"], "ground")

# The island's sides leave the ground mesh: they take no top-down light.
side_mat = bpy.data.materials.new("island_side")
ground.data.materials.append(side_mat)
side_index = len(ground.data.materials) - 1
bm = bmesh.new(); bm.from_mesh(ground.data)
for f in bm.faces:
    f.select = f.normal.z < 0.5 and ground.data.materials[f.material_index].name == "base"
    if f.select:
        f.material_index = side_index
bm.to_mesh(ground.data); bm.free()
bpy.context.view_layer.objects.active = ground
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="DESELECT")
bpy.ops.object.mode_set(mode="OBJECT")
for p in ground.data.polygons:
    p.select = p.material_index == side_index
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.separate(type="SELECTED")
bpy.ops.object.mode_set(mode="OBJECT")
sides = next(o for o in scene.objects if o.name.startswith("ground") and o is not ground)
sides.name = "island_sides"
ground.data.materials.pop(index=side_index)
# Faces that look down or sideways (slab bottoms, the island's underside) are never seen from above.
bm = bmesh.new(); bm.from_mesh(ground.data)
bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z < 0.5], context="FACES")
bm.to_mesh(ground.data); bm.free()

# Top-down UV over the island's square: the lightmap's frame.
xs = [v.co.x for v in ground.data.vertices]; ys = [v.co.y for v in ground.data.vertices]
x0, y0 = min(xs), min(ys)
span = max(max(xs) - x0, max(ys) - y0)
uv = ground.data.uv_layers.new(name="light")
ground.data.uv_layers.active = uv
for loop in ground.data.loops:
    co = ground.data.vertices[loop.vertex_index].co
    uv.data[loop.index].uv = ((co.x - x0) / span, (co.y - y0) / span)

# --- 3. bake the light on the ground ---------------------------------------------------------------------
# A flat card above the island takes the bake: rays go straight down from it and record the light on
# the first ground surface they meet (grass over the island's top, a path over grass), lit by the sun
# and the sky with the buildings and trees casting their shadows.
img = bpy.data.images.new("ground_light", LIGHT_SIZE, LIGHT_SIZE, float_buffer=True)
card_mesh = bpy.data.meshes.new("light_card")
card_mesh.from_pydata([(x0, y0, 0.6), (x0 + span, y0, 0.6), (x0 + span, y0 + span, 0.6), (x0, y0 + span, 0.6)],
                      [], [(0, 1, 2, 3)])
card_uv = card_mesh.uv_layers.new(name="light")
for loop, co in zip(card_uv.data, ((0, 0), (1, 0), (1, 1), (0, 1))):
    loop.uv = co
card = bpy.data.objects.new("light_card", card_mesh)
scene.collection.objects.link(card)
card_mat = bpy.data.materials.new("light_card"); card_mat.use_nodes = True
node = card_mat.node_tree.nodes.new("ShaderNodeTexImage"); node.image = img
card_mat.node_tree.nodes.active = node
card_mesh.materials.append(card_mat)
# The card must render to take the bake, but no ray may see it (it would shade the ground it bakes).
for flag in ("visible_camera", "visible_shadow", "visible_diffuse", "visible_glossy", "visible_transmission",
             "visible_volume_scatter"):
    setattr(card, flag, False)
bpy.ops.object.select_all(action="DESELECT")
ground.select_set(True)
card.select_set(True)
bpy.context.view_layer.objects.active = card
scene.render.bake.use_selected_to_active = True
scene.render.bake.cage_extrusion = 30.0
scene.render.bake.max_ray_distance = 40.0
scene.cycles.samples = int(argv[3]) if len(argv) > 3 else 256
scene.render.bake.use_pass_direct = True
scene.render.bake.use_pass_indirect = True
scene.render.bake.use_pass_color = False
scene.render.bake.margin = 4
bpy.ops.object.bake(type="DIFFUSE")
px = np.array(img.pixels[:], dtype=np.float32).reshape(LIGHT_SIZE, LIGHT_SIZE, 4)
lum = px[..., 0] * 0.2126 + px[..., 1] * 0.7152 + px[..., 2] * 0.0722
lit = np.percentile(lum[lum > 0], 98)
light = np.clip(lum / lit, 0, 1) ** 0.85
out = bpy.data.images.new("ground_light_8", LIGHT_SIZE, LIGHT_SIZE)
rgba = np.dstack([light, light, light, np.ones_like(light)]).astype(np.float32)
out.pixels[:] = rgba.ravel()
scene.render.image_settings.file_format = "WEBP"
scene.render.image_settings.color_mode = "RGB"
scene.render.image_settings.quality = 82
out.save_render(str(OUT / "ground-light.webp"), scene=scene)

# --- 4. export ---------------------------------------------------------------------------------------------
for ob in list(scene.objects):
    keep = ob.name in ("ground", "island_sides", "buildings", "units", "landmarks") or ob is cam or ob.name.startswith("tree")
    keep = keep and ob.name != "light_card"
    if not keep or ob.type == "EMPTY":
        bpy.data.objects.remove(ob, do_unlink=True)
protos = [o for o in bpy.data.objects if o.name.startswith("tree") and o.type == "MESH"]
for p in protos:
    if p.name not in scene.collection.objects:
        scene.collection.objects.link(p)
    p.location = (0, 0, 0)
for mat in bpy.data.materials:                   # the browser colours by material name
    if mat.node_tree:
        for n in [n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE"]:
            mat.node_tree.nodes.remove(n)
# Only the ground's light UV leaves Blender (curves and primitives brought their own; the browser
# would read the first one).
for ob in [ground, sides, buildings, units, landmarks, *protos]:
    for layer in [l for l in ob.data.uv_layers if not (ob is ground and l.name == "light")]:
        ob.data.uv_layers.remove(layer)
bpy.ops.object.select_all(action="DESELECT")
for ob in [ground, sides, buildings, units, landmarks, cam, *protos]:
    ob.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(OUT / "campus.glb"), export_format="GLB", use_selection=True,
                          export_apply=True, export_yup=True, export_cameras=True, export_lights=False,
                          export_attributes=True, export_normals=True, export_texcoords=True,
                          export_materials="EXPORT", export_image_format="NONE",
                          export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=7,
                          export_draco_position_quantization=14, export_draco_normal_quantization=8,
                          export_draco_texcoord_quantization=12, export_draco_generic_quantization=12)

sun_dir = ns["sun"]
info = {
    "attribution": TABLE["attribution"],
    "palette": {k: ([round(c, 4) for c in v] if isinstance(v[0], float) else [[round(c, 4) for c in w] for w in v])
                for k, v in ns["palette"].items()},
    "sun": {"direction": to_web(*sun_dir), "color": list(ns["sun_color"])},
    "camera": {"position": to_web(*cam.location), "target": to_web(*ns["target"]), "lens": cam.data.lens,
               "sensor": cam.data.sensor_width, "aspect": POSTER[0] / POSTER[1]},
    "light": {"x0": round(x0, 2), "z0": round(-(y0 + span), 2), "span": round(span, 2)},
    "trees": [[round(x, 1), round(-y, 1), round(s, 2), round(r, 2), k] for x, y, s, r, k in ns["trees"]],
}
(OUT / "model.json").write_text(json.dumps(info, separators=(",", ":")) + "\n", encoding="utf-8")
print("EXPORTED", OUT, {p.name: os.path.getsize(p) for p in OUT.iterdir() if p.is_file()})
