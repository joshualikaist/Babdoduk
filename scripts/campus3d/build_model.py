# -*- coding: utf-8 -*-
"""The 3D campus miniature (docs/CAMPUS_MAP.md), built in Blender from inputs/campus3d/campus.json.

    blender -b --factory-startup -P scripts/campus3d/build_model.py -- \
        inputs/campus3d/campus.json clay .local/campus/clay.png [samples] [x y distance]

Style clay was chosen by the owner on 2026-11-04 (paper and dusk were the other look-dev styles and
stay for comparison). The island is the KAIST campus outline; buildings stand at their OpenStreetMap
floors (scripts/campus3d/buildings.py uses the same heights for the pins), with rounded edges, a
parapet round each flat roof, rooftop plant on the large ones and floor bands of windows.
The sample pins (E11, E9, N13) are for renders only; the site draws its pins as buttons.
"""
import json, math, random, sys
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, STYLE, OUT = argv[0], argv[1], argv[2]
SAMPLES = int(argv[3]) if len(argv) > 3 else 96
data = json.load(open(SRC))
random.seed(7)

PINS = ("E11", "E9", "N13")          # sample "today" events for the mockup

STYLES = {
    "clay": dict(base_top=(0.93, 0.89, 0.80), base_side=(0.62, 0.45, 0.33), grass=(0.55, 0.72, 0.42),
                 wood=(0.42, 0.62, 0.34), pitch=(0.47, 0.70, 0.40), court=(0.45, 0.64, 0.62),
                 track=(0.80, 0.52, 0.40), parking=(0.82, 0.80, 0.76), unit=(0.80, 0.76, 0.70),
                 path=(0.98, 0.96, 0.91), road=(0.90, 0.87, 0.82), water=(0.36, 0.66, 0.78),
                 wall=(0.97, 0.94, 0.88), roof=(0.90, 0.84, 0.76), glass=(0.62, 0.72, 0.80),
                 crown=((0.38, 0.62, 0.32), (0.50, 0.70, 0.36), (0.30, 0.54, 0.30)), trunk=(0.45, 0.32, 0.22),
                 highlight=(0.99, 0.80, 0.88), world=(0.96, 0.92, 0.86), world_strength=0.9,
                 sun=(1.0, 0.95, 0.88), sun_strength=3.2, sun_elev=30, sun_azim=225, sun_angle=4.0,
                 emission=0.0),
    "paper": dict(base_top=(0.96, 0.95, 0.92), base_side=(0.86, 0.83, 0.78), grass=(0.86, 0.90, 0.80),
                  wood=(0.80, 0.86, 0.74), pitch=(0.88, 0.91, 0.84), court=(0.90, 0.90, 0.88),
                  track=(0.93, 0.88, 0.84), parking=(0.92, 0.91, 0.88), unit=(0.90, 0.90, 0.89),
                  path=(1.0, 1.0, 1.0), road=(0.95, 0.94, 0.92), water=(0.78, 0.86, 0.90),
                  wall=(1.0, 1.0, 0.99), roof=(0.97, 0.97, 0.96), glass=(0.90, 0.91, 0.93),
                  crown=((0.84, 0.90, 0.78), (0.88, 0.92, 0.82), (0.80, 0.87, 0.74)), trunk=(0.80, 0.76, 0.70),
                  highlight=(0.99, 0.84, 0.91), world=(1.0, 0.99, 0.97), world_strength=1.15,
                  sun=(1.0, 1.0, 1.0), sun_strength=2.4, sun_elev=50, sun_azim=225, sun_angle=8.0,
                  emission=0.0),
    "dusk": dict(base_top=(0.80, 0.72, 0.66), base_side=(0.40, 0.28, 0.25), grass=(0.36, 0.50, 0.36),
                 wood=(0.26, 0.40, 0.30), pitch=(0.32, 0.48, 0.32), court=(0.30, 0.42, 0.44),
                 track=(0.60, 0.38, 0.32), parking=(0.56, 0.52, 0.52), unit=(0.55, 0.50, 0.50),
                 path=(0.86, 0.78, 0.70), road=(0.72, 0.64, 0.60), water=(0.25, 0.36, 0.55),
                 wall=(0.92, 0.84, 0.78), roof=(0.70, 0.62, 0.60), glass=(0.30, 0.32, 0.42),
                 crown=((0.24, 0.40, 0.28), (0.30, 0.46, 0.30), (0.20, 0.34, 0.26)), trunk=(0.30, 0.22, 0.18),
                 highlight=(1.0, 0.70, 0.82), world=(0.35, 0.36, 0.55), world_strength=0.55,
                 sun=(1.0, 0.62, 0.38), sun_strength=4.0, sun_elev=11, sun_azim=250, sun_angle=2.0,
                 emission=4.0),
}
S = STYLES[STYLE]
LEVEL = 3.6

