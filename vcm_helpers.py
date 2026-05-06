#  ***** GPL LICENSE BLOCK *****
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#  All rights reserved.
#  ***** GPL LICENSE BLOCK *****

# <pep8 compliant>


# COMMON IDENTIFIERS:

# PARAMETERS
# src_attr, dst_attr : source and destination Attributes (containing array of per vertex or corner data)
# src_channel_idx, dst_channel_idx : source and destination channel indices (0-3)

# LOCAL VARIABLES
# src_av, dst_av : source and destination Attribute Values (e.g. src_attr.data[i].color)
# src_cv, dst_cv : source and destination channel values (e.g. src_attr.data[i].color[src_channel_idx])


import bpy
import bmesh
import hashlib
import logging
import math
import random
import re
from math import fmod
from mathutils import Color, Vector
from .vcm_globals import *
from .vcm_log import logger, log_vcol_info


# ---------------------------------------------------------------------------
# Brush color access (Blender 4.3+ brush-asset / unified-paint compatibility)
# ---------------------------------------------------------------------------
#
# Blender 4.3 reworked vertex paint brushes into asset-shelf brushes; from
# 4.5 onward `bpy.data.brushes['Draw']` is no longer reliably the active
# brush, and Unified Paint Settings can intercept color reads/writes when
# `use_unified_color` is True. These helpers route every brush color
# read/write through the active brush + unified flag, so VCM stays
# synchronised with what the user actually sees in the brush panel.

def get_active_vp_brush(context):
    """Return the active Vertex Paint brush, or None if unavailable."""
    ts = getattr(context, 'tool_settings', None)
    if ts is None:
        return None
    vp = getattr(ts, 'vertex_paint', None)
    if vp is None:
        return None
    return getattr(vp, 'brush', None)


def _unified_settings(context):
    ts = getattr(context, 'tool_settings', None)
    if ts is None:
        return None
    return getattr(ts, 'unified_paint_settings', None)


def get_unified_paint_settings(context):
    """Public alias for the Unified Paint Settings block."""
    return _unified_settings(context)


def is_unified_color_active(context):
    """True when Unified Paint Settings drives brush color in the UI."""
    ups = _unified_settings(context)
    return ups is not None and bool(getattr(ups, 'use_unified_color', False))


def get_brush_color(context, brush=None):
    """Read primary brush color; honors Unified Paint Settings if enabled."""
    if brush is None:
        brush = get_active_vp_brush(context)
    ups = _unified_settings(context)
    if ups is not None and getattr(ups, 'use_unified_color', False):
        return tuple(ups.color)
    if brush is None:
        return (1.0, 1.0, 1.0)
    return tuple(brush.color)


def get_brush_secondary_color(context, brush=None):
    """Read secondary brush color; honors Unified Paint Settings if enabled."""
    if brush is None:
        brush = get_active_vp_brush(context)
    ups = _unified_settings(context)
    if ups is not None and getattr(ups, 'use_unified_color', False):
        return tuple(ups.secondary_color)
    if brush is None:
        return (0.0, 0.0, 0.0)
    return tuple(brush.secondary_color)


def _coerce_color3(value):
    # Accept tuple / list / Color / Vector / bpy_prop_array / scalar.
    try:
        n = len(value)
        seq = value
    except TypeError:
        x = float(value)
        return (x, x, x)
    if n >= 3:
        return (float(seq[0]), float(seq[1]), float(seq[2]))
    if n == 0:
        return (0.0, 0.0, 0.0)
    x = float(seq[0])
    return (x, x, x)


def set_brush_color(context, value, brush=None):
    """Write primary brush color to brush AND unified (when unified active)."""
    if brush is None:
        brush = get_active_vp_brush(context)
    rgb = _coerce_color3(value)
    ups = _unified_settings(context)
    # Always mirror to the brush so per-brush state stays correct, AND to
    # unified settings when the user has enabled unified color — Blender
    # reads from whichever is active for the painting display.
    if brush is not None:
        try:
            brush.color = rgb
        except Exception as e:
            logger.warning("VCM brush color write failed: %s", e)
    if ups is not None and getattr(ups, 'use_unified_color', False):
        try:
            ups.color = rgb
        except Exception as e:
            logger.warning("VCM unified color write failed: %s", e)


def set_brush_secondary_color(context, value, brush=None):
    """Write secondary brush color to brush AND unified (when unified active)."""
    if brush is None:
        brush = get_active_vp_brush(context)
    rgb = _coerce_color3(value)
    ups = _unified_settings(context)
    if brush is not None:
        try:
            brush.secondary_color = rgb
        except Exception as e:
            logger.warning("VCM brush secondary write failed: %s", e)
    if ups is not None and getattr(ups, 'use_unified_color', False):
        try:
            ups.secondary_color = rgb
        except Exception as e:
            logger.warning("VCM unified secondary write failed: %s", e)


# VCM-ISO_<MASK>_<original-name>, where MASK is 1..4 letters from RGBA.
_VCM_ISO_RE = re.compile(r'^VCM-ISO_([RGBA]{1,4})_(.+)$')


def posterize(value, steps):
    return round(value * steps) / steps


def remap(value, min0, max0, min1, max1):
    r0 = max0 - min0
    if r0 == 0:
        return min1
    r1 = max1 - min1
    return ((value - min0) * r1) / r0 + min1


def channel_id_to_idx(id):
    if id == red_id:
        return 0
    if id == green_id:
        return 1
    if id == blue_id:
        return 2
    if id == alpha_id:
        return 3
    # default to red
    return 0


def get_active_channel_mask(active_channels):
    rgba_mask = [True if cid in active_channels else False for cid in valid_channel_ids]
    return rgba_mask


def get_isolated_channel_ids(vcol):
    """Parse VCM-ISO_<MASK>_<name>. MASK is 1..4 distinct chars from RGBA.

    Returns [original_name, mask_str] or None. mask_str is a single char
    for legacy single-channel isolate (e.g. 'R'), or 2-4 chars for
    multi-channel mask (e.g. 'RG', 'RGB', 'RGBA') in RGBA order.
    """
    if vcol is None:
        return None
    m = _VCM_ISO_RE.match(vcol.name)
    if not m:
        return None
    mask = m.group(1)
    if len(set(mask)) != len(mask):
        return None
    # Normalise mask to RGBA order so callers see a stable form.
    mask = ''.join(c for c in valid_channel_ids if c in mask)
    return [m.group(2), mask]


# ---------------------------------------------------------------------------
# Isolate dirty/clean detection (Iteration 6: smart channel switching)
# ---------------------------------------------------------------------------
#
# A "clean" isolate is one whose temp VCM-ISO_* attribute still matches the
# data we wrote into it at isolate creation time. A "dirty" isolate has been
# edited since — by VCM operators, Blender's native paint brush, fills, etc.
#
# We do NOT track edits via flag/event hooks because vertex paint brush
# strokes do not surface a hookable signal. Instead we fingerprint the
# selected mask channels of the iso temp at creation time and compare the
# fingerprint on every smart-switch attempt.

def _iso_apply_source_indices(mask):
    """Channel indices in the temp VCM-ISO_* attribute that Apply reads back.

    The dirty checksum MUST sample exactly these — anything else risks a
    silent data loss when smart-switch auto-discards.

    Single-channel iso (R / G / B / A): IsolateChannel broadcasts the source
    value into RGB and Apply reads `temp[0]` back into `vcol[mask_idx]`. So
    the apply-source is `[0]` for every single mask. In particular, an
    Alpha isolate stores `[src_A, src_A, src_A, 1.0]` — sampling temp[3]
    (alpha) reads the constant fill and never observes any edit. Sampling
    temp[0] tracks what the user actually paints (and what Apply will
    write back).

    Multi-channel mask (RG, RA, RGB, RGBA, …): IsolateChannelMask copies
    selected channels verbatim and Apply uses `copy_mask_channels` which
    reads `temp[ci]` for each ci in mask. So apply-source = those mask
    indices.
    """
    if not mask:
        return []
    if len(mask) == 1:
        return [0]
    return [channel_id_to_idx(c) for c in mask]


