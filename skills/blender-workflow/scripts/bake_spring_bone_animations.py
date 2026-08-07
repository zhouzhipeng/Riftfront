"""Bake deterministic secondary-motion bone animation and export animation GLBs.

This module is intended to run inside Blender. The public entry point is
``run_with_arguments`` so it can be invoked through Blender Foundation's
official MCP ``execute_blender_code_for_cli`` tool.

The recipe owns asset-specific action names, spring chains, colliders, and
root-motion policy. Physics is evaluated offline and written back as ordinary
pose-bone quaternion keyframes, which makes the result portable to glTF/GLB.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree


GLB_MAGIC = b"glTF"
GLB_VERSION = 2
GLB_JSON_CHUNK = 0x4E4F534A
EPSILON = 1.0e-9


class SpringBakeError(RuntimeError):
    """Raised when the bake cannot produce a verified result."""


@dataclass(frozen=True)
class ChainConfig:
    name: str
    bones: tuple[str, ...]
    damping: float
    stiffness: float
    gravity: Vector
    max_angle_radians: float
    collision_margin: float
    collision_point_count: int
    collision_start_point: int
    maximum_proxy_penetration: float
    collision_guide: Vector | None
    collision_guide_weight: float


@dataclass(frozen=True)
class ColliderConfig:
    name: str
    kind: str
    bone: str
    radius_a: float
    radius_b: float
    local_a: Vector
    local_b: Vector | None
    chains: frozenset[str]


@dataclass(frozen=True)
class ChestJiggleConfig:
    bones: tuple[str, ...]
    driver_bone: str
    axis_local: Vector
    response_radians_per_acceleration: float
    forward_response: float
    stiffness: float
    damping: float
    max_angle_radians: float
    action_gains: dict[str, float]


@dataclass(frozen=True)
class MeshCollisionValidationConfig:
    armature: str
    hair_mesh: str
    obstacles: tuple[str, ...]
    vertex_groups: tuple[str, ...]
    minimum_weight: float
    epsilon: float


def _parse_arguments(arguments: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bake spring-bone animation and export one GLB per action."
    )
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--output-blend", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--action",
        action="append",
        dest="actions",
        help="Bake only this recipe action; repeat to select multiple actions.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing the requested output blend or output GLBs.",
    )
    return parser.parse_args(list(arguments))


def _load_recipe(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SpringBakeError(f"Cannot read recipe {path}: {error}") from error
    if not isinstance(data, dict) or data.get("version") != 1:
        raise SpringBakeError("Spring-bone recipe must be a version-1 JSON object")
    return data


def _absolute_path(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve()


def _iter_action_fcurves(action: Any) -> list[Any]:
    curves: list[Any] = []
    seen: set[int] = set()
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        try:
            for curve in legacy:
                pointer = curve.as_pointer()
                if pointer not in seen:
                    seen.add(pointer)
                    curves.append(curve)
        except (AttributeError, TypeError):
            pass
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for channelbag in getattr(strip, "channelbags", []):
                for curve in channelbag.fcurves:
                    pointer = curve.as_pointer()
                    if pointer not in seen:
                        seen.add(pointer)
                        curves.append(curve)
    return curves


def _curve_map(action: Any) -> dict[tuple[str, int], Any]:
    return {
        (curve.data_path, int(curve.array_index)): curve
        for curve in _iter_action_fcurves(action)
    }


def _assign_action(armature: Any, action: Any) -> None:
    """Assign an action and its Blender 4.4+ slot to an armature."""
    armature.animation_data_create()
    animation_data = armature.animation_data
    animation_data.action = action
    slots = list(getattr(action, "slots", []))
    if slots:
        current_slot = getattr(animation_data, "action_slot", None)
        if current_slot not in slots:
            animation_data.action_slot = slots[0]


def _reset_pose_to_rest(armature: Any) -> None:
    """Remove unkeyed pose state left behind by a previously evaluated action."""
    if armature.animation_data is not None:
        armature.animation_data.action = None
    identity = Matrix.Identity(4)
    for pose_bone in armature.pose.bones:
        pose_bone.matrix_basis = identity
    bpy.context.view_layer.update()


def _set_curve_constant(curve: Any, value: float) -> None:
    for key in curve.keyframe_points:
        key.co[1] = value
        key.handle_left[1] = value
        key.handle_right[1] = value
        key.interpolation = "LINEAR"
    curve.update()


def _replace_curve_samples(
    curve: Any,
    samples: dict[int, float],
    frame_start: int,
    frame_end: int,
) -> None:
    keys_by_frame = {
        int(round(float(key.co[0]))): key for key in curve.keyframe_points
    }
    missing = [
        frame for frame in range(frame_start, frame_end + 1) if frame not in keys_by_frame
    ]
    if missing:
        raise SpringBakeError(
            f"Curve {curve.data_path}[{curve.array_index}] has no per-frame keys at "
            f"{missing[:8]}"
        )
    for frame, value in samples.items():
        key = keys_by_frame[frame]
        key.co[1] = float(value)
        key.handle_left[1] = float(value)
        key.handle_right[1] = float(value)
        key.interpolation = "LINEAR"
    curve.update()


def _canonical_root_values(
    reference_action: Any,
    root_bone: str,
    frame: int,
) -> dict[tuple[str, int], float]:
    prefix = f'pose.bones["{root_bone}"].'
    values: dict[tuple[str, int], float] = {}
    for curve in _iter_action_fcurves(reference_action):
        if not curve.data_path.startswith(prefix):
            continue
        property_name = curve.data_path[len(prefix) :]
        if property_name not in {
            "location",
            "rotation_quaternion",
            "rotation_euler",
            "rotation_axis_angle",
        }:
            continue
        values[(property_name, int(curve.array_index))] = float(curve.evaluate(frame))
    if not any(name == "location" for name, _ in values):
        raise SpringBakeError(
            f"Reference action {reference_action.name!r} has no location curves for "
            f"root bone {root_bone!r}"
        )
    return values


def _remove_root_motion(
    action: Any,
    root_bone: str,
    canonical_values: dict[tuple[str, int], float],
) -> dict[str, float]:
    curves = _curve_map(action)
    applied: dict[str, float] = {}
    for (property_name, array_index), value in canonical_values.items():
        data_path = f'pose.bones["{root_bone}"].{property_name}'
        curve = curves.get((data_path, array_index))
        if curve is None:
            continue
        _set_curve_constant(curve, value)
        applied[f"{property_name}[{array_index}]"] = value

    # Also neutralize armature-object transform channels if an input action has
    # them. The canonical target actions normally contain pose-bone channels only.
    for property_name, neutral in (
        ("location", (0.0, 0.0, 0.0)),
        ("rotation_euler", (0.0, 0.0, 0.0)),
        ("rotation_quaternion", (1.0, 0.0, 0.0, 0.0)),
        ("rotation_axis_angle", (0.0, 0.0, 1.0, 0.0)),
    ):
        for array_index, value in enumerate(neutral):
            curve = curves.get((property_name, array_index))
            if curve is not None:
                _set_curve_constant(curve, value)
                applied[f"object.{property_name}[{array_index}]"] = value
    return applied


def _parse_chain_configs(recipe: dict[str, Any], armature: Any) -> list[ChainConfig]:
    records = recipe.get("chains")
    if not isinstance(records, list) or not records:
        raise SpringBakeError("Recipe must define at least one spring chain")
    chains: list[ChainConfig] = []
    claimed: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise SpringBakeError(f"Chain {index} must be an object")
        bones_value = record.get("bones")
        if not isinstance(bones_value, list) or not bones_value:
            raise SpringBakeError(f"Chain {index} must contain a non-empty bones array")
        bones = tuple(str(name) for name in bones_value)
        missing = [name for name in bones if armature.pose.bones.get(name) is None]
        if missing:
            raise SpringBakeError(f"Chain {index} references missing bones: {missing}")
        duplicates = sorted(set(bones) & claimed)
        if duplicates:
            raise SpringBakeError(f"Bones occur in more than one chain: {duplicates}")
        claimed.update(bones)
        gravity_value = record.get("gravity", [0.0, 0.0, -1.0])
        if not isinstance(gravity_value, list) or len(gravity_value) != 3:
            raise SpringBakeError(f"Chain {index} gravity must contain three numbers")
        max_angle = float(record.get("maxAngleDegrees", 45.0))
        collision_point_count = int(record.get("collisionPointCount", len(bones)))
        collision_start_point = int(record.get("collisionStartPoint", 1))
        maximum_proxy_penetration = float(
            record.get("maximumProxyPenetration", 0.012)
        )
        if collision_point_count < 1 or collision_point_count > len(bones):
            raise SpringBakeError(
                f"Chain {index} collisionPointCount must be between 1 and "
                f"{len(bones)}"
            )
        if collision_start_point < 1 or collision_start_point > collision_point_count:
            raise SpringBakeError(
                f"Chain {index} collisionStartPoint must be between 1 and "
                f"collisionPointCount"
            )
        if (
            not math.isfinite(maximum_proxy_penetration)
            or maximum_proxy_penetration < 0.0
        ):
            raise SpringBakeError(
                f"Chain {index} maximumProxyPenetration must be finite and non-negative"
            )
        guide_value = record.get("collisionGuide")
        collision_guide = None
        if guide_value is not None:
            if not isinstance(guide_value, list) or len(guide_value) != 3:
                raise SpringBakeError(
                    f"Chain {index} collisionGuide must contain three numbers"
                )
            collision_guide = Vector(tuple(float(value) for value in guide_value))
            if collision_guide.length_squared <= EPSILON:
                raise SpringBakeError(f"Chain {index} collisionGuide cannot be zero")
            collision_guide.normalize()
        chains.append(
            ChainConfig(
                name=str(record.get("name", bones[0])),
                bones=bones,
                damping=float(record.get("damping", 0.88)),
                stiffness=float(record.get("stiffness", 0.15)),
                gravity=Vector(tuple(float(v) for v in gravity_value)),
                max_angle_radians=math.radians(max_angle),
                collision_margin=float(record.get("collisionMargin", 0.0)),
                collision_point_count=collision_point_count,
                collision_start_point=collision_start_point,
                maximum_proxy_penetration=maximum_proxy_penetration,
                collision_guide=collision_guide,
                collision_guide_weight=float(record.get("collisionGuideWeight", 0.75)),
            )
        )
    return chains


def _to_local_point(rest_bone: Any, point: Sequence[float]) -> Vector:
    if len(point) != 3:
        raise SpringBakeError("Collider rest point must contain three numbers")
    return rest_bone.matrix_local.inverted() @ Vector(tuple(float(v) for v in point))


def _parse_colliders(recipe: dict[str, Any], armature: Any) -> list[ColliderConfig]:
    records = recipe.get("colliders", [])
    if not isinstance(records, list):
        raise SpringBakeError("Recipe colliders must be an array")
    colliders: list[ColliderConfig] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise SpringBakeError(f"Collider {index} must be an object")
        kind = str(record.get("type", "sphere")).lower()
        if kind not in {"sphere", "capsule"}:
            raise SpringBakeError(f"Unsupported collider type: {kind}")
        bone_name = str(record.get("bone", ""))
        rest_bone = armature.data.bones.get(bone_name)
        if rest_bone is None:
            raise SpringBakeError(f"Collider {index} references missing bone {bone_name!r}")
        radius_a = float(record.get("radiusA", record.get("radius", 0.0)))
        radius_b = float(record.get("radiusB", radius_a))
        if (
            not math.isfinite(radius_a)
            or not math.isfinite(radius_b)
            or radius_a <= 0.0
            or radius_b <= 0.0
        ):
            raise SpringBakeError(f"Collider {index} radii must be positive")
        point_a = record.get("center") if kind == "sphere" else record.get("a")
        point_b = record.get("b") if kind == "capsule" else None
        if kind == "capsule" and (not isinstance(point_a, list) or not isinstance(point_b, list)):
            center_value = record.get("center")
            axis_value = record.get("axis")
            length = float(record.get("length", 0.0))
            if (
                not isinstance(center_value, list)
                or len(center_value) != 3
                or not isinstance(axis_value, list)
                or len(axis_value) != 3
                or length <= 0.0
            ):
                raise SpringBakeError(
                    f"Capsule {index} needs a/b or center/axis/length"
                )
            center = Vector(tuple(float(value) for value in center_value))
            axis = Vector(tuple(float(value) for value in axis_value))
            if axis.length_squared <= EPSILON:
                raise SpringBakeError(f"Capsule {index} axis cannot be zero")
            half_axis = axis.normalized() * (length * 0.5)
            point_a = list(center - half_axis)
            point_b = list(center + half_axis)
        if not isinstance(point_a, list):
            raise SpringBakeError(f"Collider {index} is missing its first rest point")
        local_a = _to_local_point(rest_bone, point_a)
        local_b = None
        if kind == "capsule":
            if not isinstance(point_b, list):
                raise SpringBakeError(f"Capsule {index} is missing rest point b")
            local_b = _to_local_point(rest_bone, point_b)
        chain_filter = record.get("chains", [])
        if not isinstance(chain_filter, list):
            raise SpringBakeError(f"Collider {index} chains must be an array")
        colliders.append(
            ColliderConfig(
                name=str(record.get("name", f"collider_{index}")),
                kind=kind,
                bone=bone_name,
                radius_a=radius_a,
                radius_b=radius_b,
                local_a=local_a,
                local_b=local_b,
                chains=frozenset(str(name) for name in chain_filter),
            )
        )
    return colliders


def _parse_chest_jiggle(
    recipe: dict[str, Any], armature: Any
) -> ChestJiggleConfig | None:
    record = recipe.get("chestJiggle")
    if record is None:
        return None
    if not isinstance(record, dict):
        raise SpringBakeError("Recipe chestJiggle must be an object")
    bones_value = record.get("bones")
    if not isinstance(bones_value, list) or not bones_value:
        raise SpringBakeError("chestJiggle bones must be a non-empty array")
    bones = tuple(str(name) for name in bones_value)
    driver_bone = str(record.get("driverBone", ""))
    missing = [
        name
        for name in (*bones, driver_bone)
        if not name or armature.pose.bones.get(name) is None
    ]
    if missing:
        raise SpringBakeError(f"chestJiggle references missing bones: {missing}")
    axis_value = record.get("axisLocal", [1.0, 0.0, 0.0])
    if not isinstance(axis_value, list) or len(axis_value) != 3:
        raise SpringBakeError("chestJiggle axisLocal must contain three numbers")
    axis = Vector(tuple(float(value) for value in axis_value))
    if axis.length_squared <= EPSILON:
        raise SpringBakeError("chestJiggle axisLocal cannot be zero")
    gains_value = record.get("actionGains", {})
    if not isinstance(gains_value, dict):
        raise SpringBakeError("chestJiggle actionGains must be an object")
    return ChestJiggleConfig(
        bones=bones,
        driver_bone=driver_bone,
        axis_local=axis.normalized(),
        response_radians_per_acceleration=math.radians(
            float(record.get("responseDegreesPerAcceleration", 0.75))
        ),
        forward_response=float(record.get("forwardResponse", 0.35)),
        stiffness=float(record.get("stiffness", 0.32)),
        damping=float(record.get("damping", 0.68)),
        max_angle_radians=math.radians(float(record.get("maxAngleDegrees", 3.5))),
        action_gains={str(name): float(value) for name, value in gains_value.items()},
    )


def _parse_mesh_collision_validation(
    recipe: dict[str, Any],
) -> MeshCollisionValidationConfig | None:
    record = recipe.get("meshCollisionValidation")
    if record is None:
        return None
    if not isinstance(record, dict):
        raise SpringBakeError("meshCollisionValidation must be an object")
    armature_name = str(record.get("armature", ""))
    hair_name = str(record.get("hairMesh", ""))
    obstacle_names = tuple(str(name) for name in record.get("obstacles", []))
    group_names = tuple(str(name) for name in record.get("vertexGroups", []))
    armature = bpy.data.objects.get(armature_name)
    hair = bpy.data.objects.get(hair_name)
    if armature is None or armature.type != "ARMATURE":
        raise SpringBakeError(
            f"Mesh collision validation armature {armature_name!r} was not found"
        )
    if hair is None or hair.type != "MESH":
        raise SpringBakeError(
            f"Mesh collision validation hair mesh {hair_name!r} was not found"
        )
    if not obstacle_names or not group_names:
        raise SpringBakeError(
            "Mesh collision validation needs obstacles and vertexGroups"
        )
    missing_obstacles = [
        name
        for name in obstacle_names
        if bpy.data.objects.get(name) is None
        or bpy.data.objects[name].type != "MESH"
    ]
    missing_groups = [name for name in group_names if hair.vertex_groups.get(name) is None]
    if missing_obstacles or missing_groups:
        raise SpringBakeError(
            "Mesh collision validation references missing data: "
            f"obstacles={missing_obstacles}, groups={missing_groups}"
        )
    minimum_weight = float(record.get("minimumWeight", 0.25))
    epsilon = float(record.get("epsilon", 0.00005))
    if minimum_weight < 0.0 or epsilon < 0.0:
        raise SpringBakeError(
            "Mesh collision validation minimumWeight and epsilon cannot be negative"
        )
    return MeshCollisionValidationConfig(
        armature=armature_name,
        hair_mesh=hair_name,
        obstacles=obstacle_names,
        vertex_groups=group_names,
        minimum_weight=minimum_weight,
        epsilon=epsilon,
    )


def _colliders_for_chain(
    colliders: Sequence[ColliderConfig], chain_name: str
) -> list[ColliderConfig]:
    return [
        collider
        for collider in colliders
        if not collider.chains or chain_name in collider.chains
    ]


def _evaluated_colliders(
    armature: Any, colliders: Sequence[ColliderConfig]
) -> list[tuple[str, Vector, Vector | None, float, float]]:
    evaluated: list[tuple[str, Vector, Vector | None, float, float]] = []
    for collider in colliders:
        matrix = armature.pose.bones[collider.bone].matrix
        point_a = matrix @ collider.local_a
        point_b = matrix @ collider.local_b if collider.local_b is not None else None
        evaluated.append(
            (collider.kind, point_a, point_b, collider.radius_a, collider.radius_b)
        )
    return evaluated


def _closest_point_and_factor(
    point: Vector, a: Vector, b: Vector
) -> tuple[Vector, float]:
    segment = b - a
    length_squared = segment.length_squared
    if length_squared <= EPSILON:
        return a.copy(), 0.0
    factor = max(0.0, min(1.0, (point - a).dot(segment) / length_squared))
    return a + segment * factor, factor


def _closest_point_on_segment(point: Vector, a: Vector, b: Vector) -> Vector:
    return _closest_point_and_factor(point, a, b)[0]


def _push_out_of_colliders(
    point: Vector,
    colliders: Sequence[tuple[str, Vector, Vector | None, float, float]],
    margin: float,
    fallback_direction: Vector,
) -> Vector:
    output = point.copy()
    # Proxies overlap around the shoulders, skirt, and thighs.  Repeated sweeps
    # project a point out of their intersection instead of allowing a later
    # collider to push it back inside an earlier one.
    for _sweep in range(6):
        changed = False
        for kind, point_a, point_b, radius_a, radius_b in colliders:
            if kind == "sphere" or point_b is None:
                center = point_a
                radius = radius_a
            else:
                center, factor = _closest_point_and_factor(output, point_a, point_b)
                radius = radius_a + (radius_b - radius_a) * factor
            difference = output - center
            minimum_distance = radius + margin
            if difference.length_squared >= minimum_distance * minimum_distance:
                continue
            if difference.length_squared <= EPSILON:
                difference = fallback_direction.normalized()
                if difference.length_squared <= EPSILON:
                    difference = Vector((0.0, -1.0, 0.0))
            output = center + difference.normalized() * minimum_distance
            changed = True
        if not changed:
            break
    return output


def _collider_clearance(
    point: Vector,
    collider: tuple[str, Vector, Vector | None, float, float],
    margin: float,
) -> float:
    kind, point_a, point_b, radius_a, radius_b = collider
    if kind == "sphere" or point_b is None:
        center = point_a
        radius = radius_a
    else:
        center, factor = _closest_point_and_factor(point, point_a, point_b)
        radius = radius_a + (radius_b - radius_a) * factor
    return (point - center).length - radius - margin


def _minimum_collider_clearance(
    point: Vector,
    colliders: Sequence[tuple[str, Vector, Vector | None, float, float]],
    margin: float,
) -> float:
    if not colliders:
        return math.inf
    return min(_collider_clearance(point, collider, margin) for collider in colliders)


def _fixed_length_collision_candidate(
    anchor: Vector,
    candidate: Vector,
    length: float,
    colliders: Sequence[tuple[str, Vector, Vector | None, float, float]],
    margin: float,
    fallback_direction: Vector,
    guide_direction: Vector | None,
    guide_weight: float,
) -> Vector:
    """Keep an endpoint at a fixed length while finding collision-free direction."""
    constrained = candidate.copy()
    for _projection in range(10):
        constrained = _push_out_of_colliders(
            constrained,
            colliders,
            margin,
            fallback_direction,
        )
        direction = constrained - anchor
        if direction.length_squared <= EPSILON:
            direction = fallback_direction
        constrained = anchor + direction.normalized() * length
        if _minimum_collider_clearance(constrained, colliders, margin) >= -1.0e-6:
            return constrained

    # Alternating projections can settle in a local dead end where the endpoint
    # is repeatedly pushed out and pulled back by the fixed-length constraint.
    # Search deterministic concentric cones around the preferred direction and
    # select the smallest collision-free deviation.
    preferred = candidate - anchor
    if preferred.length_squared <= EPSILON:
        preferred = fallback_direction.copy()
    preferred.normalize()
    tangent_a = preferred.orthogonal().normalized()
    tangent_b = preferred.cross(tangent_a).normalized()
    best_point = constrained
    best_clearance = _minimum_collider_clearance(best_point, colliders, margin)
    best_valid_point: Vector | None = None
    best_valid_score = -math.inf
    for angle_degrees in range(0, 181, 5):
        angle = math.radians(angle_degrees)
        cosine = math.cos(angle)
        sine = math.sin(angle)
        azimuth_steps = 1 if angle_degrees in {0, 180} else 24
        for azimuth_index in range(azimuth_steps):
            azimuth = math.tau * azimuth_index / azimuth_steps
            direction = (
                preferred * cosine
                + tangent_a * (sine * math.cos(azimuth))
                + tangent_b * (sine * math.sin(azimuth))
            ).normalized()
            point = anchor + direction * length
            clearance = _minimum_collider_clearance(point, colliders, margin)
            if clearance > best_clearance:
                best_clearance = clearance
                best_point = point
            if clearance >= -1.0e-6:
                score = preferred.dot(direction)
                if guide_direction is not None:
                    score += guide_weight * guide_direction.dot(direction)
                score += min(clearance, 0.05)
                if score > best_valid_score:
                    best_valid_score = score
                    best_valid_point = point
    if best_valid_point is not None:
        return best_valid_point
    return best_point


def _validate_action_collisions(
    armature: Any,
    action: Any,
    chains: Sequence[ChainConfig],
    colliders: Sequence[ColliderConfig],
    frame_start: int,
    frame_end: int,
) -> dict[str, Any]:
    _assign_action(armature, action)
    minimum_clearance = math.inf
    minimum_record: dict[str, Any] | None = None
    maximum_tolerance_excess = -math.inf
    violation_record: dict[str, Any] | None = None
    for frame in range(frame_start, frame_end + 1):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for chain in chains:
            chain_colliders = _colliders_for_chain(colliders, chain.name)
            evaluated = _evaluated_colliders(armature, chain_colliders)
            points, _matrices = _chain_base_data(armature, chain)
            # Point zero is the kinematic chain anchor embedded in the scalp.
            weighted_points = points[
                chain.collision_start_point : chain.collision_point_count + 1
            ]
            for point_index, point in enumerate(
                weighted_points, start=chain.collision_start_point
            ):
                for collider_index, collider in enumerate(evaluated):
                    clearance = _collider_clearance(
                        point, collider, chain.collision_margin
                    )
                    if clearance < minimum_clearance:
                        minimum_clearance = clearance
                        minimum_record = {
                            "frame": frame,
                            "chain": chain.name,
                            "pointIndex": point_index,
                            "collider": chain_colliders[collider_index].name,
                            "clearance": clearance,
                        }
                    tolerance_excess = -clearance - chain.maximum_proxy_penetration
                    if tolerance_excess > maximum_tolerance_excess:
                        maximum_tolerance_excess = tolerance_excess
                        violation_record = {
                            "frame": frame,
                            "chain": chain.name,
                            "pointIndex": point_index,
                            "collider": chain_colliders[collider_index].name,
                            "clearance": clearance,
                            "allowedPenetration": chain.maximum_proxy_penetration,
                        }
    if minimum_record is None:
        return {"minimumClearance": None, "minimum": None}
    if maximum_tolerance_excess > 1.0e-6:
        raise SpringBakeError(
            "Hair control point penetrated a collision proxy after baking: "
            f"{violation_record}"
        )
    return {
        "minimumClearance": minimum_clearance,
        "minimum": minimum_record,
        "maximumToleranceExcess": maximum_tolerance_excess,
    }


def _evaluated_mesh_bvh(
    obj: Any,
    epsilon: float,
    polygon_indices: set[int] | None = None,
) -> tuple[BVHTree, int]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        world = evaluated.matrix_world.copy()
        vertices = [world @ vertex.co for vertex in mesh.vertices]
        polygons = [
            tuple(polygon.vertices)
            for polygon in mesh.polygons
            if polygon_indices is None or polygon.index in polygon_indices
        ]
        if not polygons:
            raise SpringBakeError(
                f"Mesh collision validation selected no polygons from {obj.name!r}"
            )
        tree = BVHTree.FromPolygons(
            vertices,
            polygons,
            all_triangles=False,
            epsilon=epsilon,
        )
    finally:
        evaluated.to_mesh_clear()
    return tree, len(polygons)


def _validate_mesh_collisions(
    action: Any,
    config: MeshCollisionValidationConfig | None,
    frame_start: int,
    frame_end: int,
) -> dict[str, Any]:
    if config is None:
        return {"enabled": False, "framesChecked": 0, "maximumOverlaps": 0}
    armature = bpy.data.objects[config.armature]
    hair = bpy.data.objects[config.hair_mesh]
    obstacles = [bpy.data.objects[name] for name in config.obstacles]
    _reset_pose_to_rest(armature)
    _make_armature_exportable(armature)
    _assign_action(armature, action)
    for obj in (hair, *obstacles):
        for collection in obj.users_collection:
            collection.hide_viewport = False
        obj.hide_set(False)
        obj.hide_viewport = False

    group_indices = {
        hair.vertex_groups[name].index for name in config.vertex_groups
    }
    selected_polygons: set[int] = set()
    for polygon in hair.data.polygons:
        maximum_weight = 0.0
        for vertex_index in polygon.vertices:
            for membership in hair.data.vertices[vertex_index].groups:
                if membership.group in group_indices:
                    maximum_weight = max(maximum_weight, float(membership.weight))
        if maximum_weight > config.minimum_weight:
            selected_polygons.add(int(polygon.index))
    if not selected_polygons:
        raise SpringBakeError(
            f"Mesh collision validation selected no polygons from {hair.name!r}"
        )

    maximum_overlaps = 0
    checks = 0
    for frame in range(frame_start, frame_end + 1):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        hair_tree, polygon_count = _evaluated_mesh_bvh(
            hair, config.epsilon, selected_polygons
        )
        for obstacle in obstacles:
            obstacle_tree, _obstacle_polygon_count = _evaluated_mesh_bvh(
                obstacle, config.epsilon
            )
            overlaps = len(hair_tree.overlap(obstacle_tree))
            maximum_overlaps = max(maximum_overlaps, overlaps)
            checks += 1
            if overlaps:
                raise SpringBakeError(
                    "Baked hair mesh intersects character geometry: "
                    f"action={action.name!r}, frame={frame}, "
                    f"hair={hair.name!r}, obstacle={obstacle.name!r}, "
                    f"overlappingTriangles={overlaps}"
                )
    return {
        "enabled": True,
        "framesChecked": frame_end - frame_start + 1,
        "obstacleChecks": checks,
        "hairPolygonsChecked": polygon_count,
        "maximumOverlaps": maximum_overlaps,
    }


def _chain_base_data(armature: Any, chain: ChainConfig) -> tuple[list[Vector], list[Matrix]]:
    matrices = [armature.pose.bones[name].matrix.copy() for name in chain.bones]
    points = [matrix.translation.copy() for matrix in matrices]
    last_bone = armature.data.bones[chain.bones[-1]]
    points.append(matrices[-1] @ Vector((0.0, float(last_bone.length), 0.0)))
    return points, matrices


def _clamp_direction(direction: Vector, rest_direction: Vector, max_angle: float) -> Vector:
    if direction.length_squared <= EPSILON or rest_direction.length_squared <= EPSILON:
        return rest_direction.normalized()
    current = direction.normalized()
    rest = rest_direction.normalized()
    dot = max(-1.0, min(1.0, rest.dot(current)))
    angle = math.acos(dot)
    if angle <= max_angle:
        return current
    axis = rest.cross(current)
    if axis.length_squared <= EPSILON:
        axis = rest.orthogonal()
    return Quaternion(axis.normalized(), max_angle) @ rest


def _simulate_step(
    positions: list[Vector],
    previous: list[Vector],
    base_points: Sequence[Vector],
    lengths: Sequence[float],
    chain: ChainConfig,
    colliders: Sequence[tuple[str, Vector, Vector | None, float, float]],
    dt: float,
    substeps: int,
    constraint_iterations: int,
) -> None:
    sub_dt_squared = (dt / substeps) ** 2
    stiffness = max(0.0, min(1.0, chain.stiffness))
    stiffness_per_iteration = 1.0 - (1.0 - stiffness) ** (
        1.0 / (substeps * constraint_iterations)
    )
    for _substep in range(substeps):
        positions[0] = base_points[0].copy()
        previous[0] = base_points[0].copy()
        for index in range(1, len(positions)):
            current = positions[index].copy()
            velocity = (positions[index] - previous[index]) * chain.damping
            previous[index] = current
            positions[index] = current + velocity + chain.gravity * sub_dt_squared

        for _iteration in range(constraint_iterations):
            positions[0] = base_points[0].copy()
            for segment_index, length in enumerate(lengths):
                anchor = positions[segment_index]
                base_direction = base_points[segment_index + 1] - base_points[segment_index]
                if base_direction.length_squared <= EPSILON:
                    continue
                target = anchor + base_direction.normalized() * length
                candidate = positions[segment_index + 1].lerp(
                    target, stiffness_per_iteration
                )
                direction = candidate - anchor
                direction = _clamp_direction(
                    direction, base_direction, chain.max_angle_radians
                )
                candidate = anchor + direction * length
                # Alternate collision and fixed-length projections.  Collision
                # can override the soft angular limit: avoiding penetration is
                # the hard constraint, while max_angle only limits free motion.
                positions[segment_index + 1] = _fixed_length_collision_candidate(
                    anchor,
                    candidate,
                    length,
                    colliders
                    if segment_index + 1 >= chain.collision_start_point
                    else (),
                    chain.collision_margin,
                    base_direction,
                    chain.collision_guide,
                    chain.collision_guide_weight,
                )


def _pose_quaternions_for_points(
    armature: Any,
    chain: ChainConfig,
    base_points: Sequence[Vector],
    base_matrices: Sequence[Matrix],
    simulated_points: Sequence[Vector],
) -> dict[str, Quaternion]:
    quaternions: dict[str, Quaternion] = {}
    desired_matrices: dict[str, Matrix] = {}
    for index, bone_name in enumerate(chain.bones):
        base_direction = base_points[index + 1] - base_points[index]
        desired_direction = simulated_points[index + 1] - simulated_points[index]
        if base_direction.length_squared <= EPSILON or desired_direction.length_squared <= EPSILON:
            delta = Quaternion()
        else:
            delta = base_direction.normalized().rotation_difference(
                desired_direction.normalized()
            )
        desired_matrix = (
            Matrix.Translation(simulated_points[index])
            @ delta.to_matrix().to_4x4()
            @ Matrix.Translation(-base_points[index])
            @ base_matrices[index]
        )
        pose_bone = armature.pose.bones[bone_name]
        parent = pose_bone.parent
        if parent is None:
            basis_matrix = pose_bone.bone.convert_local_to_pose(
                desired_matrix,
                pose_bone.bone.matrix_local,
                invert=True,
            )
        else:
            parent_matrix = desired_matrices.get(parent.name, parent.matrix)
            basis_matrix = pose_bone.bone.convert_local_to_pose(
                desired_matrix,
                pose_bone.bone.matrix_local,
                parent_matrix=parent_matrix,
                parent_matrix_local=parent.bone.matrix_local,
                invert=True,
            )
        _location, quaternion, _scale = basis_matrix.decompose()
        quaternion.normalize()
        quaternions[bone_name] = quaternion
        desired_matrices[bone_name] = desired_matrix
    return quaternions


def _close_quaternion_loop(samples: list[Quaternion]) -> list[Quaternion]:
    if len(samples) <= 1:
        return samples
    compatible: list[Quaternion] = []
    for quaternion in samples:
        value = quaternion.copy().normalized()
        if compatible:
            value.make_compatible(compatible[-1])
        compatible.append(value)
    delta = compatible[-1].rotation_difference(compatible[0])
    identity = Quaternion()
    corrected: list[Quaternion] = []
    denominator = len(compatible) - 1
    for index, quaternion in enumerate(compatible):
        correction = identity.slerp(delta, index / denominator)
        value = (correction @ quaternion).normalized()
        if corrected:
            value.make_compatible(corrected[-1])
        corrected.append(value)
    corrected[-1] = corrected[0].copy()
    return corrected


def _quaternion_angular_distance(a: Quaternion, b: Quaternion) -> float:
    """Return the shortest orientation distance, treating q and -q as equal."""
    dot = max(-1.0, min(1.0, abs(float(a.dot(b)))))
    return 2.0 * math.acos(dot)


def _close_quaternion_loop_endpoint(samples: list[Quaternion]) -> list[Quaternion]:
    """Keep a warmed physics loop collision-safe and quaternion-compatible."""
    if len(samples) <= 1:
        return samples
    compatible: list[Quaternion] = []
    for quaternion in samples:
        value = quaternion.copy().normalized()
        if compatible:
            value.make_compatible(compatible[-1])
        compatible.append(value)
    return compatible


def _bake_chest_jiggle(
    armature: Any,
    action: Any,
    config: ChestJiggleConfig | None,
    loop: bool,
    fps: float,
    frame_start: int,
    frame_end: int,
    settle_frames: int,
    warmup_loops: int,
) -> dict[str, Any]:
    if config is None:
        return {
            "enabled": False,
            "gain": 0.0,
            "bones": 0,
            "quaternionCurvesChanged": 0,
            "maximumAngularSpanDegrees": 0.0,
            "maximumOffsetDegrees": 0.0,
        }
    gain = max(0.0, float(config.action_gains.get(action.name, 0.0)))
    if gain <= 0.0:
        return {
            "enabled": True,
            "gain": gain,
            "bones": len(config.bones),
            "quaternionCurvesChanged": 0,
            "maximumAngularSpanDegrees": 0.0,
            "maximumOffsetDegrees": 0.0,
        }

    _assign_action(armature, action)
    for bone_name in config.bones:
        armature.pose.bones[bone_name].rotation_mode = "QUATERNION"

    frames = list(range(frame_start, frame_end + 1))
    base_quaternions: dict[str, dict[int, Quaternion]] = {
        bone_name: {} for bone_name in config.bones
    }
    driver_positions: dict[int, Vector] = {}
    for frame in frames:
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        driver_positions[frame] = (
            armature.pose.bones[config.driver_bone].matrix.translation.copy()
        )
        for bone_name in config.bones:
            base_quaternions[bone_name][frame] = (
                armature.pose.bones[bone_name]
                .rotation_quaternion.copy()
                .normalized()
            )

    first_position = driver_positions[frame_start]
    previous_position = first_position.copy()
    previous_velocity = Vector((0.0, 0.0, 0.0))
    angle = 0.0
    angular_velocity = 0.0
    recorded_angles: dict[int, float] = {}

    def advance(frame: int, record: bool) -> None:
        nonlocal previous_position, previous_velocity, angle, angular_velocity
        position = driver_positions[frame]
        velocity = (position - previous_position) * fps
        acceleration = (velocity - previous_velocity) * fps
        previous_position = position
        previous_velocity = velocity
        drive = -acceleration.z + config.forward_response * acceleration.y
        target = max(
            -config.max_angle_radians,
            min(
                config.max_angle_radians,
                drive * config.response_radians_per_acceleration * gain,
            ),
        )
        angular_velocity += (target - angle) * config.stiffness
        angular_velocity *= config.damping
        angle += angular_velocity
        if angle > config.max_angle_radians:
            angle = config.max_angle_radians
            angular_velocity = min(0.0, angular_velocity)
        elif angle < -config.max_angle_radians:
            angle = -config.max_angle_radians
            angular_velocity = max(0.0, angular_velocity)
        if record:
            recorded_angles[frame] = angle

    for _ in range(settle_frames):
        advance(frame_start, False)
    if loop:
        for _ in range(warmup_loops):
            for frame in range(frame_start, frame_end + 1):
                advance(frame, False)
    for frame in range(frame_start, frame_end + 1):
        advance(frame, True)

    samples: dict[str, dict[int, Quaternion]] = {
        bone_name: {} for bone_name in config.bones
    }
    for bone_name in config.bones:
        previous_value: Quaternion | None = None
        for frame in frames:
            # The jiggle axis is expressed in the chest bone's local space.  Compose
            # it with the already-sampled animation instead of mutating pose matrices;
            # direct pose writes can invalidate layered-action evaluation in Blender 5.
            delta = Quaternion(config.axis_local, recorded_angles[frame])
            value = (
                base_quaternions[bone_name][frame] @ delta
            ).normalized()
            if previous_value is not None:
                value.make_compatible(previous_value)
            samples[bone_name][frame] = value
            previous_value = value.copy()

    if loop:
        for bone_name, by_frame in samples.items():
            ordered = [by_frame[frame] for frame in range(frame_start, frame_end + 1)]
            corrected = _close_quaternion_loop(ordered)
            samples[bone_name] = {
                frame: corrected[frame - frame_start]
                for frame in range(frame_start, frame_end + 1)
            }
    else:
        for by_frame in samples.values():
            previous_value: Quaternion | None = None
            for frame in frames:
                value = by_frame[frame]
                if previous_value is not None:
                    value.make_compatible(previous_value)
                previous_value = value.copy()

    curves = _curve_map(action)
    changed_curves = 0
    maximum_span = 0.0
    for bone_name, by_frame in samples.items():
        ordered = [by_frame[frame] for frame in range(frame_start, frame_end + 1)]
        reference = ordered[0]
        maximum_span = max(
            maximum_span,
            max(_quaternion_angular_distance(reference, value) for value in ordered),
        )
        data_path = f'pose.bones["{bone_name}"].rotation_quaternion'
        for array_index in range(4):
            curve = curves.get((data_path, array_index))
            if curve is None:
                raise SpringBakeError(
                    f"Action {action.name!r} is missing {data_path}[{array_index}]"
                )
            _replace_curve_samples(
                curve,
                {
                    frame: float(by_frame[frame][array_index])
                    for frame in range(frame_start, frame_end + 1)
                },
                frame_start,
                frame_end,
            )
            changed_curves += 1
    return {
        "enabled": True,
        "gain": gain,
        "bones": len(config.bones),
        "quaternionCurvesChanged": changed_curves,
        "maximumAngularSpanDegrees": math.degrees(maximum_span),
        "maximumOffsetDegrees": math.degrees(
            max(abs(value) for value in recorded_angles.values())
        ),
    }


def _bake_action(
    armature: Any,
    action: Any,
    chains: Sequence[ChainConfig],
    colliders: Sequence[ColliderConfig],
    chest_jiggle: ChestJiggleConfig | None,
    mesh_collision_validation: MeshCollisionValidationConfig | None,
    root_bone: str,
    canonical_root: dict[tuple[str, int], float],
    loop: bool,
    fps: float,
    substeps: int,
    constraint_iterations: int,
    settle_frames: int,
    warmup_loops: int,
) -> dict[str, Any]:
    frame_start = int(math.floor(float(action.frame_range[0])))
    frame_end = int(math.ceil(float(action.frame_range[1])))
    if frame_end < frame_start:
        raise SpringBakeError(f"Invalid frame range for action {action.name!r}")

    _reset_pose_to_rest(armature)
    root_applied = _remove_root_motion(action, root_bone, canonical_root)
    _assign_action(armature, action)
    action.use_fake_user = True
    action.use_frame_range = True
    action.frame_start = frame_start
    action.frame_end = frame_end
    action.use_cyclic = loop
    for chain in chains:
        for bone_name in chain.bones:
            armature.pose.bones[bone_name].rotation_mode = "QUATERNION"

    chest_result = _bake_chest_jiggle(
        armature,
        action,
        chest_jiggle,
        loop,
        fps,
        frame_start,
        frame_end,
        settle_frames,
        warmup_loops,
    )

    bpy.context.scene.render.fps = int(round(fps))
    bpy.context.scene.render.fps_base = int(round(fps)) / fps
    bpy.context.scene.frame_start = frame_start
    bpy.context.scene.frame_end = frame_end
    bpy.context.scene.frame_set(frame_start)
    bpy.context.view_layer.update()

    states: dict[str, dict[str, Any]] = {}
    for chain in chains:
        base_points, _base_matrices = _chain_base_data(armature, chain)
        lengths = [
            (base_points[index + 1] - base_points[index]).length
            for index in range(len(base_points) - 1)
        ]
        if any(length <= EPSILON for length in lengths):
            raise SpringBakeError(f"Chain {chain.name!r} contains a zero-length segment")
        states[chain.name] = {
            "positions": [point.copy() for point in base_points],
            "previous": [point.copy() for point in base_points],
            "lengths": lengths,
        }

    def advance(frame: int, record: bool, storage: dict[str, dict[int, Quaternion]]) -> None:
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for chain in chains:
            evaluated = _evaluated_colliders(
                armature, _colliders_for_chain(colliders, chain.name)
            )
            base_points, base_matrices = _chain_base_data(armature, chain)
            state = states[chain.name]
            _simulate_step(
                state["positions"],
                state["previous"],
                base_points,
                state["lengths"],
                chain,
                evaluated,
                1.0 / fps,
                substeps,
                constraint_iterations,
            )
            quaternions = _pose_quaternions_for_points(
                armature,
                chain,
                base_points,
                base_matrices,
                state["positions"],
            )
            if record:
                for bone_name, quaternion in quaternions.items():
                    storage[bone_name][frame] = quaternion

    samples: dict[str, dict[int, Quaternion]] = {
        bone_name: {}
        for chain in chains
        for bone_name in chain.bones
    }
    for _ in range(settle_frames):
        advance(frame_start, False, samples)
    if loop:
        for _ in range(warmup_loops):
            for frame in range(frame_start, frame_end + 1):
                advance(frame, False, samples)
    for frame in range(frame_start, frame_end + 1):
        advance(frame, True, samples)

    if loop:
        for bone_name, by_frame in samples.items():
            ordered = [by_frame[frame] for frame in range(frame_start, frame_end + 1)]
            corrected = _close_quaternion_loop_endpoint(ordered)
            samples[bone_name] = {
                frame: corrected[frame - frame_start]
                for frame in range(frame_start, frame_end + 1)
            }
    else:
        for by_frame in samples.values():
            previous_value: Quaternion | None = None
            for frame in range(frame_start, frame_end + 1):
                value = by_frame[frame]
                if previous_value is not None:
                    value.make_compatible(previous_value)
                previous_value = value.copy()

    curves = _curve_map(action)
    changed_curves = 0
    maximum_angular_span = 0.0
    for bone_name, by_frame in samples.items():
        ordered = [by_frame[frame] for frame in range(frame_start, frame_end + 1)]
        reference = ordered[0]
        maximum_angular_span = max(
            maximum_angular_span,
            max(_quaternion_angular_distance(reference, value) for value in ordered),
        )
        data_path = f'pose.bones["{bone_name}"].rotation_quaternion'
        for array_index in range(4):
            curve = curves.get((data_path, array_index))
            if curve is None:
                raise SpringBakeError(
                    f"Action {action.name!r} is missing {data_path}[{array_index}]"
                )
            _replace_curve_samples(
                curve,
                {
                    frame: float(by_frame[frame][array_index])
                    for frame in range(frame_start, frame_end + 1)
                },
                frame_start,
                frame_end,
            )
            changed_curves += 1

    collision_validation = _validate_action_collisions(
        armature,
        action,
        chains,
        colliders,
        frame_start,
        frame_end,
    )
    mesh_collision_result = _validate_mesh_collisions(
        action,
        mesh_collision_validation,
        frame_start,
        frame_end,
    )
    _assign_action(armature, action)
    bpy.context.scene.frame_set(frame_start)
    bpy.context.view_layer.update()
    return {
        "name": action.name,
        "frameStart": frame_start,
        "frameEnd": frame_end,
        "frameCount": frame_end - frame_start + 1,
        "loop": loop,
        "rootChannelsNeutralized": root_applied,
        "hairBones": len(samples),
        "hairQuaternionCurvesChanged": changed_curves,
        "maximumHairAngularSpanDegrees": math.degrees(maximum_angular_span),
        "collisionValidation": collision_validation,
        "meshCollisionValidation": mesh_collision_result,
        "chestJiggle": chest_result,
    }


def _supported_operator_options(operator: Any, requested: dict[str, Any]) -> dict[str, Any]:
    supported = set(operator.get_rna_type().properties.keys())
    return {name: value for name, value in requested.items() if name in supported}


def _make_armature_exportable(armature: Any) -> None:
    active_object = bpy.context.view_layer.objects.active
    if active_object is not None and active_object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for collection in armature.users_collection:
        collection.hide_viewport = False
        collection.hide_render = False
    armature.hide_set(False)
    armature.hide_viewport = False
    armature.hide_render = False
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature


def _load_glb_json(path: Path) -> dict[str, Any]:
    try:
        file_size = path.stat().st_size
        with path.open("rb") as file:
            header = file.read(12)
            magic, version, declared_size = struct.unpack("<4sII", header)
            if magic != GLB_MAGIC or version != GLB_VERSION or declared_size != file_size:
                raise SpringBakeError(f"Invalid GLB container: {path}")
            json_length, chunk_type = struct.unpack("<II", file.read(8))
            if chunk_type != GLB_JSON_CHUNK:
                raise SpringBakeError(f"GLB JSON chunk is missing: {path}")
            json_bytes = file.read(json_length)
        data = json.loads(json_bytes.decode("utf-8").rstrip("\x00 \t\r\n"))
    except (OSError, UnicodeError, json.JSONDecodeError, struct.error) as error:
        raise SpringBakeError(f"Cannot inspect GLB {path}: {error}") from error
    if not isinstance(data, dict):
        raise SpringBakeError(f"GLB JSON root is not an object: {path}")
    return data


def _temporary_output(path: Path) -> Path:
    return path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp.glb")


def _export_action_glb(armature: Any, action: Any, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    _assign_action(armature, action)
    _make_armature_exportable(armature)
    frame_start = int(math.floor(float(action.frame_range[0])))
    bpy.context.scene.frame_set(frame_start)
    bpy.context.view_layer.update()
    temporary = _temporary_output(output)
    requested: dict[str, Any] = {
        "filepath": str(temporary),
        "check_existing": False,
        "export_format": "GLB",
        "use_selection": True,
        "export_cameras": False,
        "export_lights": False,
        "export_apply": False,
        "export_materials": "NONE",
        "export_animations": True,
        "export_animation_mode": "ACTIVE_ACTIONS",
        "export_nla_strips_merged_animation_name": action.name,
        "export_force_sampling": True,
        "export_frame_step": 1,
        "export_anim_slide_to_zero": True,
        "export_bake_animation": False,
        "export_merge_animation": "ACTION",
        "export_anim_single_armature": True,
        "export_reset_pose_bones": True,
        "export_rest_position_armature": True,
        "export_skins": True,
        "export_def_bones": False,
        "export_leaf_bone": False,
        "export_armature_object_remove": False,
        "export_optimize_animation_size": False,
        "export_morph": False,
        "export_morph_animation": False,
        "export_yup": True,
    }
    options = _supported_operator_options(bpy.ops.export_scene.gltf, requested)
    try:
        operation = bpy.ops.export_scene.gltf(**options)
        if "FINISHED" not in operation or not temporary.is_file():
            raise SpringBakeError(f"Blender failed to export {action.name!r}")
        data = _load_glb_json(temporary)
        animations = data.get("animations", [])
        names = [entry.get("name", "") for entry in animations if isinstance(entry, dict)]
        if names != [action.name]:
            raise SpringBakeError(
                f"Animation name changed for {action.name!r}: exported {names}"
            )
        if not data.get("nodes"):
            raise SpringBakeError(f"Export lost the skeleton nodes for {action.name!r}")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "path": str(output),
        "bytes": output.stat().st_size,
        "animations": names,
        "nodes": len(data.get("nodes", [])),
        "skins": len(data.get("skins", [])),
        "meshes": len(data.get("meshes", [])),
        "exportOptions": options,
    }


def _action_records(recipe: dict[str, Any]) -> list[dict[str, Any]]:
    records = recipe.get("actions")
    if not isinstance(records, list) or not records:
        raise SpringBakeError("Recipe must define a non-empty actions array")
    output: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or not isinstance(record.get("name"), str):
            raise SpringBakeError(f"Action record {index} must contain a name")
        relative_output = record.get("output")
        if not isinstance(relative_output, str) or not relative_output:
            raise SpringBakeError(f"Action record {index} must contain an output path")
        output.append(
            {
                "name": record["name"],
                "loop": bool(record.get("loop", False)),
                "output": relative_output,
            }
        )
    return output


def _validate_output_target(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise SpringBakeError(f"Refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def run_with_arguments(arguments: Sequence[str]) -> dict[str, Any]:
    args = _parse_arguments(arguments)
    recipe_path = _absolute_path(args.recipe)
    output_blend = _absolute_path(args.output_blend)
    output_dir = _absolute_path(args.output_dir) if args.output_dir else None
    recipe = _load_recipe(recipe_path)
    _validate_output_target(output_blend, args.overwrite)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    armature_name = str(recipe.get("armature", ""))
    armature = bpy.data.objects.get(armature_name)
    if armature is None or armature.type != "ARMATURE":
        available = sorted(obj.name for obj in bpy.data.objects if obj.type == "ARMATURE")
        raise SpringBakeError(
            f"Armature {armature_name!r} was not found; available: {available}"
        )
    root_bone = str(recipe.get("rootBone", "root"))
    if armature.pose.bones.get(root_bone) is None:
        raise SpringBakeError(f"Root bone {root_bone!r} was not found")
    _make_armature_exportable(armature)

    actions = _action_records(recipe)
    selected = set(args.actions or [])
    if selected:
        known = {record["name"] for record in actions}
        unknown = sorted(selected - known)
        if unknown:
            raise SpringBakeError(f"Requested actions are absent from recipe: {unknown}")
        actions = [record for record in actions if record["name"] in selected]

    missing_actions = [
        record["name"] for record in actions if bpy.data.actions.get(record["name"]) is None
    ]
    if missing_actions:
        raise SpringBakeError(f"Blend file is missing actions: {missing_actions}")

    reference_name = str(recipe.get("rootReferenceAction", ""))
    reference_action = bpy.data.actions.get(reference_name)
    if reference_action is None:
        raise SpringBakeError(f"Root reference action {reference_name!r} was not found")
    reference_frame = int(math.floor(float(reference_action.frame_range[0])))
    canonical_root = _canonical_root_values(reference_action, root_bone, reference_frame)

    chains = _parse_chain_configs(recipe, armature)
    colliders = _parse_colliders(recipe, armature)
    chest_jiggle = _parse_chest_jiggle(recipe, armature)
    mesh_collision_validation = _parse_mesh_collision_validation(recipe)
    solver = recipe.get("solver", {})
    if not isinstance(solver, dict):
        raise SpringBakeError("Recipe solver must be an object")
    fps = float(solver.get("fps", 30.0))
    substeps = int(solver.get("substeps", 2))
    constraint_iterations = int(solver.get("constraintIterations", 5))
    settle_frames = int(solver.get("settleFrames", 20))
    warmup_loops = int(solver.get("warmupLoops", 3))
    if fps <= 0 or substeps < 1 or constraint_iterations < 1:
        raise SpringBakeError("Solver fps, substeps, and iterations must be positive")

    source_blend = Path(bpy.data.filepath).resolve()
    source_stat = source_blend.stat()
    baked: list[dict[str, Any]] = []
    exported: list[dict[str, Any]] = []
    for record in actions:
        action = bpy.data.actions[record["name"]]
        baked_record = _bake_action(
            armature,
            action,
            chains,
            colliders,
            chest_jiggle,
            mesh_collision_validation,
            root_bone,
            canonical_root,
            bool(record["loop"]),
            fps,
            substeps,
            constraint_iterations,
            settle_frames,
            warmup_loops,
        )
        baked.append(baked_record)
        if output_dir is not None:
            output_path = (output_dir / record["output"]).resolve()
            try:
                output_path.relative_to(output_dir)
            except ValueError as error:
                raise SpringBakeError(
                    f"Action output escapes output directory: {record['output']}"
                ) from error
            _validate_output_target(output_path, args.overwrite)
            exported.append(_export_action_glb(armature, action, output_path))

    _assign_action(armature, bpy.data.actions[actions[0]["name"]])
    bpy.context.scene.frame_set(int(baked[0]["frameStart"]))
    bpy.context.view_layer.update()
    save_result = bpy.ops.wm.save_as_mainfile(
        filepath=str(output_blend),
        check_existing=False,
        copy=False,
    )
    if "FINISHED" not in save_result or not output_blend.is_file():
        raise SpringBakeError(f"Failed to save baked blend: {output_blend}")

    source_after = source_blend.stat()
    source_preserved = (
        source_stat.st_size == source_after.st_size
        and source_stat.st_mtime_ns == source_after.st_mtime_ns
    )
    if not source_preserved and source_blend != output_blend:
        raise SpringBakeError(f"Input blend changed during bake: {source_blend}")

    return {
        "success": True,
        "sourceBlend": str(source_blend),
        "sourcePreserved": source_preserved,
        "outputBlend": str(output_blend),
        "outputBlendBytes": output_blend.stat().st_size,
        "armature": armature.name,
        "rootBone": root_bone,
        "rootReferenceAction": reference_name,
        "canonicalRoot": {
            f"{name}[{index}]": value
            for (name, index), value in canonical_root.items()
        },
        "chains": [
            {"name": chain.name, "bones": list(chain.bones)} for chain in chains
        ],
        "colliders": [collider.name for collider in colliders],
        "bakedActions": baked,
        "exports": exported,
        "warnings": [],
    }


if __name__ == "__main__":
    import sys

    print(json.dumps(run_with_arguments(sys.argv[1:]), indent=2))