# --- scene ---------------------------------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
col = scene.collection


def srgb(c):
    return tuple((x / 12.92) if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def material(name, color, rough=0.75, spec=0.3, emission=None, strength=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*srgb(color), 1)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Specular IOR Level"].default_value = spec
    if emission:
        p.inputs["Emission Color"].default_value = (*srgb(emission), 1)
        p.inputs["Emission Strength"].default_value = strength
    return m


def node(tree, kind, **inputs):
    n = tree.nodes.new(kind)
    for k, v in inputs.items():
        setattr(n, k, v)
    return n


def math_node(tree, op, a, b=None, value=None):
    n = tree.nodes.new("ShaderNodeMath")
    n.operation = op
    links = tree.links
    if isinstance(a, (int, float)):
        n.inputs[0].default_value = a
    else:
        links.new(a, n.inputs[0])
    if b is not None:
        if isinstance(b, (int, float)):
            n.inputs[1].default_value = b
        else:
            links.new(b, n.inputs[1])
    return n.outputs[0]


def building_material(name, wall, roof, glass, emission):
    """Walls with floor bands of windows and mullions; roofs by normal; dusk windows glow."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    t = m.node_tree
    p = t.nodes["Principled BSDF"]
    geo = t.nodes.new("ShaderNodeNewGeometry")
    sep_n = t.nodes.new("ShaderNodeSeparateXYZ"); t.links.new(geo.outputs["Normal"], sep_n.inputs[0])
    sep_p = t.nodes.new("ShaderNodeSeparateXYZ"); t.links.new(geo.outputs["Position"], sep_p.inputs[0])
    nz = math_node(t, "ABSOLUTE", sep_n.outputs[2])
    wall_f = math_node(t, "LESS_THAN", nz, 0.35)
    roof_f = math_node(t, "GREATER_THAN", nz, 0.8)
    band = math_node(t, "FRACT", math_node(t, "DIVIDE", math_node(t, "SUBTRACT", sep_p.outputs[2], 0.4), LEVEL))
    win_v = math_node(t, "MULTIPLY", math_node(t, "GREATER_THAN", band, 0.38), math_node(t, "LESS_THAN", band, 0.78))
    along = math_node(t, "ADD", sep_p.outputs[0], sep_p.outputs[1])
    col_f = math_node(t, "GREATER_THAN", math_node(t, "FRACT", math_node(t, "DIVIDE", along, 3.2)), 0.22)
    above = math_node(t, "GREATER_THAN", sep_p.outputs[2], 2.2)
    window = math_node(t, "MULTIPLY", math_node(t, "MULTIPLY", wall_f, win_v), math_node(t, "MULTIPLY", col_f, above))
    mix_roof = t.nodes.new("ShaderNodeMix"); mix_roof.data_type = "RGBA"
    t.links.new(roof_f, mix_roof.inputs["Factor"])
    mix_roof.inputs["A"].default_value = (*srgb(wall), 1); mix_roof.inputs["B"].default_value = (*srgb(roof), 1)
    mix_win = t.nodes.new("ShaderNodeMix"); mix_win.data_type = "RGBA"
    t.links.new(window, mix_win.inputs["Factor"])
    t.links.new(mix_roof.outputs["Result"], mix_win.inputs["A"]); mix_win.inputs["B"].default_value = (*srgb(glass), 1)
    t.links.new(mix_win.outputs["Result"], p.inputs["Base Color"])
    rough = math_node(t, "SUBTRACT", 0.8, math_node(t, "MULTIPLY", window, 0.6))
    t.links.new(rough, p.inputs["Roughness"])
    if emission:
        info = t.nodes.new("ShaderNodeObjectInfo")
        lit = math_node(t, "GREATER_THAN", info.outputs["Random"], 0.25)
        cell = math_node(t, "GREATER_THAN", math_node(t, "FRACT", math_node(t, "MULTIPLY", math_node(t, "ADD", along, math_node(t, "MULTIPLY", sep_p.outputs[2], 7.31)), 0.37)), 0.35)
        glow = math_node(t, "MULTIPLY", math_node(t, "MULTIPLY", window, lit), cell)
        p.inputs["Emission Color"].default_value = (*srgb((1.0, 0.78, 0.48)), 1)
        t.links.new(math_node(t, "MULTIPLY", glow, emission), p.inputs["Emission Strength"])
    return m


def base_material():
    m = bpy.data.materials.new("base")
    m.use_nodes = True
    t = m.node_tree
    p = t.nodes["Principled BSDF"]
    geo = t.nodes.new("ShaderNodeNewGeometry")
    sep = t.nodes.new("ShaderNodeSeparateXYZ"); t.links.new(geo.outputs["Normal"], sep.inputs[0])
    top = math_node(t, "GREATER_THAN", sep.outputs[2], 0.7)
    mix = t.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"
    t.links.new(top, mix.inputs["Factor"])
    mix.inputs["A"].default_value = (*srgb(S["base_side"]), 1); mix.inputs["B"].default_value = (*srgb(S["base_top"]), 1)
    t.links.new(mix.outputs["Result"], p.inputs["Base Color"])
    p.inputs["Roughness"].default_value = 0.9
    return m


MAT = {k: material(k, S[k]) for k in ("grass", "wood", "pitch", "court", "track", "parking", "path", "road", "unit")}
MAT["water"] = material("water", S["water"], rough=0.06, spec=0.6)
MAT["base"] = base_material()
MAT["building"] = building_material("building", S["wall"], S["roof"], S["glass"], S["emission"])
MAT["highlight"] = building_material("highlight", S["highlight"], S["highlight"], S["glass"], S["emission"])
MAT["trunk"] = material("trunk", S["trunk"], rough=0.9)
MAT["crowns"] = [material(f"crown{i}", c, rough=0.85) for i, c in enumerate(S["crown"])]
MAT["pin"] = material("pin", (0.75, 0.09, 0.36), rough=0.35, spec=0.5, emission=(0.93, 0.28, 0.55), strength=0.4)
MAT["pin_white"] = material("pin_white", (1, 1, 1), rough=0.4)


def slab(name, rings, z0, z1, mat, bevel=0.0):
    """A filled 2D curve (holes by even-odd) extruded between z0 and z1, edges rounded by bevel."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "2D"
    cu.fill_mode = "BOTH"
    cu.extrude = max((z1 - z0) / 2 - bevel, 0.01)
    cu.bevel_depth = bevel
    cu.bevel_resolution = 2 if bevel else 0
    for pts in rings:
        if pts[0] == pts[-1]:
            pts = pts[:-1]
        if len(pts) < 3:
            continue
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for i, (x, y) in enumerate(pts):
            sp.points[i].co = (x, y, 0, 1)
        sp.use_cyclic_u = True
    ob = bpy.data.objects.new(name, cu)
    ob.location.z = (z0 + z1) / 2
    cu.materials.append(mat)
    col.objects.link(ob)
    return ob


def ribbons(name, lines, width, z, mat):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = width / 2
    cu.bevel_resolution = 0
    cu.fill_mode = "FULL"
    for pts in lines:
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for i, (x, y) in enumerate(pts):
            sp.points[i].co = (x, y, 0, 1)
    ob = bpy.data.objects.new(name, cu)
    ob.location.z = z
    ob.scale.z = 0.12 / width
    cu.materials.append(mat)
    col.objects.link(ob)
    return ob


# --- the island ------------------------------------------------------------------------------------
GROUND = 0.0
slab("base", [data["boundary"]], -28, GROUND, MAT["base"], bevel=3.0)
def poly_area(pts):
    return abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2


# Nested areas (courts inside a sports ground) must not share a top face: smaller ones sit a little higher.
COURTS = {"tennis", "badminton", "basketball", "volleyball"}
for kind, z1 in (("parking", 0.25), ("track", 0.30), ("pitch", 0.34), ("grass", 0.38), ("wood", 0.40)):
    ranked = sorted(data.get(kind, []), key=lambda a: -poly_area(a["pts"]))
    for i, a in enumerate(ranked):
        top = z1 + 0.05 * i / max(1, len(ranked) - 1)
        mat = MAT["court"] if kind == "pitch" and a.get("sport") in COURTS else MAT[kind]
        slab(f"{kind}{i}", [a["pts"], *a.get("holes", [])], GROUND, top, mat, bevel=0.12)
for i, a in enumerate(data["water"]):
    slab(f"water{i}", [a["pts"], *a.get("holes", [])], GROUND - 0.2, 0.12, MAT["water"], bevel=0.0)
def on_island(x, y, poly=data["boundary"]):
    c = False
    for i in range(len(poly)):
        x1, y1 = poly[i]; x2, y2 = poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def clipped(lines):
    """Polylines cut where they leave the island (roads ran off its edge)."""
    out = []
    for pts in lines:
        run = []
        for x, y in pts:
            if on_island(x, y):
                run.append((x, y))
            else:
                if len(run) >= 2:
                    out.append(run)
                run = []
        if len(run) >= 2:
            out.append(run)
    return out


ribbons("roads", clipped(r["pts"] for r in data["roads"]), 6.5, 0.30, MAT["road"])
ribbons("paths", clipped(p["pts"] for p in data["paths"]), 2.6, 0.46, MAT["path"])


def height(b):
    if b.get("levels"):
        return b["levels"] * LEVEL + 1.0
    a = b.get("area") or 0
    return (1 if a < 150 else 2 if a < 600 else 4) * LEVEL + 1.0


import bmesh


def finish_roof(ob, b, h):
    """Mesh the building, sink its flat roof inside a 0.8 m parapet, and set plant on large roofs."""
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.convert(target="MESH")
    ob.select_set(False)
    me = ob.data
    bm = bmesh.new(); bm.from_mesh(me)
    zmax = max(v.co.z for v in bm.verts)
    tops = [f for f in bm.faces if f.normal.z > 0.99 and all(abs(v.co.z - zmax) < 0.02 for v in f.verts)]
    if tops and poly_area(b["pts"]) > 60:
        xs0 = [v.co.x for v in bm.verts]; ys0 = [v.co.y for v in bm.verts]
        before = bm.copy()
        bmesh.ops.inset_region(bm, faces=tops, thickness=0.8, depth=0.0, use_even_offset=True)
        inner = {v for f in tops for v in f.verts}
        bmesh.ops.translate(bm, verts=list(inner), vec=(0, 0, -0.9))
        # A narrow, bent outline can make the inset shoot a corner far away (W7 did, 2 km): keep
        # that building without a parapet.
        if any(not (min(xs0) - 1 <= v.co.x <= max(xs0) + 1 and min(ys0) - 1 <= v.co.y <= max(ys0) + 1) for v in bm.verts):
            bm.free(); bm = before
        else:
            before.free()
    bm.to_mesh(me); bm.free()
    area = poly_area(b["pts"])
    if area < 1200:
        return
    xs = [p[0] for p in b["pts"]]; ys = [p[1] for p in b["pts"]]
    placed = 0
    for _ in range(40):
        if placed >= min(3, 1 + int(area // 2500)):
            break
        x = random.uniform(min(xs), max(xs)); y = random.uniform(min(ys), max(ys))
        if all(inside(x + dx, y + dy, b["pts"]) for dx, dy in ((0, 0), (9, 0), (-9, 0), (0, 9), (0, -9))):
            w, d, uh = random.uniform(5, 10), random.uniform(4, 8), random.uniform(1.8, 3.0)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, 0.4 + h - 0.9 + uh / 2))
            unit = bpy.context.active_object
            unit.scale = (w, d, uh)
            unit.rotation_euler.z = random.uniform(0, math.pi)
            unit.data.materials.append(MAT["unit"])
            mod = unit.modifiers.new("round", "BEVEL"); mod.width = 0.12; mod.segments = 1
            placed += 1


def inside(x, y, poly):
    c = False
    for i in range(len(poly)):
        x1, y1 = poly[i]; x2, y2 = poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


pin_spots = {}
footprints = []
for i, b in enumerate(data["buildings"]):
    h = height(b)
    mat = MAT["highlight"] if b.get("code") in PINS else MAT["building"]
    ob = slab(f"b{i}_{b.get('code') or ''}", [b["pts"], *b.get("holes", [])], 0.4, 0.4 + h, mat, bevel=0.55)
    finish_roof(ob, b, h)
    xs = [p[0] for p in b["pts"]]; ys = [p[1] for p in b["pts"]]
    footprints.append((min(xs), min(ys), max(xs), max(ys), b["pts"]))
    if b.get("code") in PINS and (b["code"] not in pin_spots or b["area"] > pin_spots[b["code"]][2]):
        pin_spots[b["code"]] = ((sum(xs) / len(xs), sum(ys) / len(ys)), h, b["area"])


def in_building(x, y):
    return any(a - 2 <= x <= c + 2 and b - 2 <= y <= d + 2 and inside(x, y, pts) for a, b, c, d, pts in footprints)


# --- trees: low-poly lollipops, instanced ----------------------------------------------------------
proto = bpy.data.collections.new("tree_protos")
scene.collection.children.link(proto)
proto.hide_render = False
tree_protos = []
for i, cmat in enumerate(MAT["crowns"]):
    bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=0.45, depth=3.0, location=(0, 0, 1.5))
    trunk = bpy.context.active_object; trunk.data.materials.append(MAT["trunk"])
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=3.2, location=(0, 0, 5.4))
    crown = bpy.context.active_object; crown.data.materials.append(cmat)
    crown.scale = (1, 1, 1.15)
    bpy.ops.object.select_all(action="DESELECT")
    trunk.select_set(True); crown.select_set(True); bpy.context.view_layer.objects.active = crown
    bpy.ops.object.join()
    t = bpy.context.active_object; t.name = f"tree{i}"
    for c in t.users_collection:
        c.objects.unlink(t)
    proto.objects.link(t)
    tree_protos.append(t)