def compute_iso_checksum(vcol, mask):
    """Quantized fingerprint of the iso temp's apply-source channels.

    Returns a hex digest (str) or None on failure. Header includes mask,
    broadcast/channels mode, domain, data_type, and data length so a
    fingerprint computed under one scheme cannot accidentally compare equal
    to one computed under another (e.g. legacy iter-7 metadata).

    The set of channel indices sampled is `_iso_apply_source_indices(mask)`
    — identical to what `ApplyIsolatedChannel` reads, so dirty-check and
    Apply always agree on what represents the isolated data. See that
    helper's docstring for the Alpha-specific rationale.
    """
    if vcol is None or not mask:
        return None
    indices = _iso_apply_source_indices(mask)
    if not indices:
        return None
    try:
        n = len(vcol.data)
    except Exception as e:
        logger.warning(
            "VCM compute_iso_checksum: data length unreadable on %s: %s",
            getattr(vcol, 'name', '?'), e)
        return None
    mode = 'broadcast' if len(mask) == 1 else 'channels'
    h = hashlib.blake2b(digest_size=16)
    header = "vcm-iso|{0}|{1}|{2}|{3}|{4}|{5}".format(
        mode, mask, vcol.domain, vcol.data_type, n, len(indices))
    h.update(header.encode('utf-8'))
    # Quantize to 16-bit. Float jitter from BYTE_COLOR/FLOAT_COLOR
    # round-tripping through Blender stays well below 1/65535 in normal
    # 0..1 range so the digest stays deterministic across reads.
    qmax = 65535
    n_idx = len(indices)
    buf = bytearray(n * n_idx * 2)
    pos = 0
    try:
        for i in range(n):
            c = vcol.data[i].color
            for ci in indices:
                v = c[ci]
                if v < 0.0:
                    v = 0.0
                elif v > 1.0:
                    v = 1.0
                q = int(v * qmax + 0.5)
                buf[pos] = q & 0xFF
                buf[pos + 1] = (q >> 8) & 0xFF
                pos += 2
    except Exception as e:
        logger.warning(
            "VCM compute_iso_checksum: read failed on %s: %s",
            getattr(vcol, 'name', '?'), e)
        return None
    h.update(bytes(buf))
    digest = h.hexdigest()
    logger.debug(
        "VCM compute_iso_checksum: attr=%s mask=%s mode=%s indices=%s "
        "len=%d digest=%s",
        getattr(vcol, 'name', '?'), mask, mode, indices, n, digest[:12])
    return digest


def store_iso_metadata(mesh, iso_vcol, original_name, mask, checksum):
    """Write the iso fingerprint + descriptor onto the mesh datablock.

    Stored under `iso_meta_key`. Survives save/load/undo because it is an
    ID custom property on mesh data.
    """
    if mesh is None or iso_vcol is None:
        return False
    try:
        mesh[iso_meta_key] = {
            "iso_name": iso_vcol.name,
            "original_name": original_name,
            "mask": mask,
            "domain": iso_vcol.domain,
            "data_type": iso_vcol.data_type,
            "data_len": len(iso_vcol.data),
            "checksum": checksum or "",
        }
        return True
    except Exception as e:
        logger.warning(
            "VCM store_iso_metadata: failed to write meta: %s", e)
        return False


def read_iso_metadata(mesh):
    """Return iso meta dict (plain Python) or None if missing/invalid."""
    if mesh is None:
        return None
    try:
        if iso_meta_key not in mesh.keys():
            return None
        raw = mesh[iso_meta_key]
    except Exception:
        return None
    try:
        return {
            "iso_name": str(raw["iso_name"]) if "iso_name" in raw.keys() else "",
            "original_name": (str(raw["original_name"])
                              if "original_name" in raw.keys() else ""),
            "mask": str(raw["mask"]) if "mask" in raw.keys() else "",
            "domain": str(raw["domain"]) if "domain" in raw.keys() else "",
            "data_type": (str(raw["data_type"])
                          if "data_type" in raw.keys() else ""),
            "data_len": int(raw["data_len"]) if "data_len" in raw.keys() else -1,
            "checksum": str(raw["checksum"]) if "checksum" in raw.keys() else "",
        }
    except Exception as e:
        logger.warning("VCM read_iso_metadata: malformed meta: %s", e)
        return None


def clear_iso_metadata(mesh):
    """Delete the stored iso metadata. Safe no-op if absent."""
    if mesh is None:
        return
    try:
        if iso_meta_key in mesh.keys():
            del mesh[iso_meta_key]
    except Exception as e:
        logger.warning("VCM clear_iso_metadata: %s", e)


def get_iso_dirty_state(mesh):
    """Inspect the active iso attribute and report dirty/clean.

    Returns a tuple (state, info) where state is one of:
      'NONE'    — no iso active.
      'CLEAN'   — checksum matches stored fingerprint. Safe to auto-discard.
      'DIRTY'   — selected channels changed. Switching must be blocked.
      'UNKNOWN' — iso temp present but metadata missing/inconsistent. Treat
                  as unsafe to auto-discard; require explicit Apply/Discard.

    info is the meta dict for CLEAN/DIRTY, the iso_vcol name for UNKNOWN,
    None for NONE.
    """
    if mesh is None or not mesh.color_attributes:
        return ('NONE', None)
    try:
        iso_vcol = mesh.color_attributes.active_color
    except Exception:
        return ('NONE', None)
    if iso_vcol is None:
        return ('NONE', None)
    info = get_isolated_channel_ids(iso_vcol)
    if info is None:
        return ('NONE', None)
    iso_name = iso_vcol.name
    iso_mask = info[1]
    iso_orig = info[0]
    meta = read_iso_metadata(mesh)
    if not meta:
        return ('UNKNOWN', iso_name)
    if (meta.get('iso_name') != iso_name
            or meta.get('original_name') != iso_orig
            or meta.get('mask') != iso_mask
            or meta.get('domain') != iso_vcol.domain
            or meta.get('data_type') != iso_vcol.data_type
            or int(meta.get('data_len', -1)) != len(iso_vcol.data)):
        logger.warning(
            "VCM get_iso_dirty_state: meta drift on %s (mask=%s) — UNKNOWN",
            iso_name, iso_mask)
        return ('UNKNOWN', iso_name)
    if iso_orig not in mesh.color_attributes:
        logger.warning(
            "VCM get_iso_dirty_state: original '%s' missing from mesh — UNKNOWN",
            iso_orig)
        return ('UNKNOWN', iso_name)
    cur = compute_iso_checksum(iso_vcol, iso_mask)
    if cur is None:
        return ('UNKNOWN', iso_name)
    stored = meta.get('checksum', '')
    state = 'DIRTY' if cur != stored else 'CLEAN'
    mode = 'broadcast' if len(iso_mask) == 1 else 'channels'
    logger.debug(
        "VCM get_iso_dirty_state: iso=%s orig=%s mask=%s mode=%s "
        "stored=%s current=%s -> %s",
        iso_name, iso_orig, iso_mask, mode,
        (stored or 'null')[:12], (cur or 'null')[:12], state)
    if state == 'DIRTY':
        return ('DIRTY', meta)
    return ('CLEAN', meta)


def normalize_channel_mask(value):
    """Coerce arbitrary input into a sorted RGBA-order mask string.

    Accepts a string ("RG", "rg", "GR"), a set/list of channel ids,
    or anything iterable of single chars. Returns the mask sorted in
    RGBA order with duplicates removed. Empty mask returns ''.
    """
    if value is None:
        return ''
    if isinstance(value, str):
        chars = set(value.upper())
    else:
        try:
            chars = {str(c).upper() for c in value}
        except TypeError:
            return ''
    return ''.join(c for c in valid_channel_ids if c in chars)


def build_loop_neighbors(mesh):
    """Return a list[len(mesh.loops)] of tuples of neighboring loop indices.

    Neighbors per loop:
      - prev/next loop in the same polygon
      - all other loops sharing the loop's vertex_index
    Self is excluded. Result is a tuple to make snapshots deterministic.
    """
    n_loops = len(mesh.loops)
    sets = [set() for _ in range(n_loops)]

    for poly in mesh.polygons:
        loops = list(poly.loop_indices)
        m = len(loops)
        if m < 2:
            continue
        for i, li in enumerate(loops):
            sets[li].add(loops[(i - 1) % m])
            sets[li].add(loops[(i + 1) % m])

    vert_to_loops = {}
    for li, loop in enumerate(mesh.loops):
        vert_to_loops.setdefault(loop.vertex_index, []).append(li)
    for vi, loops in vert_to_loops.items():
        if len(loops) < 2:
            continue
        for li in loops:
            for lj in loops:
                if lj != li:
                    sets[li].add(lj)

    for i in range(n_loops):
        sets[i].discard(i)
    return [tuple(s) for s in sets]


def build_vertex_neighbors(mesh):
    """Per-vertex tuple of edge-connected neighbor vertex indices.

    Built from `mesh.edges`. Self is never in the set. Vertices with no
    edges return an empty tuple.
    """
    n = len(mesh.vertices)
    sets = [set() for _ in range(n)]
    for e in mesh.edges:
        a = e.vertices[0]
        b = e.vertices[1]
        if a == b:
            continue
        sets[a].add(b)
        sets[b].add(a)
    return [tuple(s) for s in sets]


