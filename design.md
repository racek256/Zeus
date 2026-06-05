# Design System Specification: The Architect of Trust

## 1. Overview & Creative North Star
The Creative North Star for this design system is **"Architectural Authority."** 

In the world of corporate security, trust is not built with flashy decorations, but through precision, structural integrity, and clarity. This system moves beyond the "generic SaaS" look by adopting a high-end editorial aesthetic. We treat the digital interface like a modern skyscraper: monolithic, transparent where necessary, and fundamentally unshakeable. 

We break the "template" look by utilizing intentional asymmetry, massive typographic scales, and a "No-Line" philosophy that relies on tonal depth rather than structural borders. The result is an enterprise-grade experience that feels bespoke, premium, and authoritative.

---

## 2. Colors & Tonal Depth
Our palette is rooted in high-contrast extremes: the deep charcoal of `on_background` (#1C1B1B) and the pristine clarity of `surface` (#FCF9F8). The corporate blue (`primary_container`: #1E40AF) is used as a surgical strike—an accent that guides the eye to the most critical actions.

### The "No-Line" Rule
Standard UI relies on 1px borders to separate content. **This design system prohibits them.** Boundaries must be defined solely through background color shifts or subtle tonal transitions. For example, a `surface_container_low` section sitting on a `surface` background provides all the separation a user needs without the visual "noise" of a line.

### Surface Hierarchy & Nesting
Treat the UI as a series of physical layers—like stacked sheets of fine paper. 
- **Base:** `surface` (#FCF9F8)
- **Secondary Content:** `surface_container_low` (#F6F3F2)
- **Elevated Cards:** `surface_container_lowest` (#FFFFFF)
- **Deep Insets:** `surface_container_high` (#EBE7E7)

### The "Glass & Gradient" Rule
To inject "soul" into the enterprise environment, use Glassmorphism for floating elements (modals, dropdowns) by applying `surface_container_lowest` at 80% opacity with a `20px` backdrop blur. For primary CTAs, use a subtle linear gradient from `primary` (#00288E) to `primary_container` (#1E40AF) at a 135-degree angle to add a sophisticated, three-dimensional polish.

---

## 3. Typography
We use a dual-typeface system to balance architectural beauty with functional legibility.

- **Display & Headlines (Manrope):** Chosen for its geometric precision. Use `display-lg` (3.5rem) with tight letter-spacing (-0.02em) to create an authoritative, editorial "header" feel.
- **Body & Labels (Inter):** The workhorse. Inter provides maximum legibility for complex security data. Use `body-md` (0.875rem) for standard text to maintain a sophisticated, airy feel.

**Editorial Hierarchy:** Always pair a massive `display-sm` headline with a significantly smaller `label-md` uppercase sub-header. This extreme contrast is a hallmark of high-end design.

---

## 4. Elevation & Depth
Depth is achieved through **Tonal Layering** rather than traditional drop shadows.

- **The Layering Principle:** Place a `surface_container_lowest` card on top of a `surface_container_low` background. The slight shift in lightness creates a natural "lift" that feels integrated, not pasted on.
- **Ambient Shadows:** When a true floating effect is required (e.g., a critical security modal), use an ultra-diffused shadow: `box-shadow: 0 20px 40px rgba(28, 27, 27, 0.06);`. The shadow color is a low-opacity version of `on_surface`, mimicking natural ambient light.
- **The "Ghost Border":** If a container requires extra definition for accessibility, use the `outline_variant` token at 15% opacity. Never use a 100% opaque border.
- **Glassmorphism:** Use `surface_tint` at 5% opacity on top of glass elements to give them a "tempered glass" feel, reinforcing the security theme.

---

## 5. Components

### Buttons
- **Primary:** Gradient fill (`primary` to `primary_container`), white text, `md` (0.375rem) roundedness. No border.
- **Secondary:** `surface_container_highest` fill with `on_surface` text.
- **Tertiary:** Ghost style. No background, `primary` text, bold weight.

### Input Fields
- **Styling:** Use a `surface_container_low` background with a `Ghost Border` (15% `outline_variant`). 
- **Focus State:** The border transitions to 100% `primary_container` with a 2px outer "glow" of the same color at 10% opacity.

### Cards & Lists
- **Prohibition:** Divider lines are strictly forbidden. 
- **Alternative:** Separate list items using 8px of vertical whitespace or by alternating backgrounds between `surface` and `surface_container_low`.
- **Nesting:** Place `surface_container_lowest` cards inside a `surface_container_high` wrapper to create a "well" effect for data-heavy dashboards.

### Trust Indicators (New Component)
- **The Security Shield:** A small, semi-transparent chip using `primary_fixed_dim` background and `on_primary_fixed` text, used to denote "Verified" or "Encrypted" status. It should use `full` roundedness (9999px).

---

## 6. Do’s and Don’ts

### Do:
- **Embrace White Space:** Use 2x the padding you think you need. Space is a premium asset that signals confidence.
- **Use Intentional Asymmetry:** Align text to the left but place supporting data or imagery on a slightly offset grid to create visual interest.
- **Leverage Tonal Shifts:** Use the `surface_container` tokens to guide the user's eye through a hierarchy of information.

### Don’t:
- **Don’t use "Pure" Black:** Use our charcoal `on_background` (#1C1B1B) for text to maintain a high-end feel. Pure black (#000000) feels "cheap" and unrefined.
- **Don’t use 1px Dividers:** If you feel the need for a line, try using a 16px gap or a subtle background color change instead.
- **Don’t Over-round:** Stick to the `md` (0.375rem) or `lg` (0.5rem) roundedness for most containers. `full` roundedness should be reserved exclusively for chips and status indicators.