proto_layer = bpy.context.view_layer.layer_collection.children[proto.name]
proto_layer.exclude = True

tree_col = bpy.data.collections.new("trees")
scene.collection.children.link(tree_col)
inst_cols = []
for t in tree_protos:
    c = bpy.data.collections.new(t.name + "_c"); c.objects.link(t); inst_cols.append(c)


def scatter(poly, holes, spacing, cap):
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    area = (max(xs) - min(xs)) * (max(ys) - min(ys))
    n = min(cap, int(area / (spacing * spacing)))
    out = []
    for _ in range(n * 2):
        x = random.uniform(min(xs), max(xs)); y = random.uniform(min(ys), max(ys))
        if inside(x, y, poly) and not any(inside(x, y, h) for h in holes) and not in_building(x, y):
            out.append((x, y))
        if len(out) >= n:
            break
    return out


spots = []
for a in data["wood"]:
    spots += scatter(a["pts"], a.get("holes", []), 9.0, 400)
for a in data["grass"]:
    spots += scatter(a["pts"], a.get("holes", []), 26.0, 25)
for i, (x, y) in enumerate(spots[:3500]):
    e = bpy.data.objects.new(f"t{i}", None)
    e.instance_type = "COLLECTION"
    e.instance_collection = random.choice(inst_cols)
    e.location = (x, y, 0.38)
    s = random.uniform(0.75, 1.35)
    e.scale = (s, s, s * random.uniform(0.9, 1.2))
    e.rotation_euler.z = random.uniform(0, math.tau)
    tree_col.objects.link(e)

