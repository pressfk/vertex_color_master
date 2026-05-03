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

red_id = 'R'
green_id = 'G'
blue_id = 'B'
alpha_id = 'A'

valid_channel_ids = 'RGBA'

type_vcol = 'VCOL'
type_vgroup = 'VGROUP'
type_uv = 'UV'
type_normal = 'NORMALS'
valid_layer_types = [type_vcol, type_vgroup, type_uv, type_normal]

channel_items = ((red_id, "R", ""),
                 (green_id, "G", ""),
                 (blue_id, "B", ""),
                 (alpha_id, "A", ""))

brush_blend_mode_items = (('MIX', "Mix", ""),
                          ('ADD', "Add", ""),
                          ('SUB', "Sub", ""),
                          ('MUL', "Multiply", ""),
                          ('BLUR', "Blur", ""),
                          ('LIGHTEN', "Lighten", ""),
                          ('DARKEN', "Darken", ""))

channel_blend_mode_items = (('ADD', "Add", ""),
                            ('SUB', "Subtract", ""),
                            ('MUL', "Multiply", ""),
                            ('DIV', "Divide", ""),
                            ('LIGHTEN', "Lighten",  ""),
                            ('DARKEN', "Darken", ""),
                            ('MIX', "Mix", ""))

default_brush_name = 'Draw' # Changed to Add in 2.81 for some reason


# ---------------------------------------------------------------------------
# Curated hotkey input (Iteration 7)
# ---------------------------------------------------------------------------
#
# Free-text key entry was fragile: the user could type 'one' or 'F13' and
# silently break the keymap. The Enum below gives a single source of truth
# of permitted Blender event identifiers, and KEY_DISPLAY renders them in
# human-friendly form ('1' instead of 'ONE', 'Enter' instead of 'RET').
#
# IDs MUST match Blender's bpy.types.Event.type identifiers exactly so the
# keymap registrar can pass them straight through to keymap_items.new().

_LETTER_IDS = tuple(chr(c) for c in range(ord('A'), ord('Z') + 1))
_NUMBER_IDS = (
    ('ZERO', '0'), ('ONE', '1'), ('TWO', '2'), ('THREE', '3'),
    ('FOUR', '4'), ('FIVE', '5'), ('SIX', '6'), ('SEVEN', '7'),
    ('EIGHT', '8'), ('NINE', '9'),
)
_FKEY_IDS = tuple('F{0}'.format(i) for i in range(1, 13))
_NAMED_IDS = (
    ('SPACE', 'Space'),
    ('TAB', 'Tab'),
    ('RET', 'Enter'),
    ('BACK_SPACE', 'Backspace'),
    ('DEL', 'Delete'),
    ('HOME', 'Home'),
    ('END', 'End'),
    ('PAGE_UP', 'Page Up'),
    ('PAGE_DOWN', 'Page Down'),
    ('LEFT_ARROW', 'Left'),
    ('RIGHT_ARROW', 'Right'),
    ('UP_ARROW', 'Up'),
    ('DOWN_ARROW', 'Down'),
    ('MINUS', '-'),
    ('EQUAL', '='),
    ('LEFT_BRACKET', '['),
    ('RIGHT_BRACKET', ']'),
    ('SEMI_COLON', ';'),
    ('QUOTE', "'"),
    ('COMMA', ','),
    ('PERIOD', '.'),
    ('SLASH', '/'),
    ('BACK_SLASH', '\\'),
    ('GRLESS', '`'),
)


def _build_key_enum():
    items = [('NONE', 'None', 'No binding')]
    for k in _LETTER_IDS:
        items.append((k, k, ''))
    for kid, label in _NUMBER_IDS:
        items.append((kid, label, ''))
    for k in _FKEY_IDS:
        items.append((k, k, ''))
    for kid, label in _NAMED_IDS:
        items.append((kid, label, ''))
    return tuple(items)


KEY_ENUM_ITEMS = _build_key_enum()
VALID_KEY_IDS = frozenset(it[0] for it in KEY_ENUM_ITEMS)

KEY_DISPLAY = {
    kid: label for kid, label, _ in KEY_ENUM_ITEMS if kid != 'NONE'
}
# Letters and F-keys use themselves as display, so KEY_DISPLAY already covers
# the full set above via _build_key_enum's items.


def key_display(key, mods):
    """Render a key + modifier dict as 'Ctrl + Shift + Alt + 1'.

    `mods` is a dict-like with optional 'ctrl', 'shift', 'alt', 'oskey'
    truthy keys. Unknown key ids fall back to their raw identifier so the
    user sees something instead of an empty cell.
    """
    parts = []
    if mods.get('ctrl'):
        parts.append('Ctrl')
    if mods.get('shift'):
        parts.append('Shift')
    if mods.get('alt'):
        parts.append('Alt')
    if mods.get('oskey'):
        parts.append('OS')
    if key and key != 'NONE':
        parts.append(KEY_DISPLAY.get(key, key))
    if not parts:
        return 'None'
    return ' + '.join(parts)

 # VCM-ISO_<CHANNEL_ID>_<VCOL_ID> ex. VCM-ISO_R_Col
isolate_mode_name_prefix = 'VCM-ISO'

# Custom mesh ID-property key holding the dirty-detection metadata for the
# currently active isolate. Stored on the mesh datablock so it survives
# Blender's depsgraph updates and .blend save/load.
iso_meta_key = "vcm_iso_meta"

# Roll order for single-channel isolate cycling (R → G → B → A → R).
roll_channel_sequence = ('R', 'G', 'B', 'A')

# unpack into color_attributes.new() using * operator
color_attribute_default = ("Color", 'BYTE_COLOR', 'CORNER')