# UI primitives

Small, generic building blocks with no knowledge of Wi-Fi or test runs. Pages and the domain
components in `../` (ChannelMap, ResultsGrid, CountsBar, ...) are built from these.

| Component | Use it for | Key props |
|---|---|---|
| `BaseButton` | Every button that is not a link | `variant`: primary, secondary, ghost, danger; `size`: md, sm |
| `SegmentedControl` | Picking one of 2 to 5 options (band, view, filter) | `v-model`, `options`, `label` or `labelledby`; `#option` slot |
| `Pager` | Page numbers under a list | `page`, `pages`, `busy`, `canNext`; emits `go` |
| `ModelTag` | Marking estimated, not measured, numbers | `title` (the explanation) |

Rules:
- Colours, radius, shadow and fonts come only from the tokens in `src/style.css` (`var(--accent)`, ...),
  so light and dark mode work without extra CSS.
- A primitive owns its own styles. A page may place it (margin, grid) but does not restyle it.
- Accessibility lives in the primitive: `SegmentedControl` is a radio group with arrow keys,
  `Pager` marks the current page with `aria-current`.
