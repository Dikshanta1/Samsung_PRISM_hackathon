"""Import the textured Character Creator head and turn its eyes into rigid, measurable eyeballs.

The source is ``Hassan+V1.blend``, a Character Creator 3 export containing the
character twice: once in centimetres and once (``Armature.001``) in metres with
its key textures packed. Only the metre-scale copy is appended.

Three things are fixed up on the way in:

* **Materials.** The CC3 importer's node graphs reference about a hundred
  auxiliary maps (AO, SSS, micro-normal, blend maps) that only existed on the
  author's machine. Blender renders a missing image as magenta, and the mixer
  groups multiply it in, so the skin comes out black. Every material that uses
  a missing image is replaced with a small Principled BSDF tree built from the
  maps that *are* packed (diffuse, normal, opacity). Procedural materials (eye
  occlusion, tear line) are kept as authored.
* **Eyes.** CC3 ships both eyeballs as one mesh skinned to two bones, in a
  posed (not rest) armature. Each eyeball is baked out of the evaluated pose
  into its own mesh, its rotation centre is found by fitting a sphere to the
  sclera, and its optical axis is taken from the pupil position in the iris
  texture. The eyeball is then rotated about that centre so the optical axis is
  exactly world ``-Y``, which makes "zero rotation" mean "looking straight
  ahead" for the gaze maths in ``calibration.py``.
* **Pupil landmark.** The pupil is painted in the texture, so there is no pupil
  geometry to measure. ``pupil_ring_points`` maps the pupil margin, measured
  from the texture, through the mesh UVs onto the eyeball surface. ``eye_rig``
  turns those points into an invisible ``Pupil_*`` landmark mesh.
"""
from __future__ import annotations

from math import cos, pi, sin, sqrt
from pathlib import Path
import os

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.geometry import barycentric_transform, intersect_point_tri_2d

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ENV = "TRACK1_CHARACTER_BLEND"
DEFAULT_SOURCE = ROOT / "assets" / "source" / "Hassan+V1.blend"
SOURCE_ROOT_OBJECT = "Armature.001"  # metre-scale copy with packed textures
FACE_RIG_NAME = "FaceRig"
HEAD_BONE = "CC_Base_Head"
EXCLUDED_OBJECTS = {"Jeans", "Boots"}  # below the frame; dropping them keeps scene.blend small

EYE_MATERIAL_PREFIX = "Std_Eye_"  # inner eyeball: sclera and iris texture
CORNEA_MATERIAL_PREFIX = "Std_Cornea_"  # transparent outer shell
SCLERA_UV_MIN_RADIUS = 0.20  # UV distance from the pupil beyond which the eyeball is sclera only
PUPIL_DARK_LUMINANCE = 0.05  # linear luminance below which an iris-texture pixel is pupil
IRIS_UV_RADIUS = 0.122  # iris edge in the CC3 eye texture (shading masks only, not ground truth)
IRIS_GAIN = 2.2  # stands in for the CC3 eye shader's iris brightness
PUPIL_EDGE_UV = 0.006  # soft edge of the brightness mask just outside the pupil margin


class CharacterAssetError(RuntimeError):
    """The character source is missing or does not have the expected structure."""


# --------------------------------------------------------------------------
# Source and append
# --------------------------------------------------------------------------

def resolve_source(explicit: str | os.PathLike | None = None) -> Path:
    """The character .blend: explicit argument, then $TRACK1_CHARACTER_BLEND, then assets/source/."""
    for candidate in (explicit, os.environ.get(SOURCE_ENV), DEFAULT_SOURCE):
        if candidate:
            path = Path(candidate).expanduser().resolve()
            if path.is_file():
                return path
    raise CharacterAssetError(
        f"Character source not found. Put Hassan+V1.blend at {DEFAULT_SOURCE} or set {SOURCE_ENV}.")


