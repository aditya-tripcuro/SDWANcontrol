---
design-tokens:
  color:
    background:
      canvas:
        value: '#020617' # Slate 950
      surface:
        value: '#0f172a' # Slate 900
      overlay:
        value: '#1e293b' # Slate 800
    text:
      strong:
        value: '#f8fafc' # Slate 50
      muted:
        value: '#94a3b8' # Slate 400
    brand:
      primary:
        value: '#334155' # Slate 700
    status:
      error:
        value: '#f87171' # Red 400
  typography:
    family:
      base:
        value: 'system-ui, -apple-system, sans-serif'
    weight:
      bold:
        value: 700
    size:
      display:
        value: '1.5rem'
      header:
        value: '1.25rem'
      body:
        value: '1rem'
  spacing:
    page:
      value: '1.5rem'
    card:
      value: '2rem'
    element:
      value: '1rem'
    stack:
      value: '0.25rem'
  radius:
    small:
      value: '0.25rem'
    base:
      value: '0.375rem'
---

# WANControl v2 Design System

WANControl v2 employs a high-contrast, utility-first design system optimized for network administration and long-term monitoring. The visual identity is rooted in a "Dark Mode by Default" philosophy to minimize eye strain in technical environments.

## Visual Identity

### Aesthetic: Industrial Precision
The interface uses a restricted "Slate" palette from the deep canvas (#020617) to the primary text (#f8fafc). This monochrome-leaning approach ensures that when colors *are* used (such as the #f87171 red for error alerts), they carry maximum semantic weight and immediately draw the operator's attention.

### Design Intent: Functional Density
The layout prioritizes information density over white space. Standard page padding is kept tight (1.5rem) to ensure that network logs, metric tables, and interface statuses remain visible without excessive scrolling. Components use subtle border radii (0.375rem) to provide a modern feel without leaning into the playfulness of consumer-grade applications.

## Component Strategy

### Surfaces
- **Canvas**: The root level of the application, used for the background of the entire viewport.
- **Surface**: The secondary level used for cards, forms, and primary content containers.
- **Overlay**: The tertiary level used for interactive elements like input fields and code blocks.

### Typography
The system relies on system sans-serif stacks to ensure zero-latency font rendering. Typographic hierarchy is driven primarily by weight and color contrast rather than large scale changes, maintaining a consistent rhythm across complex data views.