def _vertex_channel_roughness(vert_values, neighbors, channel_indices):
    """Sum of squared per-channel differences across each undirected edge.

    Used only as a before/after diagnostic in DEBUG logs. Each edge is
    visited once per direction in the neighbor lists; the result is halved
    so the metric matches `sum_{(i,j) in E} (vi-vj)^2`.
    """
    totals = {ci: 0.0 for ci in channel_indices}
    for i, nb in enumerate(neighbors):
        if not nb:
            continue
        vi = vert_values[i]
        for j in nb:
            vj = vert_values[j]
            for ci in channel_indices:
                d = vi[ci] - vj[ci]
                totals[ci] += d * d
    return {ci: t * 0.5 for ci, t in totals.items()}


def blur_channels_mask_vertex(mesh, vcol, mask, strength, iterations):
    """Vertex-diffusion smoothing of selected channels on a CORNER-domain
    color attribute.

    Algorithm:
      1. Snapshot every loop's full RGBA so unselected channels round-trip
         bit-exact through Blender's quantization.
      2. For each vertex, average the selected channel values across all
         loops that reference it. This collapses per-corner discontinuities
         into a single per-vertex value (which is what causes the visible
         cell-banding in pure loop blur).
      3. Iterate Jacobi-style edge-graph diffusion on the per-vertex
         values: `new[v] = lerp(cur[v], avg(neighbors), strength)`. Snapshot
         per iteration; clamp 0..1.
      4. Write the smoothed per-vertex value back to every loop using that
         vertex, but only into the channels listed in `mask`. Channels
         outside `mask` are restored from the loop snapshot.

    Returns True on success, False on validation failure (no partial write).
    """
    if vcol is None:
        logger.error("VCM blur_channels_mask_vertex: vcol is None")
        return False
    if vcol.domain != 'CORNER':
        logger.warning(
            "VCM blur_channels_mask_vertex: domain=%s not supported (CORNER only)",
            vcol.domain)
        return False
    if not mask:
        logger.error("VCM blur_channels_mask_vertex: empty mask")
        return False
    indices = [channel_id_to_idx(c) for c in mask]
    if not indices:
        logger.error(
            "VCM blur_channels_mask_vertex: mask resolved to no channels")
        return False
    s = max(0.0, min(float(strength), 1.0))
    if s <= 0.0:
        logger.info("VCM blur_channels_mask_vertex: strength=0, no-op")
        return True
    iters = max(1, int(iterations))

    n_loops = len(vcol.data)
    if n_loops != len(mesh.loops):
        logger.error(
            "VCM blur_channels_mask_vertex: data/loop length mismatch "
            "(data=%d, loops=%d) — refusing to write",
            n_loops, len(mesh.loops))
        return False

    n_verts = len(mesh.vertices)
    if n_verts == 0:
        logger.error("VCM blur_channels_mask_vertex: mesh has no vertices")
        return False

    loop_snapshot = [list(vcol.data[i].color) for i in range(n_loops)]

    vert_loops = [[] for _ in range(n_verts)]
    for li, loop in enumerate(mesh.loops):
        vi = loop.vertex_index
        if 0 <= vi < n_verts:
            vert_loops[vi].append(li)
        else:
            logger.error(
                "VCM blur_channels_mask_vertex: loop %d points to invalid "
                "vertex %d (n_verts=%d) — refusing to write",
                li, vi, n_verts)
            return False

    vert_values = [[0.0, 0.0, 0.0, 0.0] for _ in range(n_verts)]
    for vi in range(n_verts):
        loops = vert_loops[vi]
        if not loops:
            continue
        inv = 1.0 / len(loops)
        for ci in indices:
            acc = 0.0
            for li in loops:
                acc += loop_snapshot[li][ci]
            vert_values[vi][ci] = acc * inv

    try:
        neighbors = build_vertex_neighbors(mesh)
    except Exception as e:
        logger.error(
            "VCM blur_channels_mask_vertex: neighbor graph failed: %s", e)
        return False

    debug_on = logger.isEnabledFor(logging.DEBUG)
    if debug_on:
        before = _vertex_channel_roughness(vert_values, neighbors, indices)

    for _ in range(iters):
        new_vals = [vv[:] for vv in vert_values]
        for vi in range(n_verts):
            nb = neighbors[vi]
            if not nb:
                continue
            inv = 1.0 / len(nb)
            for ci in indices:
                acc = 0.0
                for j in nb:
                    acc += vert_values[j][ci]
                avg = acc * inv
                cur = vert_values[vi][ci]
                v = cur + (avg - cur) * s
                if v < 0.0:
                    v = 0.0
                elif v > 1.0:
                    v = 1.0
                new_vals[vi][ci] = v
        vert_values = new_vals

    if debug_on:
        after = _vertex_channel_roughness(vert_values, neighbors, indices)

    for li, loop in enumerate(mesh.loops):
        vi = loop.vertex_index
        col = loop_snapshot[li]
        vv = vert_values[vi]
        for ci in indices:
            col[ci] = vv[ci]
        vcol.data[li].color = col
    mesh.update()

    if debug_on:
        before_str = ', '.join(
            "{0}={1:.4f}".format(valid_channel_ids[ci], before[ci])
            for ci in indices)
        after_str = ', '.join(
            "{0}={1:.4f}".format(valid_channel_ids[ci], after[ci])
            for ci in indices)
        logger.debug(
            "VCM blur_channels_mask_vertex: roughness before {%s} -> "
            "after {%s}", before_str, after_str)

    logger.debug(
        "VCM blur_channels_mask_vertex: wrote attr=%s mask=%s strength=%.3f "
        "iters=%d (%s/%s, verts=%d, loops=%d)",
        vcol.name, mask, s, iters, vcol.data_type, vcol.domain,
        n_verts, n_loops)
    return True


def blur_channels_dispatch(mesh, vcol, mask, strength, iterations,
                           mode='SMOOTH_VERTEX'):
    """Pick a blur implementation by mode. Default is vertex-diffusion."""
    if mode == 'LEGACY_LOOP':
        return blur_channels_mask(mesh, vcol, mask, strength, iterations)
    return blur_channels_mask_vertex(mesh, vcol, mask, strength, iterations)


def blur_channels_mask(mesh, vcol, mask, strength, iterations):
    """Smooth selected channels of `vcol` using a topology-based neighbor
    average. Only writes back the channels listed in `mask`. Channels
    outside `mask` are preserved bit-exact (read from the snapshot).

    Returns True on success, False if validation fails.
    """
    if vcol is None:
        logger.error("VCM blur_channels_mask: vcol is None")
        return False
    if vcol.domain != 'CORNER':
        # Defensive: the operator-level guard normally rejects POINT before
        # we get here. Log WARNING (not ERROR) since this is an expected
        # graceful refusal path.
        logger.warning(
            "VCM blur_channels_mask: domain=%s not supported (CORNER only)",
            vcol.domain)
        return False
    if not mask:
        logger.error("VCM blur_channels_mask: empty mask")
        return False
    indices = [channel_id_to_idx(c) for c in mask]
    if not indices:
        logger.error("VCM blur_channels_mask: mask resolved to no channels")
        return False
    s = max(0.0, min(float(strength), 1.0))
    if s <= 0.0:
        logger.info("VCM blur_channels_mask: strength=0, no-op")
        return True
    iters = max(1, int(iterations))

    n = len(vcol.data)
    if n != len(mesh.loops):
        logger.error(
            "VCM blur_channels_mask: data/loop length mismatch "
            "(data=%d, loops=%d) — refusing to write",
            n, len(mesh.loops))
        return False

    try:
        neighbors = build_loop_neighbors(mesh)
    except Exception as e:
        logger.error("VCM blur_channels_mask: neighbor graph failed: %s", e)
        return False

    snapshot = [list(vcol.data[i].color) for i in range(n)]

    for it in range(iters):
        new_snap = [c[:] for c in snapshot]
        for i in range(n):
            nb = neighbors[i]
            if not nb:
                continue
            inv = 1.0 / len(nb)
            for ci in indices:
                avg = 0.0
                for j in nb:
                    avg += snapshot[j][ci]
                avg *= inv
                cur = snapshot[i][ci]
                v = cur + (avg - cur) * s
                if v < 0.0:
                    v = 0.0
                elif v > 1.0:
                    v = 1.0
                new_snap[i][ci] = v
        snapshot = new_snap

    for i in range(n):
        vcol.data[i].color = snapshot[i]
    mesh.update()

    logger.debug(
        "VCM blur_channels_mask: wrote attr=%s mask=%s strength=%.3f iters=%d "
        "(%s/%s, len=%d)",
        vcol.name, mask, s, iters, vcol.data_type, vcol.domain, n)
    return True


