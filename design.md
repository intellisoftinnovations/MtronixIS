# design.md — Carton Inventory System UI

**Style:** Glassmorphism · Dark, calm, professional
**Primary:** `#22333B` · **Text:** White · **Buttons:** Black

---

## 1. Design Direction

A deep slate-teal background with soft glowing color blobs behind frosted-glass panels. Everything feels light, layered and clean, with white text and bold black buttons for clear actions. Mobile-first, because scanning happens on phones.

---

## 2. Color Palette

### Core (your choices)
| Role | Color | Hex |
|---|---|---|
| Primary | Deep slate teal | `#22333B` |
| Text | White | `#FFFFFF` |
| Button | Black | `#000000` |

### Supporting (suggested)
| Role | Hex | Use |
|---|---|---|
| Primary dark | `#161F24` | Page background gradient start |
| Primary light | `#3A5560` | Gradient end, hover surfaces |
| Accent (soft sand) | `#C6AC8E` | Highlights, active nav indicator, chart accent |
| Muted text | `rgba(255,255,255,0.70)` | Secondary text, labels |
| Faint text | `rgba(255,255,255,0.50)` | Placeholders, hints |
| Success | `#4ADE80` | Stock In, success states |
| Danger | `#F87171` | Stock Out, errors, delete |
| Warning | `#FBBF24` | Low stock |
| Info | `#60A5FA` | Info badges |

### CSS Variables
```css
:root {
  --primary: #22333B;
  --primary-dark: #161F24;
  --primary-light: #3A5560;
  --accent: #C6AC8E;

  --text: #FFFFFF;
  --text-muted: rgba(255, 255, 255, 0.70);
  --text-faint: rgba(255, 255, 255, 0.50);

  --btn-bg: #000000;
  --btn-text: #FFFFFF;

  --glass-bg: rgba(255, 255, 255, 0.08);
  --glass-bg-strong: rgba(255, 255, 255, 0.14);
  --glass-border: rgba(255, 255, 255, 0.18);
  --glass-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
  --glass-blur: 16px;

  --success: #4ADE80;
  --danger: #F87171;
  --warning: #FBBF24;
  --info: #60A5FA;

  --radius-sm: 10px;
  --radius-md: 16px;
  --radius-lg: 24px;
}
```

---

## 3. Background

Gradient base with blurred color blobs so the glass has something to refract.

```css
body {
  background:
    radial-gradient(circle at 15% 20%, rgba(198,172,142,0.25), transparent 40%),
    radial-gradient(circle at 85% 80%, rgba(58,85,96,0.55), transparent 45%),
    linear-gradient(135deg, #161F24 0%, #22333B 55%, #3A5560 100%);
  background-attachment: fixed;
  color: var(--text);
  min-height: 100vh;
}
```

---

## 4. Glass Surfaces

### Standard Card
```css
.glass {
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow);
}
.glass-strong { background: var(--glass-bg-strong); }
```

- Use `.glass` for cards, sidebar, top bar, modals, tables.
- Use `.glass-strong` for modals and dropdowns so they stand out.
- Fallback when `backdrop-filter` is unsupported: solid `rgba(34,51,59,0.92)`.

---

## 5. Typography

| Use | Font | Weight | Size |
|---|---|---|---|
| Headings | **Poppins** (or Inter) | 600 | 24–32px |
| Body | **Inter** | 400 | 14–16px |
| Numbers (stats) | Poppins | 700 | 28–40px |
| Labels / captions | Inter | 500 | 12–13px |

- Text is white; secondary info uses muted white.
- Optional Bangla support: **Hind Siliguri** as fallback font.

---

## 6. Buttons

### Primary — Black
```css
.btn {
  background: var(--btn-bg);
  color: var(--btn-text);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: var(--radius-md);
  padding: 12px 22px;
  font-weight: 600;
  min-height: 44px;
  transition: transform .15s, box-shadow .15s, background .15s;
}
.btn:hover  { background: #111; box-shadow: 0 6px 20px rgba(0,0,0,0.45); transform: translateY(-1px); }
.btn:active { transform: translateY(0); }
.btn:disabled { opacity: .5; cursor: not-allowed; }
```

### Variants
| Variant | Style |
|---|---|
| Primary | Black bg, white text |
| Secondary | Glass bg, white text, glass border |
| Stock In | Black bg + green left icon / green outline on hover |
| Stock Out | Black bg + red left icon / red outline on hover |
| Danger | Black bg, red text/border |
| Ghost | Transparent, white text |

All buttons: minimum 44px height for touch.

---

## 7. Forms & Inputs