# --- pins for the mockup ---------------------------------------------------------------------------
for code, ((x, y), h, _) in pin_spots.items():
    top = 0.4 + h
    bpy.ops.mesh.primitive_cone_add(vertices=24, radius1=8.0, radius2=0.0, depth=26, location=(x, y, top + 15),
                                    rotation=(math.pi, 0, 0))
    bpy.context.active_object.data.materials.append(MAT["pin"])
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=13.5, location=(x, y, top + 37))
    bpy.ops.object.shade_smooth()
    bpy.context.active_object.data.materials.append(MAT["pin"])
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=5.6, location=(x, y, top + 37))
    bpy.ops.object.shade_smooth()
    dot = bpy.context.active_object; dot.data.materials.append(MAT["pin_white"])
    dot.location.y -= 9.5; dot.location.x += 4.0; dot.location.z += 2.0
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=20, depth=0.4, location=(x, y, top + 0.3))
    bpy.context.active_object.data.materials.append(MAT["pin"])

# --- shadow catcher, light, camera -----------------------------------------------------------------
bpy.ops.mesh.primitive_plane_add(size=6000, location=(0, 0, -28.2))
catcher = bpy.context.active_object
catcher.is_shadow_catcher = True

world = bpy.data.worlds.new("world"); scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (*srgb(S["world"]), 1)
bg.inputs["Strength"].default_value = S["world_strength"]