def copy_mask_channels(mesh, src_attribute, dst_attribute, mask):
    """Copy only the channels listed in `mask` from src to dst, per element.

    Channels outside `mask` in dst are preserved. Both attributes must
    share data_type, domain, and length. Returns True on success.
    """
    if src_attribute is None or dst_attribute is None:
        logger.error("VCM copy_mask_channels: src or dst attribute is None")
        return False
    if (src_attribute.data_type != dst_attribute.data_type
            or src_attribute.domain != dst_attribute.domain):
        logger.error(
            "VCM copy_mask_channels: type/domain mismatch — "
            "src(%s/%s/%s) vs dst(%s/%s/%s)",
            src_attribute.name, src_attribute.data_type, src_attribute.domain,
            dst_attribute.name, dst_attribute.data_type, dst_attribute.domain)
        return False
    src_len = len(src_attribute.data)
    dst_len = len(dst_attribute.data)
    if src_len != dst_len:
        logger.error(
            "VCM copy_mask_channels: data length mismatch — "
            "src=%s/%d vs dst=%s/%d",
            src_attribute.name, src_len, dst_attribute.name, dst_len)
        return False
    indices = [channel_id_to_idx(c) for c in mask]
    if not indices:
        logger.error("VCM copy_mask_channels: empty mask")
        return False
    for i in range(src_len):
        s = src_attribute.data[i].color
        d = dst_attribute.data[i].color
        for ci in indices:
            d[ci] = s[ci]
        dst_attribute.data[i].color = d
    mesh.update()
    logger.debug(
        "VCM copy_mask_channels: success mask=%s src=%s -> dst=%s "
        "(%s/%s, len=%d)",
        mask, src_attribute.name, dst_attribute.name,
        src_attribute.data_type, src_attribute.domain, src_len)
    return True


def get_active_color_attribute(context):
    """Return the active color attribute, or None if unavailable.

    Safe against missing object, non-mesh object, or empty color_attributes.
    """
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return None
    mesh = obj.data
    if not mesh.color_attributes:
        return None
    return mesh.color_attributes.active_color


# ---------------------------------------------------------------------------
# Diagnostic state helpers (Iteration 9, read-only)
# ---------------------------------------------------------------------------
#
# Used by the Copy / Save Diagnostics Summary operators. Must NEVER mutate
# mesh data, remove temp attributes, or invoke other operators. Each helper
# tolerates missing object / non-mesh / no active color attribute.

def get_active_color_attribute_info(context):
    """Return descriptor dict for the active vcol or None."""
    obj = getattr(context, 'active_object', None)
    if obj is None or obj.type != 'MESH':
        return None
    mesh = obj.data
    ca = getattr(mesh, 'color_attributes', None)
    if not ca or ca.active_color is None:
        return None
    vc = ca.active_color
    try:
        return {
            'name': vc.name,
            'domain': vc.domain,
            'data_type': vc.data_type,
            'data_len': len(vc.data),
            'active_index': ca.active_color_index,
        }
    except Exception:
        return None


def get_vcm_temp_attributes(mesh):
    """List of {name, mask, original} for every VCM-ISO_* on `mesh`."""
    out = []
    if mesh is None or not getattr(mesh, 'color_attributes', None):
        return out
    for a in mesh.color_attributes:
        info = get_isolated_channel_ids(a)
        if info is None:
            continue
        out.append({'name': a.name, 'mask': info[1], 'original': info[0]})
    return out


def get_vcm_mode(context):
    """'Normal' / 'Isolated' / 'Unknown'."""
    obj = getattr(context, 'active_object', None)
    if obj is None or obj.type != 'MESH':
        return 'Unknown'
    mesh = obj.data
    ca = getattr(mesh, 'color_attributes', None)
    if not ca or ca.active_color is None:
        return 'Unknown'
    if get_isolated_channel_ids(ca.active_color) is not None:
        return 'Isolated'
    return 'Normal'


def get_current_mask_string(context):
    """Sorted RGBA-order mask string from the panel's Active Channels."""
    scn = getattr(context, 'scene', None)
    if scn is None:
        return ''
    settings = getattr(scn, 'vertex_color_master_settings', None)
    if settings is None:
        return ''
    return ''.join(c for c in valid_channel_ids
                   if c in settings.active_channels)


def get_isolate_dirty_summary(context):
    """(state, iso_name, mask, original) — read-only dirty state probe."""
    obj = getattr(context, 'active_object', None)
    if obj is None or obj.type != 'MESH':
        return ('NONE', None, '', '')
    mesh = obj.data
    state, info = get_iso_dirty_state(mesh)
    if state == 'NONE':
        return ('NONE', None, '', '')
    if isinstance(info, dict):
        return (state, info.get('iso_name'), info.get('mask', ''),
                info.get('original_name', ''))
    return (state, info, '', '')


def get_active_vcm_context_summary(context):
    """High-level read-only snapshot of the live VCM state."""
    obj = getattr(context, 'active_object', None)
    summary = {
        'object': obj.name if obj else None,
        'object_type': obj.type if obj else None,
        'mode': obj.mode if obj else None,
    }
    try:
        summary['selected_count'] = len(context.selected_objects)
    except Exception:
        summary['selected_count'] = 0
    summary['attr'] = get_active_color_attribute_info(context)
    summary['mask'] = get_current_mask_string(context)
    summary['vcm_mode'] = get_vcm_mode(context)
    state, iso_name, iso_mask, iso_orig = get_isolate_dirty_summary(context)
    summary['iso_state'] = state
    summary['iso_name'] = iso_name
    summary['iso_mask'] = iso_mask
    summary['iso_original'] = iso_orig
    if obj is not None and obj.type == 'MESH':
        summary['temp_attrs'] = get_vcm_temp_attributes(obj.data)
    else:
        summary['temp_attrs'] = []
    return summary


def require_corner_domain(vcol, operation_name):
    """Return an error message if vcol uses POINT domain, or None if CORNER.

    Many VCM operations iterate mesh.loops and index vcol.data[loop_index],
    which only produces correct results for CORNER-domain attributes.
    POINT-domain attributes have len(data) == len(vertices), not len(loops),
    so loop-based indexing silently reads/writes wrong data.
    """
    if vcol is not None and vcol.domain == 'POINT':
        return (
            "{} does not support POINT (vertex) domain color attributes yet. "
            "Active attribute '{}' uses POINT domain. "
            "Convert it to Face Corner first "
            "(Object Data Properties > Color Attributes > arrow menu > "
            "Convert Domain)."
            .format(operation_name, vcol.name)
        )
    return None


def report_unsupported_point_domain(operator, operation_name, vcol):
    """Guard wrapper. Returns True if it is safe to proceed.

    Returns False after reporting an ERROR if vcol uses POINT domain, so the
    caller can `if not report_unsupported_point_domain(...): return {'CANCELLED'}`
    BEFORE touching any mesh data.

    Always emits a WARNING-level log line so refusals appear in
    vcm_debug.log even when Debug Mode is off.
    """
    msg = require_corner_domain(vcol, operation_name)
    if msg is None:
        return True
    operator.report({'ERROR'}, msg)
    # HUD notice — lazy import keeps vcm_helpers free of vcm_hud at import time.
    try:
        from . import vcm_hud
        vcm_hud.show_hud(
            bpy.context,
            "POINT domain not supported for this operation",
            'WARNING')
    except Exception:
        pass
    if vcol is not None:
        try:
            data_len = len(vcol.data)
        except Exception:
            data_len = -1
        logger.warning(
            "VCM %s: refused POINT domain attr=%s, data_type=%s, data_len=%d",
            operation_name, vcol.name, vcol.data_type, data_len)
    else:
        logger.warning("VCM %s: refused (no active vcol)", operation_name)
    return False


def rgb_to_luminosity(color):
    # Y = 0.299 R + 0.587 G + 0.114 B
    return color[0] * 0.299 + color[1] * 0.587 + color[2] * 0.114


def convert_rgb_to_luminosity(mesh, src_vcol, dst_vcol, dst_channel_idx, dst_all_channels=False):
    if dst_all_channels:
        for loop_index, loop in enumerate(mesh.loops):
            c = src_vcol.data[loop_index].color
            luminosity = rgb_to_luminosity(c)
            c[0] = luminosity # assigning this way will preserve alpha
            c[1] = luminosity
            c[2] = luminosity
            dst_vcol.data[loop_index].color = c
    else:
        for loop_index, loop in enumerate(mesh.loops):
            luminosity = rgb_to_luminosity(src_vcol.data[loop_index].color)
            dst_vcol.data[loop_index].color[dst_channel_idx] = luminosity


# Blender now uses Attributes for everything. vcol channels are attributes, and colors are vectors
# Must check domain and type are the same between src + destination or conversion is required

