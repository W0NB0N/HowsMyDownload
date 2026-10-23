# Design tokens

Both clients use the same dark "terminal" look: near-black surfaces, monospace type, one purple accent and green for live activity. The values below are the source of truth in code:

- Extension: CSS custom properties in [`extension/popup/popup.css`](../extension/popup/popup.css)
- Android: [`android/.../ui/theme/Color.kt`](../android/app/src/main/java/com/notifs/app/ui/theme/Color.kt)

| Token (CSS / Kotlin) | Value | Used for |
|---|---|---|
| `--bg-canvas` / `BgCanvas` | `#09090c` | Page background |
| `--bg-card` / `BgCard` | `#111116` | Cards and sections |
| `BgElevated` | `#181820` | Download rows, secondary buttons |
| `--border-subtle` / `BorderSubtle` | `#23232c` | Hairline borders |
| `--purple-brand` / `PurpleBrand` | `#8a05ff` | Primary actions, focus, active switches, notification accent colour |
| `--purple-light` / `PurpleLight` | `#c084fc` | `--flag` prefixes, completed state, Restart |
| `--green-neon` / `GreenNeon` | `#61cf92` | Downloading state, live/online indicators, Resume, QR viewfinder |
| `StatePaused` (literal `#fbbf24` in CSS) | `#fbbf24` | Paused state, reconnecting, Pause, in-flight commands |
| `StateFailed` | `#f87171` | Failed state, errors, unpair |
| `--text-white` / `TextWhite` | `#ffffff` | Titles, filenames |
| `--text-dim` / `TextDim` | `#a1a1aa` | Secondary text, stats |
| `--text-muted` / `TextMuted` | `#52525b` | `// comments`, inactive indicators |

**Type.** Monospace throughout (`ui-monospace, "JetBrains Mono", Menlo, Consolas`; `FontFamily.Monospace` on Android). Labels read like CLI flags (`--pairing [ pc_relay ]`), and buttons like commands (`> scan qr code`).

**Icons.** 11×11 pixel-grid glyphs. The source art is in [`assets/`](../assets). [`tools/process_app_icon.py`](../tools/process_app_icon.py) scales `assets/icon.png` into the extension and Android launcher icons.