def _base_name(name: str) -> str:
    """``Std_Skin_Head.001`` -> ``Std_Skin_Head``."""
    head, dot, tail = name.rpartition(".")
    return head if dot and tail.isdigit() else name


def append_character(source: Path, scene: bpy.types.Scene) -> bpy.types.Object:
    """Append the metre-scale armature and everything parented to it; return the armature."""
    with bpy.data.libraries.load(str(source), link=False) as (src, _):
        names = list(src.objects)
    if SOURCE_ROOT_OBJECT not in names:
        raise CharacterAssetError(f"{source.name} has no {SOURCE_ROOT_OBJECT} object")
    # Parent relationships are only known after loading, so load everything once,
    # keep the root's hierarchy and delete the rest.
    with bpy.data.libraries.load(str(source), link=False) as (_, dst):
        dst.objects = names
    loaded = [obj for obj in dst.objects if obj is not None]
    root = next(obj for obj in loaded if _base_name(obj.name) == _base_name(SOURCE_ROOT_OBJECT) and obj.type == "ARMATURE"
                and obj.name.startswith(SOURCE_ROOT_OBJECT))
    keep = {root} | {obj for obj in loaded if obj.parent is root and obj.name not in EXCLUDED_OBJECTS}
    for obj in loaded:
        if obj not in keep:
            bpy.data.objects.remove(obj)
    for obj in keep:
        scene.collection.objects.link(obj)
        obj.hide_render = False
        obj.hide_viewport = False
    root.name = FACE_RIG_NAME
    root.data.name = FACE_RIG_NAME
    for obj in keep - {root}:
        obj.name = _base_name(obj.name)
    bpy.context.view_layer.update()
    return root


# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------

def _images_in(tree: bpy.types.NodeTree) -> list[bpy.types.Image]:
    found: list[bpy.types.Image] = []
    for node in tree.nodes:
        if node.type == "TEX_IMAGE" and node.image is not None:
            found.append(node.image)
        elif node.type == "GROUP" and node.node_tree is not None:
            found.extend(_images_in(node.node_tree))
    return found


def _image_available(image: bpy.types.Image) -> bool:
    return image.packed_file is not None or Path(bpy.path.abspath(image.filepath)).is_file()


def _pick(images: list[bpy.types.Image], role: str) -> bpy.types.Image | None:
    """The packed map for ``role`` (Diffuse, Normal, Opacity), preferring the un-suffixed copy."""
    matches = sorted({img for img in images if img.packed_file is not None and role in img.name},
                     key=lambda img: (img.name != _base_name(img.name), img.name))
    return matches[0] if matches else None


def _material_kind(base: str) -> str:
    if base.startswith("Std_Skin_") or base == "Std_Nails":
        return "skin"
    if base.startswith(EYE_MATERIAL_PREFIX) and "Occlusion" not in base:
        return "eye"
    if base.startswith(CORNEA_MATERIAL_PREFIX):
        return "cornea"
    if base.startswith(("Hair", "Beard", "Male_Bushy", "Scalp", "Std_Eyelash")):
        return "hair"
    if "Teeth" in base or "Tongue" in base:
        return "mouth"
    return "cloth"


def _set_render_method(material: bpy.types.Material, method: str) -> None:
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = method
    if hasattr(material, "use_transparent_shadow"):
        material.use_transparent_shadow = True


def _texture(nodes, image: bpy.types.Image, non_color: bool, location) -> bpy.types.Node:
    node = nodes.new("ShaderNodeTexImage")
    node.image = image
    node.location = location
    node.interpolation = "Linear"
    if non_color:
        image.colorspace_settings.name = "Non-Color"
    return node