# src_attribute: Source attribute (ByteColorAttribute or FloatColorAttribute)
# dst_attribute: Destination attribute (Attribute of same data_type and domain as src_attr)
# src_channel_idx: Source channel (0-3)
# dst_channel_idx: Destination channel (0-3)

# alpha_mode: When copying to all channels, what to do with the alpha channel
# 'USE_SRC' - keep existing alpha value from source
# 'USE_DST' - keep existing alpha value from destination
# 'FILL' - fill alpha with 1.0
#
# Returns True on success, False on failure.
def copy_channel(mesh, src_attribute, dst_attribute, src_channel_idx, dst_channel_idx,
                 swap=False, dst_all_channels=False, alpha_mode='USE_SRC'):
    if src_attribute is None or dst_attribute is None:
        logger.error("VCM copy_channel: src or dst attribute is None")
        return False

    if src_attribute.data_type != dst_attribute.data_type or src_attribute.domain != dst_attribute.domain:
        logger.error(
            "VCM copy_channel: type/domain mismatch — src(%s/%s/%s) vs dst(%s/%s/%s)",
            src_attribute.name, src_attribute.data_type, src_attribute.domain,
            dst_attribute.name, dst_attribute.data_type, dst_attribute.domain)
        return False

    src_len = len(src_attribute.data)
    dst_len = len(dst_attribute.data)
    if src_len != dst_len:
        logger.error(
            "VCM copy_channel: data length mismatch — src=%s/%d vs dst=%s/%d",
            src_attribute.name, src_len, dst_attribute.name, dst_len)
        return False

    if dst_all_channels: # typically used by isolate mode
        if alpha_mode == 'FILL':
            for i, src_av in enumerate(src_attribute.data):
                src_cv = src_av.color[src_channel_idx]
                dst_attribute.data[i].color = [src_cv, src_cv, src_cv, 1.0]
        elif alpha_mode == 'USE_DST':
            for i, src_av in enumerate(src_attribute.data):
                src_cv = src_av.color[src_channel_idx]
                dst_alpha = dst_attribute.data[i].color[3]
                dst_attribute.data[i].color = [src_cv, src_cv, src_cv, dst_alpha]
        else: # 'KEEP_SRC'
            for i, src_av in enumerate(src_attribute.data):
                src_cv = src_av.color[src_channel_idx]
                dst_attribute.data[i].color = [src_cv, src_cv, src_cv, src_av.color[3]]
    else:
        if swap:
            for i in range(src_len):
                src_cv = src_attribute.data[i].color[src_channel_idx]
                dst_cv = dst_attribute.data[i].color[dst_channel_idx]
                src_attribute.data[i].color[src_channel_idx] = dst_cv
                dst_attribute.data[i].color[dst_channel_idx] = src_cv
        else:
            for i, src_av in enumerate(src_attribute.data):
                dst_attribute.data[i].color[dst_channel_idx] = src_av.color[src_channel_idx]

    mesh.update()
    logger.debug(
        "VCM copy_channel: success src=%s[%d] -> dst=%s[%d] "
        "(%s/%s, len=%d, swap=%s, all=%s, alpha=%s)",
        src_attribute.name, src_channel_idx,
        dst_attribute.name, dst_channel_idx,
        src_attribute.data_type, src_attribute.domain, src_len,
        swap, dst_all_channels, alpha_mode)
    return True


def blend_channels(mesh, src_attribute, dst_attribute, src_channel_idx, dst_channel_idx,
                   result_channel_idx, operation='ADD'):
    if src_attribute is None or dst_attribute is None:
        logger.error("VCM blend_channels: src or dst attribute is None")
        return False

    if src_attribute.data_type != dst_attribute.data_type or src_attribute.domain != dst_attribute.domain:
        logger.error(
            "VCM blend_channels: type/domain mismatch — src(%s/%s/%s) vs dst(%s/%s/%s)",
            src_attribute.name, src_attribute.data_type, src_attribute.domain,
            dst_attribute.name, dst_attribute.data_type, dst_attribute.domain)
        return False

    src_len = len(src_attribute.data)
    dst_len = len(dst_attribute.data)
    if src_len != dst_len:
        logger.error(
            "VCM blend_channels: data length mismatch — src=%s/%d vs dst=%s/%d",
            src_attribute.name, src_len, dst_attribute.name, dst_len)
        return False

    if operation == 'ADD':
        for i, src_av in enumerate(src_attribute.data):
            val = src_av.color[src_channel_idx] + dst_attribute.data[i].color[dst_channel_idx]
            dst_attribute.data[i].color[result_channel_idx] = max(0.0, min(val, 1.0))
    elif operation == 'SUB':
        for i, src_av in enumerate(src_attribute.data):
            val = src_av.color[src_channel_idx] - dst_attribute.data[i].color[dst_channel_idx]
            dst_attribute.data[i].color[result_channel_idx] = max(0.0, min(val, 1.0))
    elif operation == 'MUL':
        for i, src_av in enumerate(src_attribute.data):
            val = src_av.color[src_channel_idx] * dst_attribute.data[i].color[dst_channel_idx]
            dst_attribute.data[i].color[result_channel_idx] = val
    elif operation == 'DIV':
        for i in range(src_len):
            src_cv = src_attribute.data[i].color[src_channel_idx]
            dst_cv = dst_attribute.data[i].color[dst_channel_idx]
            val = 1.0 if dst_cv == 0.0 else src_cv / dst_cv
            dst_attribute.data[i].color[result_channel_idx] = max(0.0, min(val, 1.0))
    elif operation == 'LIGHTEN':
        for i in range(src_len):
            src_cv = src_attribute.data[i].color[src_channel_idx]
            dst_cv = dst_attribute.data[i].color[dst_channel_idx]
            dst_attribute.data[i].color[result_channel_idx] = src_cv if src_cv > dst_cv else dst_cv
    elif operation == 'DARKEN':
        for i in range(src_len):
            src_cv = src_attribute.data[i].color[src_channel_idx]
            dst_cv = dst_attribute.data[i].color[dst_channel_idx]
            dst_attribute.data[i].color[result_channel_idx] = src_cv if src_cv < dst_cv else dst_cv
    elif operation == 'MIX':
        for i, src_av in enumerate(src_attribute.data):
            dst_attribute.data[i].color[result_channel_idx] = src_av.color[src_channel_idx]
    else: # UNDEFINED
        logger.error("VCM blend_channels: unknown operation=%s", operation)
        return False

    mesh.update()
    logger.debug(
        "VCM blend_channels: success op=%s src=%s[%d] dst=%s[%d] result[%d] "
        "(%s/%s, len=%d)",
        operation,
        src_attribute.name, src_channel_idx,
        dst_attribute.name, dst_channel_idx, result_channel_idx,
        src_attribute.data_type, src_attribute.domain, src_len)
    return True


# TODO: Properly deal with UV and normal attributes later
def uvs_to_color(mesh, src_uv, dst_vcol, dst_u_idx=0, dst_v_idx=1):
    # by default copy u->r and v->g
    # uv range is -inf, inf so use fmod to remap to 0-1
    for loop_index, loop in enumerate(mesh.loops):
        c = dst_vcol.data[loop_index].color
        uv = src_uv.data[loop_index].uv
        u = fmod(uv[0], 1.0)
        v = fmod(uv[1], 1.0)
        c[dst_u_idx] = u + 1.0 if u < 0 else u
        c[dst_v_idx] = v + 1.0 if v < 0 else v
        dst_vcol.data[loop_index].color = c

    mesh.update()


# TODO: Does this make any sense? Data loss is likely to occur,
# and it's too niche to do properly (create uv islands based on contiguousness)
def color_to_uvs(mesh, src_vcol, dst_uv, src_u_idx=0, src_v_idx=1):
    # by default copy r->u and g->v
    for loop_index, loop in enumerate(mesh.loops):
        c = src_vcol.data[loop_index].color
        uv = [c[src_u_idx], c[src_v_idx]]
        dst_uv.data[loop_index].uv = uv

    mesh.update()


def get_custom_normals(obj):
    # Not entirely sure why this works and [loop.normal for loop in obj.data.loops] doesn't work...
    # note that these normals are in world space... seems to be a huge pain to get tangent space normals
    normals = [loop.normal for loop in [obj.data.calc_normals_split(), obj][1].data.loops]

    return normals


def normals_to_color(mesh, normals, dst_vcol):
    # copy normal xyz to color rgb
    for loop_index, loop in enumerate(mesh.loops):
        c = dst_vcol.data[loop_index].color
        n = normals[loop_index]
        # remap to values that can be displayed
        c[0] = remap(n[0], -1.0, 1.0, 0.0, 1.0)
        c[1] = remap(n[1], -1.0, 1.0, 0.0, 1.0)
        c[2] = remap(n[2], -1.0, 1.0, 0.0, 1.0)
        dst_vcol.data[loop_index].color = c

    mesh.update()