```css
.input {
  background: rgba(255,255,255,0.08);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  color: #fff;
  padding: 12px 16px;
  backdrop-filter: blur(8px);
}
.input::placeholder { color: var(--text-faint); }
.input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(198,172,142,0.25);
}
```

- Labels above inputs, muted white, 13px.
- Errors: red text under the field + red border.

---

## 8. Layout

### Desktop
- **Left sidebar** (glass, 260px): logo, navigation, user chip at bottom.
- **Top bar** (glass): page title, search, notifications, profile menu.
- **Content area:** max width 1400px, 24px gap grid.

### Mobile
- Top bar with menu.
- **Bottom navigation** (glass): Dashboard · Cartons · **Scan** (large center button) · Log · More.
- Scan button is raised and prominent (black circle, white QR icon).

### Navigation Items
Dashboard · Products · Cartons · **Scan QR** · Inventories · Activity Log · Users (admin) · Profile

Active item: glass-strong background + accent-colored left bar.

---

## 9. Screen Notes

### Login
- Centered glass card, logo, email, password, black **Sign in** button.
- Second step: 6-digit 2FA code input.
- Subtle floating background blobs.

### Dashboard
- Row of **stat cards** (Total Inventories, Total Cartons, Total Quantity, Today In/Out).
- Inventory table card: name, cartons, total quantity, status.
- Line/bar chart card (Stock In green, Stock Out red, on glass).
- Recent activity list and low-stock alerts.

### Products / Cartons
- Glass table with image thumbnail, name, SKU, quantity, status badge.
- Search + filter bar on top. Row actions: edit, delete (icon buttons).
- Add/Edit opens a glass modal or slide-over.

### Scan QR
- Full-width camera viewport with rounded corners and glowing accent scan frame.
- After scan: glass result card with **large product image**, name, SKU, inventory, current stock.
- Two large buttons side by side: **Stock In** and **Stock Out**.
- Quantity stepper (− / +), note field, **Confirm** button.
- Success screen: check animation, receipt number, **Download PDF**, **Scan Next**.

### Activity Log
- Glass table with sticky header, colored action badges (In = green, Out = red, Edit = blue, Delete = red outline).
- Filters row, PDF download icon per row, Bangladesh time shown on every entry.

### Public QR Page (no login)
- Minimal: large product image in a glass frame, product name, small footer.
- No stock data, no navigation.

---

## 10. Components

| Component | Notes |
|---|---|
| Stat card | Icon in glass circle, big number, muted label, small trend |
| Badge | Pill, 12px, translucent colored bg + matching text |
| Table | Transparent rows, 1px glass-border dividers, row hover `rgba(255,255,255,0.06)` |
| Modal | Glass-strong, blur 24px, dark overlay `rgba(0,0,0,0.55)` |
| Toast | Glass, colored left border by type |
| Empty state | Soft icon + short text + black action button |
| Skeleton loader | Shimmering glass blocks |

---

## 11. Spacing, Radius & Effects

- Spacing scale: 4 · 8 · 12 · 16 · 24 · 32 · 48
- Radius: 10 / 16 / 24px (cards use 24px)
- Shadows: soft and dark, never harsh
- Motion: 150–250ms ease; subtle fade-up on cards; no heavy animations
- Respect `prefers-reduced-motion`

---

## 12. Accessibility

- White on `#22333B` gives strong contrast (about 12:1); keep text over glass at ≥ 4.5:1. If a glass panel sits over a light blob, increase `--glass-bg` opacity.
- Never rely on color alone: Stock In/Out also use icons and labels (↓ In / ↑ Out).
- Visible focus rings (accent color).
- Touch targets ≥ 44px.

---

## 13. PDF Receipt Style

Print-friendly, so **not glass**:
- White background, `#22333B` headings and header band, black text.
- Green "STOCK IN" / red "STOCK OUT" title badge.
- Clean two-column details table, product thumbnail, QR code in the corner.
- Bangladesh date/time prominently at the top.

---

## 14. Tailwind Quick Config

```js
// tailwind.config.js
theme: {
  extend: {
    colors: {
      primary: { DEFAULT: '#22333B', dark: '#161F24', light: '#3A5560' },
      accent: '#C6AC8E',
    },
    backdropBlur: { glass: '16px' },
    borderRadius: { glass: '24px' },
  },
}
```

```html
<div class="bg-white/10 backdrop-blur-glass border border-white/20 rounded-glass shadow-xl text-white p-6">
  ...
</div>
<button class="bg-black text-white rounded-2xl px-6 py-3 font-semibold hover:bg-neutral-900">
  Stock In
</button>
```