def _rebuild(material: bpy.types.Material, images: list[bpy.types.Image]) -> None:
    """Replace the material's node tree with a compact, fully resolvable PBR tree."""
    kind = _material_kind(_base_name(material.name))
    diffuse, normal, opacity = (_pick(images, role) for role in ("Diffuse", "Normal", "Opacity"))
    tree = material.node_tree
    tree.nodes.clear()
    nodes, links = tree.nodes, tree.links
    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (600, 0)

    if kind == "cornea":
        # Clear, wet shell: transparent with a Fresnel-weighted sharp reflection.
        fresnel = nodes.new("ShaderNodeFresnel")
        fresnel.inputs["IOR"].default_value = 1.376
        glossy = nodes.new("ShaderNodeBsdfGlossy")
        glossy.inputs["Roughness"].default_value = 0.02
        clear = nodes.new("ShaderNodeBsdfTransparent")
        mix = nodes.new("ShaderNodeMixShader")
        links.new(fresnel.outputs["Fac"], mix.inputs["Fac"])
        links.new(clear.outputs["BSDF"], mix.inputs[1])
        links.new(glossy.outputs["BSDF"], mix.inputs[2])
        links.new(mix.outputs["Shader"], output.inputs["Surface"])
        _set_render_method(material, "DITHERED")  # BLENDED sorting made 1-level differences between runs
        material.use_backface_culling = True
        return

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (250, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    settings = {
        "skin": dict(roughness=0.48, specular=0.45, sss=0.12),
        "eye": dict(roughness=0.30, specular=0.50, sss=0.0),
        "hair": dict(roughness=0.55, specular=0.35, sss=0.0),
        "mouth": dict(roughness=0.35, specular=0.50, sss=0.05),
        "cloth": dict(roughness=0.80, specular=0.25, sss=0.0),
    }[kind]
    bsdf.inputs["Roughness"].default_value = settings["roughness"]
    bsdf.inputs["Specular IOR Level"].default_value = settings["specular"]
    if kind == "eye":
        # The cornea's tear film: a clear, glossy coat over the sclera and iris.
        bsdf.inputs["Coat Weight"].default_value = 1.0
        bsdf.inputs["Coat Roughness"].default_value = 0.03
        bsdf.inputs["Coat IOR"].default_value = 1.376
        # The tear film is a smooth dome, unlike the dished iris under it: its normal is the
        # direction from the eyeball centre (the object origin) to the shading point.
        coords = nodes.new("ShaderNodeTexCoord")
        radial = nodes.new("ShaderNodeVectorMath")
        radial.operation = "NORMALIZE"
        to_world = nodes.new("ShaderNodeVectorTransform")
        to_world.vector_type = "NORMAL"
        to_world.convert_from = "OBJECT"
        to_world.convert_to = "WORLD"
        links.new(coords.outputs["Object"], radial.inputs[0])
        links.new(radial.outputs["Vector"], to_world.inputs["Vector"])
        links.new(to_world.outputs["Vector"], bsdf.inputs["Coat Normal"])
    if settings["sss"]:
        bsdf.inputs["Subsurface Weight"].default_value = settings["sss"]
        bsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.35, 0.20)
        bsdf.inputs["Subsurface Scale"].default_value = 0.004

    if diffuse is not None:
        colour = _texture(nodes, diffuse, False, (-500, 200))
        colour_out = colour.outputs["Color"]
        if kind == "eye":
            colour_out = _eye_colour(nodes, links, diffuse, colour_out)
        links.new(colour_out, bsdf.inputs["Base Color"])
    if normal is not None:
        normal_tex = _texture(nodes, normal, True, (-500, -150))
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.location = (0, -200)
        normal_map.inputs["Strength"].default_value = 0.8 if kind == "skin" else 1.0
        links.new(normal_tex.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
    if opacity is not None:
        alpha = _texture(nodes, opacity, True, (-500, -450))
        links.new(alpha.outputs["Color"], bsdf.inputs["Alpha"])
    elif kind == "hair" and diffuse is not None and diffuse.channels == 4:
        # Some hair cards (e.g. the eyebrow base) lost their opacity map but keep alpha in the diffuse PNG.
        links.new(colour.outputs["Alpha"], bsdf.inputs["Alpha"])
    _set_render_method(material, "DITHERED")


def _eye_colour(nodes, links, image: bpy.types.Image, colour_out):
    """Recreate the two CC3 eye-shader adjustments the importer's missing maps used to provide.

    * Iris brightness: the CC3 shader brightens the iris; without it this brown
      iris renders nearly as dark as the pupil. The iris ring (between the
      pupil margin and the iris edge) is multiplied by ``IRIS_GAIN``; the pupil
      itself is left untouched, so it stays black.
    * Sclera tint: the pink base map is blended toward white outside the iris,
      as CC3 does with its (missing) sclera map.

    Both masks are radial distances in UV from the pupil centre, which is
    measured from the texture by ``pupil_in_texture``.
    """
    pupil_uv, pupil_radius = pupil_in_texture(image)
    coords = nodes.new("ShaderNodeTexCoord")
    centred = nodes.new("ShaderNodeVectorMath")
    centred.operation = "SUBTRACT"
    centred.inputs[1].default_value = (pupil_uv.x, pupil_uv.y, 0.0)
    distance = nodes.new("ShaderNodeVectorMath")
    distance.operation = "LENGTH"
    links.new(coords.outputs["UV"], centred.inputs[0])
    links.new(centred.outputs["Vector"], distance.inputs[0])

    def ramp(lo: float, hi: float, to_lo: float, to_hi: float):
        node = nodes.new("ShaderNodeMapRange")
        node.interpolation_type = "SMOOTHSTEP"
        node.inputs["From Min"].default_value = lo
        node.inputs["From Max"].default_value = hi
        node.inputs["To Min"].default_value = to_lo
        node.inputs["To Max"].default_value = to_hi
        links.new(distance.outputs["Value"], node.inputs["Value"])
        return node.outputs["Result"]

    # gain = 1 + (IRIS_GAIN - 1) * [outside pupil] * [inside iris]
    outside_pupil = ramp(pupil_radius, pupil_radius + PUPIL_EDGE_UV, 0.0, IRIS_GAIN - 1.0)
    inside_iris = ramp(IRIS_UV_RADIUS - 0.01, IRIS_UV_RADIUS + 0.01, 1.0, 0.0)
    ring = nodes.new("ShaderNodeMath")
    ring.operation = "MULTIPLY"
    links.new(outside_pupil, ring.inputs[0])
    links.new(inside_iris, ring.inputs[1])
    gain = nodes.new("ShaderNodeMath")
    gain.operation = "ADD"
    gain.inputs[1].default_value = 1.0
    links.new(ring.outputs["Value"], gain.inputs[0])
    brightened = nodes.new("ShaderNodeVectorMath")
    brightened.operation = "SCALE"
    links.new(colour_out, brightened.inputs[0])
    links.new(gain.outputs["Value"], brightened.inputs["Scale"])

    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MIX"
    mix.inputs["B"].default_value = (0.80, 0.76, 0.72, 1.0)
    links.new(ramp(IRIS_UV_RADIUS, IRIS_UV_RADIUS + 0.06, 0.0, 0.62), mix.inputs["Factor"])
    links.new(brightened.outputs["Vector"], mix.inputs["A"])
    return mix.outputs["Result"]


def rebuild_materials(objects: list[bpy.types.Object]) -> list[str]:
    """Rebuild every material that depends on a missing image, plus the eye and cornea; return their names.

    Every material ends up DITHERED: BLENDED transparency (the authored eye
    occlusion and tear line) is sorted on the GPU and made the same frame
    differ by one 8-bit level between runs.
    """
    rebuilt = []
    seen: set[str] = set()
    for obj in objects:
        if obj.type != "MESH":
            continue
        for material in obj.data.materials:
            if material is None or material.name in seen or material.node_tree is None:
                continue
            seen.add(material.name)
            _set_render_method(material, "DITHERED")
            images = _images_in(material.node_tree)
            kind = _material_kind(_base_name(material.name))
            if kind in ("eye", "cornea") or any(not _image_available(img) for img in images):
                _rebuild(material, images)
                rebuilt.append(material.name)
    return rebuilt


# --------------------------------------------------------------------------
# Size
# --------------------------------------------------------------------------

# Never seen by the locked camera (it frames the head), so they are stored small.
OFF_CAMERA_TEXTURE_LIMITS = {"Std_Skin_Arm": 512, "Std_Skin_Leg": 512, "Std_Nails": 256, "Std_Skin_Body": 1024}


def prune_shape_keys(objects: list[bpy.types.Object], keep_word: str = "Eye") -> int:
    """Drop the speech and expression shape keys (all at zero); keep the eye and lid keys.

    The beard and brow cards carry ~146 keys each, which is most of the file size.
    Returns the number of keys removed.
    """
    removed = 0
    for obj in objects:
        if obj.type != "MESH" or obj.data.shape_keys is None:
            continue
        blocks = obj.data.shape_keys.key_blocks
        if obj.data.shape_keys.animation_data is not None:
            obj.data.shape_keys.animation_data_clear()
        for block in list(blocks)[1:]:
            if keep_word not in block.name:
                if abs(block.value) > 1e-9:
                    raise CharacterAssetError(f"{obj.name}: shape key {block.name} is active ({block.value})")
                obj.shape_key_remove(block)
                removed += 1
        if len(obj.data.shape_keys.key_blocks) == 1:
            obj.shape_key_remove(obj.data.shape_keys.key_blocks[0])
    return removed


def disable_hair_card_shadows(objects: list[bpy.types.Object]) -> list[str]:
    """Hair, beard and brow cards receive light but do not cast shadows.

    Their dithered-alpha shadows are not reproducible on the GPU: the same pose
    rendered twice differed by one 8-bit level in a couple of pixels. Without
    them, renders are byte-identical between runs. Eyelashes are part of the
    body mesh and still cast shadows.
    """
    changed = []
    for obj in objects:
        materials = [m for m in getattr(obj.data, "materials", []) if m is not None]
        if obj.type == "MESH" and materials and all(_material_kind(_base_name(m.name)) == "hair" for m in materials):
            obj.visible_shadow = False
            changed.append(obj.name)
    return changed


LOOK_KEY_PREFIXES = ("A06_", "A07_", "A08_", "A09_", "A10_", "A11_", "A12_", "A13_")
LOOK_KEY_FULL_M = 0.030  # full strength within this height of the eyes
LOOK_KEY_ZERO_M = 0.045  # and none beyond this (the moustache starts about 58 mm below the eyes)


def localise_look_keys(objects: list[bpy.types.Object], eye_height_m: float) -> int:
    """Confine the eye-look (lid follow) keys to the band around the eyes.

    The Character Creator morphs carry tiny stray deltas far from the eyes (on
    the neck, and a few hundredths of a millimetre on the moustache cards).
    They are invisible as shapes, but on dithered hair cards they change the
    noise pattern, so gaze would alter pixels around the mouth. Real lid follow
    is local, so each key's deltas are faded to zero between 30 and 45 mm from
    eye height (measured in the rest pose; the posed head differs by < 1 cm).
    Returns the number of vertex deltas that were reduced.
    """
    changed = 0
    for obj in objects:
        if obj.type != "MESH" or obj.data.shape_keys is None:
            continue
        blocks = obj.data.shape_keys.key_blocks
        basis = blocks[0].data
        heights = [(obj.matrix_world @ point.co).z for point in basis]
        weights = [min(1.0, max(0.0, (LOOK_KEY_ZERO_M - abs(z - eye_height_m)) / (LOOK_KEY_ZERO_M - LOOK_KEY_FULL_M)))
                   for z in heights]
        for block in blocks[1:]:
            if not block.name.startswith(LOOK_KEY_PREFIXES):
                continue
            for index, weight in enumerate(weights):
                if weight < 1.0:
                    rest = basis[index].co
                    delta = block.data[index].co - rest
                    if delta.length_squared > 0.0:
                        block.data[index].co = rest + delta * weight
                        changed += 1
    return changed


def downscale_off_camera_textures() -> list[str]:
    """Shrink packed textures used only on parts of the body the camera cannot see."""
    changed = []
    for image in bpy.data.images:
        limit = next((size for prefix, size in OFF_CAMERA_TEXTURE_LIMITS.items() if image.name.startswith(prefix)), None)
        if limit is None or image.packed_file is None or max(image.size) <= limit:
            continue
        image.scale(limit, limit)
        image.pack()
        changed.append(f"{image.name}->{limit}")
    return changed


# --------------------------------------------------------------------------
# Eyes
# --------------------------------------------------------------------------

def eye_source_object(rig: bpy.types.Object) -> bpy.types.Object:
    for obj in rig.children:
        if obj.type == "MESH" and any(m and m.name.startswith(CORNEA_MATERIAL_PREFIX) for m in obj.data.materials):
            return obj
    raise CharacterAssetError("No eyeball mesh (with Std_Cornea materials) under the face rig")


def _side_of(material_name: str) -> str | None:
    base = _base_name(material_name)
    for prefix in (EYE_MATERIAL_PREFIX, CORNEA_MATERIAL_PREFIX):
        if base.startswith(prefix):
            tail = base[len(prefix):]
            if tail in ("L", "R"):
                return tail
    return None


def bake_eye_meshes(rig: bpy.types.Object) -> dict[str, bpy.types.Mesh]:
    """Posed eyeballs as two world-space meshes (metres), one per side, modifiers applied."""
    source = eye_source_object(rig)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = source.evaluated_get(depsgraph)
    baked = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
    baked.transform(source.matrix_world)
    meshes = {}
    for side in ("L", "R"):
        # Only the eyeball itself is kept. The separate cornea shell needed partially transparent
        # shading, which EEVEE can only dither (grainy catchlights) or sort (not reproducible);
        # the eyeball material carries a clear coat instead, which gives the same wet highlights.
        keep_slots = [i for i, m in enumerate(baked.materials)
                      if m is not None and _side_of(m.name) == side and _base_name(m.name).startswith(EYE_MATERIAL_PREFIX)]
        bm = bmesh.new()
        bm.from_mesh(baked)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index not in keep_slots], context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
        remap = {old: new for new, old in enumerate(keep_slots)}
        for face in bm.faces:
            face.material_index = remap[face.material_index]
        mesh = bpy.data.meshes.new(f"Eye_{side}")
        bm.to_mesh(mesh)
        bm.free()
        for slot in keep_slots:
            mesh.materials.append(baked.materials[slot])
        meshes[side] = mesh
    bpy.data.meshes.remove(baked)
    bpy.data.objects.remove(source)
    return meshes