# TODO: Remove this, as it's likely not useful
def color_to_normals(mesh, src_vcol):
    # ensure the mesh has empty split normals
    if not mesh.has_custom_normals:
        mesh.create_normals_split()
        # use_auto_smooth was removed in Blender 4.1+
        if hasattr(mesh, 'use_auto_smooth'):
            mesh.use_auto_smooth = True

    # create a structure that matches the required input of the normals_split_custom_set function
    clnors = [Vector()] * len(mesh.loops)

    for loop_index, loop in enumerate(mesh.loops):
        c = src_vcol.data[loop_index].color
        # remap color to normal range
        n = Vector([remap(channel, 0.0, 1.0, -1.0, 1.0) for channel in c[0:3]])
        n.normalize()
        clnors[loop_index] = n

    mesh.normals_split_custom_set(clnors)
    mesh.update()


def weights_to_color(mesh, src_vgroup_idx, dst_vcol, dst_channel_idx, all_channels=False):
    vertex_weights = [0.0] * len(mesh.vertices)

    # build list of weights for vertex indices
    for i, vert in enumerate(mesh.vertices):
        for group in vert.groups:
            if group.group == src_vgroup_idx:
                vertex_weights[i] = group.weight
                break

    # copy weights to channel of dst color layer
    if not all_channels:
        for loop_index, loop in enumerate(mesh.loops):
            weight = vertex_weights[loop.vertex_index]
            dst_vcol.data[loop_index].color[dst_channel_idx] = weight
    else:
        for loop_index, loop in enumerate(mesh.loops):
            weight = vertex_weights[loop.vertex_index]
            dst_vcol.data[loop_index].color[:3] = [weight]*3

    mesh.update()


def color_to_weights(obj, src_vcol, src_channel_idx, dst_vgroup_idx):
    mesh = obj.data

    # build 2d array containing sum of color channel value, number of values
    # used to calculate average for vertex when setting weights
    vertex_values = [[0.0, 0] for i in range(0, len(mesh.vertices))]

    for loop_index, loop in enumerate(mesh.loops):
        vi = loop.vertex_index
        vertex_values[vi][0] += src_vcol.data[loop_index].color[src_channel_idx]
        vertex_values[vi][1] += 1

    # replace weights of the destination group
    group = obj.vertex_groups[dst_vgroup_idx]
    mode = 'REPLACE'

    for i in range(0, len(mesh.vertices)):
        cnt = vertex_values[i][1]
        weight = 0.0 if cnt == 0.0 else vertex_values[i][0] / cnt
        group.add([i], weight, mode)

    mesh.update()


# ---------------------------------------------------------------------------
# Domain-aware iteration (Iteration 8: controlled POINT support)
# ---------------------------------------------------------------------------
#
# The "simple" channel ops (Fill, Quick Fill, Invert, Posterize, Remap) all
# share the same per-element loop:
#   for di in eligible-data-indices: rewrite selected channels of vcol.data[di]
#
# CORNER attributes index by loop, POINT attributes index by vertex. The
# helpers below abstract that, plus the existing paint-mask filtering
# (face mask via `mesh.use_paint_mask`, vertex mask via
# `mesh.use_paint_mask_vertex`).

def data_length_matches_domain(mesh, vcol):
    """True iff vcol.data length matches its declared domain."""
    if vcol is None:
        return False
    n = len(vcol.data)
    if vcol.domain == 'CORNER':
        return n == len(mesh.loops)
    if vcol.domain == 'POINT':
        return n == len(mesh.vertices)
    return False


def validate_simple_op(operator, mesh, vcol, op_name):
    """Common pre-check for POINT/CORNER simple ops.

    On failure: reports an ERROR, logs WARNING, returns False so the
    caller can `if not validate_simple_op(...): return {'CANCELLED'}`
    BEFORE touching any data — never half-write on validation failure.
    """
    if vcol is None:
        operator.report({'ERROR'}, "{0}: no active color attribute.".format(op_name))
        logger.warning("VCM %s: refused (no active vcol)", op_name)
        return False
    if vcol.domain not in ('CORNER', 'POINT'):
        operator.report(
            {'ERROR'},
            "{0}: domain '{1}' not supported.".format(op_name, vcol.domain))
        logger.warning(
            "VCM %s: refused unknown domain=%s attr=%s",
            op_name, vcol.domain, vcol.name)
        return False
    if not data_length_matches_domain(mesh, vcol):
        operator.report(
            {'ERROR'},
            "{0}: attribute length does not match {1} domain.".format(
                op_name, vcol.domain))
        try:
            data_len = len(vcol.data)
        except Exception:
            data_len = -1
        logger.error(
            "VCM %s: data length mismatch attr=%s domain=%s data_len=%d "
            "loops=%d verts=%d",
            op_name, vcol.name, vcol.domain, data_len,
            len(mesh.loops), len(mesh.vertices))
        return False
    return True


def iter_color_data_indices(mesh, vcol):
    """Yield indices into `vcol.data` to operate on, honoring paint masks.

    CORNER:
      - face paint mask  -> loop indices of selected faces.
      - vertex paint mask -> loops whose vertex is selected.
      - no mask          -> every loop index (== every data index).
    POINT:
      - face paint mask  -> vertex indices belonging to selected faces.
      - vertex paint mask -> vertex indices with .select == True.
      - no mask          -> every vertex index (== every data index).
    """
    domain = vcol.domain
    if domain == 'CORNER':
        if getattr(mesh, 'use_paint_mask', False):
            for face in mesh.polygons:
                if face.select:
                    for li in face.loop_indices:
                        yield li
        elif getattr(mesh, 'use_paint_mask_vertex', False):
            verts = mesh.vertices
            for li, loop in enumerate(mesh.loops):
                if verts[loop.vertex_index].select:
                    yield li
        else:
            for li in range(len(vcol.data)):
                yield li
        return
    if domain == 'POINT':
        if getattr(mesh, 'use_paint_mask', False):
            seen = set()
            for face in mesh.polygons:
                if not face.select:
                    continue
                for vi in face.vertices:
                    if vi not in seen:
                        seen.add(vi)
                        yield vi
        elif getattr(mesh, 'use_paint_mask_vertex', False):
            for vi, v in enumerate(mesh.vertices):
                if v.select:
                    yield vi
        else:
            for vi in range(len(vcol.data)):
                yield vi


def _channel_flags(active_channels):
    return (red_id in active_channels,
            green_id in active_channels,
            blue_id in active_channels,
            alpha_id in active_channels)


# no channel checking. Designed to more efficiently apply a color to mesh
def quick_fill_selected(mesh, vcol, color):
    """RGB-only quick fill. Domain-aware (POINT or CORNER)."""
    for di in iter_color_data_indices(mesh, vcol):
        c = vcol.data[di].color
        c[0] = color[0]
        c[1] = color[1]
        c[2] = color[2]
        vcol.data[di].color = c
    mesh.update()


def fill_selected(mesh, vcol, color, active_channels):
    chR, chG, chB, chA = _channel_flags(active_channels)
    for di in iter_color_data_indices(mesh, vcol):
        c = vcol.data[di].color
        if chR:
            c[0] = color[0]
        if chG:
            c[1] = color[1]
        if chB:
            c[2] = color[2]
        if chA:
            c[3] = color[3]
        vcol.data[di].color = c
    mesh.update()


def invert_selected(mesh, vcol, active_channels):
    chR, chG, chB, chA = _channel_flags(active_channels)
    for di in iter_color_data_indices(mesh, vcol):
        c = vcol.data[di].color
        if chR:
            c[0] = 1.0 - c[0]
        if chG:
            c[1] = 1.0 - c[1]
        if chB:
            c[2] = 1.0 - c[2]
        if chA:
            c[3] = 1.0 - c[3]
        vcol.data[di].color = c
    mesh.update()


def posterize_selected(mesh, vcol, steps, active_channels):
    chR, chG, chB, chA = _channel_flags(active_channels)
    for di in iter_color_data_indices(mesh, vcol):
        c = vcol.data[di].color
        if chR:
            c[0] = posterize(c[0], steps)
        if chG:
            c[1] = posterize(c[1], steps)
        if chB:
            c[2] = posterize(c[2], steps)
        if chA:
            c[3] = posterize(c[3], steps)
        vcol.data[di].color = c
    mesh.update()


