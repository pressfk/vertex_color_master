Fresh-profile brush color sync hotfix on top of v0.11.2.

## New

- **Brush sync diagnostics operator.**
  `vertexcolormaster.copy_brush_sync_diagnostics` (F3 search:
  *"Copy VCM Brush Sync Diagnostics"*) copies a compact snapshot of
  Blender version, active object/mode, active Vertex Paint brush
  name, `brush.color`, `brush.secondary_color`,
  `unified_paint_settings.use_unified_color`, `ups.color`,
  `ups.secondary_color`, the VCM panel color/value props, and the
  current isolate / channel state to the system clipboard for bug
  reports.

## Fixes

- **VCM color row now respects Unified Paint Settings.**
  On clean Blender 4.5.x profiles where
  `tool_settings.unified_paint_settings.use_unified_color` is
  enabled, the standard-mode color swatches in the VCM panel were
  bound to `brush.color` / `brush.secondary_color`, while Blender's
  native brush panel, Fill (`paint.vertex_color_set`), and the X /
  Flip operator read/wrote `unified_paint_settings.color`. This
  caused the reported fresh-profile symptoms: an apparent
  black/white vs. white/black mismatch at startup, VCM color edits
  that did not affect the painted brush, Fill / Ctrl+X using a
  different color than the swatch, and X / Flip "snapping" the VCM
  swatches back to the unified pair.
  The standard-mode color row is now bound to whichever color block
  Blender actually paints with — `unified_paint_settings.color` when
  unified color is on, `brush.color` otherwise — matching Blender's
  own brush panel and the helper-driven X / Flip / Fill paths.
- **No-active-brush safety in panel.** The Strength row and the
  Affect Alpha toggle no longer attempt to bind to `None` on fresh
  profiles where `tool_settings.vertex_paint.brush` has not been
  resolved yet; an `INFO` placeholder is shown instead.

## Known issues / follow-up

- Geometry Mask convex/concave BFS artifact still unfixed (deferred
  to the continuous backend rework).
- Blur and gradient quality remain known limitations.
- Boundary Loop generator and the clipboard-style transfer / buffer
  system are still future work.

## Manual test checklist

Run on a clean Blender 4.5.1 user profile:

1. Open Blender on a fresh profile, install the
   `vertex_color_master.zip` asset, enable the addon. Confirm
   register has no traceback.
2. Add a default cube, enter Vertex Paint mode, open the VCM panel.
3. Confirm the VCM color swatches and Blender's own brush panel
   show the **same** primary / secondary colors immediately, with
   no need to press X first.
4. Edit the VCM primary swatch → Blender's brush panel updates
   instantly. Paint a stroke → the stroke uses the VCM color.
5. Edit Blender's primary swatch → VCM swatch updates instantly.
6. Press **Ctrl+X / Fill With Color** → fill uses the visible
   swatch color.
7. Press **X / Flip** → primary and secondary swap; previously-set
   VCM colors are not silently overwritten by an unrelated unified
   pair.
8. Toggle `Edit → Preferences → … → Unified Paint Settings →
   Use Unified Color` ON and OFF; verify the VCM swatch tracks
   whichever block is active each time.
9. Run *"Copy VCM Brush Sync Diagnostics"* via F3, paste into a
   text editor, confirm output looks sane.

## Installation

Install the `vertex_color_master.zip` asset attached to the
GitHub Release via **Edit → Preferences → Add-ons → Install…**.
Do **not** use GitHub's auto-generated source archive. Do **not**
install via the Extension Repository.