sun_data = bpy.data.lights.new("sun", "SUN")
sun_data.energy = S["sun_strength"]
sun_data.color = S["sun"]
sun_data.angle = math.radians(S["sun_angle"])
sun = bpy.data.objects.new("sun", sun_data); col.objects.link(sun)
sun.rotation_euler = (math.radians(90 - S["sun_elev"]), 0, math.radians(S["sun_azim"]))

cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 85
cam_data.clip_start = 50; cam_data.clip_end = 20000
cam = bpy.data.objects.new("cam", cam_data); col.objects.link(cam)
target = Vector((20, 10, 0))
elev, azim, dist = math.radians(46), math.radians(-28), 3750
if len(argv) > 6:                       # close-up: target x, y and distance
    target = Vector((float(argv[4]), float(argv[5]), 0)); dist = float(argv[6]); elev = math.radians(42)
cam.location = target + Vector((math.sin(azim) * math.cos(elev) * dist, -math.cos(azim) * math.cos(elev) * dist,
                                math.sin(elev) * dist))
direction = target - cam.location
cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
cam_data.dof.use_dof = True
cam_data.dof.focus_distance = (target - cam.location).length
cam_data.dof.aperture_fstop = 1.4 if dist > 2000 else 0.9
scene.camera = cam

# --- render ------------------------------------------------------------------------------------------
scene.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "CUDA"; prefs.get_devices()
for d in prefs.devices:
    d.use = d.type == "CUDA"
scene.cycles.device = "GPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.cycles.denoiser = "OPENIMAGEDENOISE"
scene.render.film_transparent = True
scene.render.resolution_x, scene.render.resolution_y = 1600, 1200
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Medium High Contrast" if STYLE != "paper" else "AgX - Base Contrast"
scene.render.filepath = OUT
bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=OUT.replace(".png", ".blend"))
print("RENDERED", OUT, "trees", len(spots[:3500]), "pins", list(pin_spots))
