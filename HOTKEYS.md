# Vertex Color Master — Hotkeys

All VCM hotkeys live in the **Vertex Paint** keymap. They are inactive in any
other mode.

## Defaults (left-hand reachable)

| Action                          | Key   | Modifiers | Default |
|---------------------------------|-------|-----------|---------|
| Pie Menu                        | V     | —         | ON      |
| Flip Brush Colors               | X     | —         | ON      |
| Isolate R                       | 1     | Alt       | ON      |
| Isolate G                       | 2     | Alt       | ON      |
| Isolate B                       | 3     | Alt       | ON      |
| Isolate A                       | 4     | Alt       | ON      |
| Select / Restore RGBA           | 5     | Alt       | ON      |
| Apply Isolated                  | E     | Alt       | ON      |
| Discard Isolated                | Q     | Alt       | ON      |
| Cleanup VCM Temp Attributes     | C     | Alt       | OFF     |
| Roll Isolate Next               | W     | Alt       | ON      |
| Roll Isolate Previous           | S     | Alt       | ON      |

`Cleanup` is OFF by default to avoid surprising data removal until the user
opts in.

`Roll Isolate Next/Previous` cycle through the single-channel isolates
R → G → B → A → R (Next) and R → A → B → G → R (Previous). They reuse the
same smart-switch dirty/clean detection as `Alt+1..4` — clean isolates
auto-discard and switch silently, dirty isolates block until the user
Applies or Discards.

## Customizing

Open `Edit → Preferences → Add-ons → Vertex Color Master`. The **Hotkeys**
panel lets you, per action:

- toggle the binding on/off
- click **Rebind** and press the desired key combination once
- click the **Reset** arrow to restore that single action's default

Press **Esc** during Rebind to cancel without changing anything. Pure
modifier presses (Ctrl / Shift / Alt / Cmd alone) are ignored during
capture — the next non-modifier key, plus whichever modifiers are held at
that moment, is what gets stored.

The current binding is shown in human-readable form
(`Alt + 1`, `Ctrl + Shift + B`) — there is no free-text key field, so
typos like `one` or `F13` cannot reach the keymap.

Changes apply immediately — no restart, no F8 reload required. Old keymap
items are removed before the new ones are registered.

## Reset

Click **Reset to Defaults** in the Hotkeys panel header to restore every
binding to the table above.

## Conflicts

The addon does not arbitrate keymap conflicts. If a configured combination
overlaps with another active keymap item in `Vertex Paint`, VCM logs a
warning but still registers its binding. Resolve the conflict via
`Preferences → Keymap → Vertex Paint`, where every VCM operator is editable
through Blender's native UI.

## Mode scope

Hotkeys are registered against the `Vertex Paint` keymap only. They do not
fire in Object Mode, Edit Mode, Sculpt, or Texture Paint.