def _inner_material_indices(mesh: bpy.types.Mesh) -> set[int]:
    return {i for i, m in enumerate(mesh.materials) if m is not None and _base_name(m.name).startswith(EYE_MATERIAL_PREFIX)}


def iris_texture(mesh: bpy.types.Mesh) -> bpy.types.Image:
    for index in _inner_material_indices(mesh):
        for node in mesh.materials[index].node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image is not None:
                return node.image
    raise CharacterAssetError(f"{mesh.name}: eyeball material has no iris texture")


def pupil_in_texture(image: bpy.types.Image) -> tuple[Vector, float]:
    """Pupil centre (UV) and radius (UV units), measured from the dark disc in the iris texture."""
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    rgb = pixels.reshape(height, width, 4)[:, :, :3]
    rows, columns = np.mgrid[0:height, 0:width]
    u, v = (columns + 0.5) / width, (rows + 0.5) / height  # foreach_get rows run bottom-up, like UV v
    near_centre = (u - 0.5) ** 2 + (v - 0.5) ** 2 < 0.1 ** 2
    dark = near_centre & (rgb.mean(axis=2) < PUPIL_DARK_LUMINANCE)
    count = int(dark.sum())
    if count < 50:
        raise CharacterAssetError(f"{image.name}: no dark pupil disc near the texture centre")
    return Vector((float(u[dark].mean()), float(v[dark].mean()))), sqrt(count / pi) / width