def remap_selected(mesh, vcol, min0, max0, min1, max1, active_channels):
    chR, chG, chB, chA = _channel_flags(active_channels)
    for di in iter_color_data_indices(mesh, vcol):
        c = vcol.data[di].color
        if chR:
            c[0] = remap(c[0], min0, max0, min1, max1)
        if chG:
            c[1] = remap(c[1], min0, max0, min1, max1)
        if chB:
            c[2] = remap(c[2], min0, max0, min1, max1)
        if chA:
            c[3] = remap(c[3], min0, max0, min1, max1)
        vcol.data[di].color = c
    mesh.update()


def adjust_hsv(mesh, vcol, h_offset, s_offset, v_offset, colorize):
    if mesh.use_paint_mask:
        selected_faces = [face for face in mesh.polygons if face.select]
        for face in selected_faces:
            for loop_index in face.loop_indices:
                c = Color(vcol.data[loop_index].color[:3])
                if colorize:
                    c.h = fmod(0.5 + h_offset, 1.0)
                else:
                    c.h = fmod(1.0 + c.h + h_offset, 1.0)
                c.s = max(0.0, min(c.s + s_offset, 1.0))
                c.v = max(0.0, min(c.v + v_offset, 1.0))

                new_color = vcol.data[loop_index].color
                new_color[:3] = c
                vcol.data[loop_index].color = new_color
    else:
        vertex_mask = True if mesh.use_paint_mask_vertex else False
        verts = mesh.vertices

        for loop_index, loop in enumerate(mesh.loops):
            if not vertex_mask or verts[loop.vertex_index].select:
                c = Color(vcol.data[loop_index].color[:3])
                if colorize:
                    c.h = fmod(0.5 + h_offset, 1.0)
                else:
                    c.h = fmod(1.0 + c.h + h_offset, 1.0)
                c.s = max(0.0, min(c.s + s_offset, 1.0))
                c.v = max(0.0, min(c.v + v_offset, 1.0))

                new_color = vcol.data[loop_index].color
                new_color[:3] = c
                vcol.data[loop_index].color = new_color

    mesh.update()


# check isolate mode (shouldn't work in isolate mode...)
# set random seed in parent function
def set_island_colors_per_channel(mesh, rgba_mask, merge_similar, vmin, vmax):
    bpy.ops.object.mode_set(mode='EDIT', toggle=False)

    bm = bmesh.from_edit_mesh(mesh)
    bm.faces.ensure_lookup_table()
    color_layer = bm.loops.layers.color.active

    # Find all islands in the mesh
    mesh_islands = []
    selected_faces = ([f for f in bm.faces if f.select])
    faces = selected_faces if mesh.use_paint_mask or mesh.use_paint_mask_vertex else bm.faces
    bpy.ops.mesh.select_all(action="DESELECT")

    while len(faces) > 0:
        # Select linked faces to find island
        faces[0].select_set(True)
        bpy.ops.mesh.select_linked()
        mesh_islands.append([f for f in faces if f.select])
        # Hide the island and update faces
        bpy.ops.mesh.hide(unselected=False)
        faces = [f for f in faces if not f.hide]

    bpy.ops.mesh.reveal()

    island_colors = {} # Island face count : Random color pairs

    for index, island in enumerate(mesh_islands):
        rgba_values = []

        face_count = len(island)
        if merge_similar and face_count in island_colors.keys():
            rgba_values = island_colors[face_count]
        else:
            vrange = abs(vmax - vmin)
            rgba_values = [(vmin + random.random() * vrange) for i in range(4)]
            island_colors[face_count] = rgba_values

        # Set island face colors (probably quite slow, due to list comprehension per face loop)
        for face in island:
            for loop in face.loops:
                c = loop[color_layer]
                c = [v if rgba_mask[i] else c[i] for i, v in enumerate(rgba_values)]
                loop[color_layer] = c

    # Restore selection
    for f in selected_faces:
        f.select = True

    bm.free()
    bpy.ops.object.mode_set(mode='VERTEX_PAINT', toggle=False)


def get_layer_info(context):
    settings = context.scene.vertex_color_master_settings

    d = ' ' # delimiter
    s = settings.src_vcol_id
    src_type = s[:s.find(d)]
    src_id = s[s.find(d) + 1:]

    s = settings.dst_vcol_id
    dst_type = s[:s.find(d)]
    dst_id = s[s.find(d) + 1:]

    return [src_type, src_id, dst_type, dst_id]


# TODO: This needs rewriting due to change from vertex_colors to color_attributes
# It must support POINT or CORNER with BYTE_COLOR or FLOAT_COLOR combinations
def get_validated_input(context, get_src, get_dst):
    settings = context.scene.vertex_color_master_settings
    obj = context.active_object
    mesh = obj.data

    rv = {}
    message = None

    layer_info = get_layer_info(context)
    src_type = layer_info[0]
    src_id = layer_info[1]
    dst_type = layer_info[2]
    dst_id = layer_info[3]

    # are these conditions actually possible?
    if message is None:
        if (src_type == type_vcol or dst_type == type_vcol) and mesh.color_attributes is None:
            message = "Object has no vertex colors."
        if (src_type == type_vgroup or dst_type == type_vgroup) and obj.vertex_groups is None:
            message = "Object has no vertex groups."
        if (src_type == type_uv or dst_type == type_uv) and mesh.uv_layers is None:
            message = "Object has no uv layers."

    # validate src
    if get_src and message is None:
        if src_type == type_vcol:
            if src_id in mesh.color_attributes:
                rv['src_vcol'] = mesh.color_attributes[src_id]
                rv['src_channel_idx'] = channel_id_to_idx(settings.src_channel_id)
            else:
                message = "Src color layer is not valid."
        elif src_type == type_uv:
            if src_id in mesh.uv_layers:
                rv['src_uv'] = mesh.uv_layers[src_id]
            else:
                message = "Src UV layer is not valid."
        else:
            src_vgroup_idx = -1
            for group in obj.vertex_groups:
                if group.name == src_id:
                    src_vgroup_idx = group.index
                    rv['src_vgroup_idx'] = src_vgroup_idx
                    break
            if src_vgroup_idx < 0:
                message = "Src vertex group is not valid."

    # validate dst
    if get_dst and message is None:
        if dst_type == type_vcol:
            if dst_id in mesh.color_attributes:
                rv['dst_vcol'] = mesh.color_attributes[dst_id]
                rv['dst_channel_idx'] = channel_id_to_idx(settings.dst_channel_id)
            else:
                message = "Dst color layer is not valid."
        elif dst_type == type_uv:
            if dst_id in mesh.uv_layers:
                rv['dst_uv'] = mesh.uv_layers[dst_id]
            else:
                message = "Dst UV layer is not valid."
        else:
            dst_vgroup_idx = -1
            for group in obj.vertex_groups:
                if group.name == dst_id:
                    dst_vgroup_idx = group.index
                    rv['dst_vgroup_idx'] = dst_vgroup_idx
                    break
            if dst_vgroup_idx < 0:
                message = "Dst vertex group is not valid."

    rv['error'] = message
    return rv


# ---------------------------------------------------------------------------
# Geometry Mask Generator (Iteration 10) — topology-based, NOT AO
# ---------------------------------------------------------------------------
#
# Detection: every manifold edge with two adjacent faces gets a signed
# dihedral angle via bmesh.edge.calc_face_angle_signed (positive = convex,
# negative = concave). Edges whose |deviation from 180°| is below the
# user threshold contribute zero.
#
# Spread: detected edges seed their two endpoint vertices with the
# normalized intensity. A multi-source BFS over `build_vertex_neighbors`
# propagates distances out to `width_rings`. Per-vertex output is the
# strongest seed value times the falloff at that distance.
#
# Per-loop projection: CORNER attributes get `value[loop.vertex_index]`.
# This MVP refuses POINT-domain attributes — caller must pre-check.
#
# Hard topology cases handled defensively:
#   - non-manifold / boundary edges:  skipped, counted in stats
#   - exactly-flat edges:             skipped (below threshold)
#   - n-gons / triangles:             handled by bmesh natively
#   - disconnected islands:           BFS naturally stays in island

def _geom_falloff(t, mode):
    """t is normalized distance in [0..1]. Returns intensity multiplier."""
    if t <= 0.0:
        return 1.0
    if t >= 1.0:
        return 0.0
    x = 1.0 - t
    if mode == 'LINEAR':
        return x
    if mode == 'SHARP':
        return x * x
    # SMOOTH (smoothstep on x)
    return x * x * (3.0 - 2.0 * x)