def _uv_to_surface(mesh: bpy.types.Mesh, uv_point: Vector) -> Vector:
    """3D point on the inner eyeball whose texture coordinate is ``uv_point``."""
    uv_layer = mesh.uv_layers.active.data
    inner = _inner_material_indices(mesh)
    mesh.calc_loop_triangles()
    target = Vector((uv_point.x, uv_point.y, 0.0))
    for tri in mesh.loop_triangles:
        if tri.material_index not in inner:
            continue
        uvs = [Vector((*uv_layer[loop].uv, 0.0)) for loop in tri.loops]
        if intersect_point_tri_2d(uv_point, uvs[0].xy, uvs[1].xy, uvs[2].xy):
            cos_ = [mesh.vertices[i].co for i in tri.vertices]
            return barycentric_transform(target, *uvs, *cos_)
    raise CharacterAssetError(f"{mesh.name}: UV {tuple(uv_point)} is not on the eyeball")


def sclera_sphere(mesh: bpy.types.Mesh, pupil_uv: Vector) -> tuple[Vector, float, float]:
    """Least-squares sphere through the sclera vertices: centre, radius, worst residual (m)."""
    uv_layer = mesh.uv_layers.active.data
    inner = _inner_material_indices(mesh)
    vertex_uv: dict[int, Vector] = {}
    for polygon in mesh.polygons:
        if polygon.material_index in inner:
            for loop_index, vertex_index in zip(polygon.loop_indices, polygon.vertices):
                vertex_uv.setdefault(vertex_index, Vector(uv_layer[loop_index].uv))
    points = np.array([mesh.vertices[i].co[:] for i, uv in vertex_uv.items()
                       if (uv - pupil_uv).length > SCLERA_UV_MIN_RADIUS])
    if len(points) < 20:
        raise CharacterAssetError(f"{mesh.name}: too few sclera vertices to fit a sphere")
    a = np.c_[2.0 * points, np.ones(len(points))]
    b = (points ** 2).sum(axis=1)
    x = np.linalg.lstsq(a, b, rcond=None)[0]
    centre = x[:3]
    radius = float(np.sqrt(x[3] + centre @ centre))
    residual = float(np.abs(np.linalg.norm(points - centre, axis=1) - radius).max())
    return Vector(centre.tolist()), radius, residual


def align_optical_axis(mesh: bpy.types.Mesh, centre: Vector, pupil_point: Vector) -> float:
    """Rotate the eyeball about ``centre`` so centre -> pupil points along world -Y; return the correction (rad)."""
    rotation = (pupil_point - centre).normalized().rotation_difference(Vector((0.0, -1.0, 0.0)))
    transform = Matrix.Translation(centre) @ rotation.to_matrix().to_4x4() @ Matrix.Translation(-centre)
    mesh.transform(transform)
    return rotation.angle


def pupil_ring_points(mesh: bpy.types.Mesh, pupil_uv: Vector, radius_uv: float, segments: int = 32) -> tuple[Vector, list[Vector]]:
    """The pupil centre and its margin, as points on the eyeball surface (mesh coordinates)."""
    centre = _uv_to_surface(mesh, pupil_uv)
    ring = [_uv_to_surface(mesh, pupil_uv + radius_uv * Vector((cos(2 * pi * k / segments), sin(2 * pi * k / segments))))
            for k in range(segments)]
    return centre, ring