def detect_geom_seed_edges(mesh, threshold_deg):
    """Build per-vertex seed dictionaries from manifold edge dihedrals.

    Returns (seeds_concave, seeds_convex, stats) where seeds_* map vertex
    index -> max intensity in [0..1]. Stats include manifold / non-manifold
    counts so the caller can log them.
    """
    seeds_concave = {}
    seeds_convex = {}
    stats = {
        'edges_total': 0,
        'edges_manifold': 0,
        'edges_non_manifold': 0,
        'edges_below_threshold': 0,
        'edges_concave': 0,
        'edges_convex': 0,
    }

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        for e in bm.edges:
            stats['edges_total'] += 1
            link_faces = e.link_faces
            if len(link_faces) != 2 or not e.is_manifold:
                stats['edges_non_manifold'] += 1
                continue
            stats['edges_manifold'] += 1
            try:
                signed = e.calc_face_angle_signed(0.0)  # radians
            except Exception:
                stats['edges_non_manifold'] += 1
                continue
            deg = math.degrees(abs(signed))
            if deg < threshold_deg:
                stats['edges_below_threshold'] += 1
                continue
            denom = max(0.001, 90.0 - threshold_deg)
            intensity = (deg - threshold_deg) / denom
            if intensity > 1.0:
                intensity = 1.0
            if intensity <= 0.0:
                continue
            if signed >= 0.0:
                stats['edges_convex'] += 1
                target = seeds_convex
            else:
                stats['edges_concave'] += 1
                target = seeds_concave
            for v in e.verts:
                vi = v.index
                cur = target.get(vi, 0.0)
                if intensity > cur:
                    target[vi] = intensity
    finally:
        bm.free()

    return seeds_concave, seeds_convex, stats


def _geom_bfs_field(seeds, neighbors, width_rings, falloff_mode):
    """Multi-source BFS limited to `width_rings`. Returns list[n_verts] of
    intensity * falloff(dist/width)."""
    n = len(neighbors)
    if not seeds:
        return [0.0] * n
    dist = [-1] * n
    seed_val = [0.0] * n
    queue = []
    for vi, v in seeds.items():
        if 0 <= vi < n and dist[vi] == -1:
            dist[vi] = 0
            seed_val[vi] = v
            queue.append(vi)

    head = 0
    while head < len(queue):
        cur = queue[head]
        head += 1
        d = dist[cur]
        if d >= width_rings:
            continue
        cur_seed = seed_val[cur]
        for nb in neighbors[cur]:
            if dist[nb] == -1:
                dist[nb] = d + 1
                seed_val[nb] = cur_seed
                queue.append(nb)
            elif dist[nb] == d + 1 and cur_seed > seed_val[nb]:
                # tie at same ring distance: stronger nearest seed wins
                seed_val[nb] = cur_seed

    out = [0.0] * n
    width = max(1, width_rings)
    for vi in range(n):
        if dist[vi] < 0:
            continue
        t = dist[vi] / width
        out[vi] = seed_val[vi] * _geom_falloff(t, falloff_mode)
    return out


def compute_geometry_masks(mesh, threshold_deg, width_rings, falloff_mode):
    """Return (per_vert_concav, per_vert_convex, stats)."""
    seeds_concave, seeds_convex, stats = detect_geom_seed_edges(
        mesh, threshold_deg)
    try:
        neighbors = build_vertex_neighbors(mesh)
    except Exception as e:
        logger.error("VCM compute_geometry_masks: neighbors build failed: %s", e)
        return None, None, stats
    concav = _geom_bfs_field(
        seeds_concave, neighbors, width_rings, falloff_mode)
    convex = _geom_bfs_field(
        seeds_convex, neighbors, width_rings, falloff_mode)
    stats['seeds_concave'] = len(seeds_concave)
    stats['seeds_convex'] = len(seeds_convex)
    return concav, convex, stats


def _blend_value(existing, generated, mode):
    """Per-element blend. Caller already multiplied generated by strength."""
    if generated <= 0.0 and mode != 'REPLACE':
        return existing
    if mode == 'REPLACE':
        v = generated
    elif mode == 'ADD':
        v = existing + generated
    else:  # MAX
        v = generated if generated > existing else existing
    if v < 0.0:
        v = 0.0
    elif v > 1.0:
        v = 1.0
    return v


def write_geometry_masks(mesh, vcol, concav_v, convex_v, params):
    """Project per-vertex masks to per-loop CORNER attribute and blend.

    `params` keys:
      strength, blend_mode,
      concav_chan, convex_chan  — channel id letter or 'NONE'
      iso_mask                  — current iso mask string or '' if not iso
      smooth_after, smooth_iters
    Returns True on success, False on validation failure.
    """
    if vcol is None or vcol.domain != 'CORNER':
        logger.error("VCM write_geometry_masks: requires CORNER vcol")
        return False
    n_loops = len(vcol.data)
    if n_loops != len(mesh.loops):
        logger.error(
            "VCM write_geometry_masks: data/loop length mismatch "
            "(data=%d, loops=%d)", n_loops, len(mesh.loops))
        return False
    n_verts = len(mesh.vertices)
    if (concav_v is not None and len(concav_v) != n_verts) or \
            (convex_v is not None and len(convex_v) != n_verts):
        logger.error(
            "VCM write_geometry_masks: per-vertex array size mismatch")
        return False

    strength = max(0.0, min(1.0, float(params.get('strength', 1.0))))
    blend = params.get('blend_mode', 'MAX')
    concav_chan = params.get('concav_chan', 'NONE')
    convex_chan = params.get('convex_chan', 'NONE')
    iso_mask = params.get('iso_mask', '') or ''

    # Combine generated values per channel (max if both target same channel)
    per_channel = {}  # ch_idx -> per-loop float list

    def add_contribution(ch_letter, per_vert):
        if ch_letter == 'NONE' or ch_letter not in valid_channel_ids:
            return
        ci = channel_id_to_idx(ch_letter)
        arr = per_channel.get(ci)
        if arr is None:
            arr = [0.0] * n_loops
            per_channel[ci] = arr
        for li, loop in enumerate(mesh.loops):
            v = per_vert[loop.vertex_index] * strength
            if v > arr[li]:
                arr[li] = v

    if concav_v is not None:
        add_contribution(concav_chan, concav_v)
    if convex_v is not None:
        add_contribution(convex_chan, convex_v)

    if not per_channel:
        logger.warning(
            "VCM write_geometry_masks: nothing to write "
            "(both outputs NONE or zero contribution)")
        return False

    # Single-channel iso: writing target channel into iso temp must broadcast
    # to the visible RGB grayscale to keep apply / dirty-check semantics.
    is_single_iso = (len(iso_mask) == 1)
    broadcast_to_rgb = is_single_iso and len(per_channel) == 1

    # Iter11: when caller asks, broadcast each generated effect across all
    # channels of the iso mask. Single-iso path already does broadcast via
    # broadcast_to_rgb above. Multi-iso: replicate per_channel[iso_mask[0]]
    # arrays into all iso mask channel indices so every iso-mask channel
    # receives the same generated value.
    iso_broadcast_mask_channels = bool(
        params.get('iso_broadcast_mask_channels', False))
    if iso_broadcast_mask_channels and not is_single_iso and len(iso_mask) > 1:
        # Take whatever single per_channel entry the caller provided and
        # spread it to every iso_mask channel.
        if per_channel:
            src_arr = next(iter(per_channel.values()))
            per_channel = {}
            for ch in iso_mask:
                per_channel[channel_id_to_idx(ch)] = src_arr

    written_indices = sorted(per_channel.keys())

    if broadcast_to_rgb:
        gen_arr = next(iter(per_channel.values()))
        for li in range(n_loops):
            c = vcol.data[li].color
            existing = c[0]  # broadcast invariant
            new_v = _blend_value(existing, gen_arr[li], blend)
            c[0] = new_v
            c[1] = new_v
            c[2] = new_v
            vcol.data[li].color = c
    else:
        for li in range(n_loops):
            c = vcol.data[li].color
            for ci in written_indices:
                existing = c[ci]
                c[ci] = _blend_value(existing, per_channel[ci][li], blend)
            vcol.data[li].color = c

    mesh.update()

    if params.get('smooth_after', False) and params.get('smooth_iters', 0) > 0:
        if broadcast_to_rgb:
            smooth_mask = 'RGB'
        else:
            smooth_mask = ''.join(
                valid_channel_ids[ci] for ci in written_indices)
        try:
            blur_channels_mask_vertex(
                mesh, vcol, smooth_mask, 0.5,
                int(params.get('smooth_iters', 1)))
        except Exception as e:
            logger.warning(
                "VCM write_geometry_masks: smoothing failed (%s) — "
                "leaving raw output.", e)

    logger.info(
        "VCM write_geometry_masks: wrote channels=%s strength=%.3f "
        "blend=%s broadcast=%s iso_broadcast=%s",
        written_indices, strength, blend, broadcast_to_rgb,
        iso_broadcast_mask_channels)
    return True
