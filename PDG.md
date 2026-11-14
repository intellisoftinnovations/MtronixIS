# PDG.md — Carton Inventory System

**Product Definition & Guide**
Version 1.0 · Timezone: Asia/Dhaka (UTC+6)

---

## 1. Overview

A secure web-based inventory system for managing **product cartons** moving **in** and **out** of one or more inventories (warehouses). Only **Admins** and **Managers** can log in and change stock. Anyone can scan a carton's **QR code** to view the product image (read-only, no login).

Every stock movement produces a **PDF receipt** with full details stamped in **Bangladesh time**, and is recorded in a permanent **Activity Log**.

### Core Principles
- Security first: admin/manager-only access for everything except the public QR image view.
- Every change is traceable (who, what, when, before/after).
- Fast on mobile: scanning and stock in/out must work smoothly on a phone.

---

## 2. User Roles & Permissions

| Capability | Public (no login) | Manager | Admin |
|---|:--:|:--:|:--:|
| View product image via QR link | ✅ | ✅ | ✅ |
| Log in to system | ❌ | ✅ | ✅ |
| View dashboard | ❌ | ✅ | ✅ |
| Scan QR → Stock In / Stock Out | ❌ | ✅ | ✅ |
| Add / edit cartons & products | ❌ | ✅ | ✅ |
| Delete cartons / products | ❌ | ❌ (or approval) | ✅ |
| Manage inventories (warehouses) | ❌ | View / limited edit | ✅ |
| View activity log | ❌ | ✅ (own inventories) | ✅ (all) |
| Manage users & roles | ❌ | ❌ | ✅ |
| Download / regenerate PDFs | ❌ | ✅ | ✅ |

> Deletion should be a **soft delete** (hidden, recoverable, logged) so history and PDFs stay valid.

---

## 3. Authentication & Security

### 3.1 Authentication
- Email + password login (passwords hashed with **Argon2id** or bcrypt, never stored in plain text).
- **Two-factor authentication (2FA)** — TOTP authenticator app, **mandatory for Admin**, strongly recommended for Manager.
- No public sign-up. Admin creates accounts and assigns roles; users set password via a one-time invite link.
- Short-lived access token + rotating refresh token in **HttpOnly, Secure, SameSite** cookies.
- Auto-logout after inactivity (e.g., 15–30 minutes).

### 3.2 Protection
- Rate limiting and temporary lockout after repeated failed logins.
- Strong password policy; check against breached-password lists.
- Role-based access control (RBAC) enforced **on the server** for every API route.
- HTTPS only, HSTS, CSRF protection, input validation, parameterized queries.
- Security headers (CSP, X-Frame-Options, etc.).
- Login history (time, IP, device) visible to the user and admin.
- Admin can force logout / disable any user.

### 3.3 Public QR Safety
- QR codes contain an **unguessable random token** (e.g., 128-bit) — never a sequential ID.
- The public page shows **only** the product image and name — **no** stock quantity, prices, or inventory details.
- Rate-limit the public endpoint; Admin can regenerate/revoke a QR token.

---

## 4. Modules & Features

### 4.1 Dashboard
Shown after login. Summary cards and widgets:

- Total inventories (warehouses)
- Inventory name list with **total cartons** and **total quantity** per inventory
- Total products, total cartons in stock
- Stock In / Stock Out **today**, this week, this month
- Low-stock alerts (below a configurable threshold)
- Recent activity (last 10 movements)
- Chart: stock in vs out over time (7/30 days)
- Quick actions: **Scan QR**, **Add Carton**

### 4.2 Products & Cartons
**Product** = the item type (name, SKU, image, description).
**Carton** = a physical box of a product held in an inventory.

Features:
- Add / edit / delete (soft) products and cartons
- Upload product image (compressed, validated type & size)
- Carton fields: product, inventory, carton number/code, quantity per carton, number of cartons, status
- Search, filter (inventory, product, status, date) and sort
- Pagination and export (CSV)
- Generate and print **QR label** per product/carton (single and bulk print sheet)

### 4.3 QR Scan (Admin / Manager only)
Dedicated page using the device camera.

**Flow**
1. User opens **Scan QR** and scans a product/carton QR.
2. System shows the **product image**, name, SKU, inventory, and current stock.
3. Two clear actions: **Stock In** / **Stock Out**.
4. User enters cartons count (and quantity if needed), optional note/reference.
5. Confirm → stock updates, log entry is created, **PDF is generated**.
6. Success screen with **Download PDF** / **Print** / **Scan next**.

**Rules**
- Stock Out cannot exceed available stock (clear error message).
- Double-submit protection (idempotency) so a movement isn't recorded twice.
- Confirmation step before saving.
- Manual code entry fallback if the camera is unavailable.

### 4.4 Inventory Management
- Create / edit / archive inventories (name, location, code, notes)
- Assign managers to inventories
- View all cartons per inventory with totals
- Set low-stock thresholds
- Transfer cartons between inventories (logged as out + in) — *phase 2*

### 4.5 Stock In / Stock Out PDF Receipt
Generated automatically on **every** movement. Stored and re-downloadable from the Log page.

**PDF contents**
- Company name / logo
- Document title: **STOCK IN RECEIPT** or **STOCK OUT RECEIPT**
- Unique receipt number (e.g., `SI-20261112-0001` / `SO-20261112-0001`)
- **Date & time in Bangladesh time** (e.g., `12 Nov 2026, 03:45 PM (BST, UTC+6)`)
- Product name, SKU, product image (thumbnail)
- Inventory name
- Carton number(s)/code(s), cartons moved, quantity per carton, total quantity
- Stock **before** and **after**
- Performed by (name, role)
- Note / reference
- QR code linking to the receipt record (for verification)
- Footer: "System generated document"

### 4.6 Activity Log Page
A full, read-only audit trail.

- Every action: stock in/out, create/edit/delete, login/logout, role changes, QR regenerate
- Columns: date-time (Bangladesh time), user, action, product, inventory, quantity, before → after, note, PDF link
- Filters: date range, user, action type, inventory, product
- Search, pagination, CSV export
- Logs **cannot be edited or deleted** by anyone, including Admin.

---

## 5. Data Model (Suggested)

| Table | Key Fields |
|---|---|
| `users` | id, name, email, password_hash, role (`admin`/`manager`), 2fa_secret, is_active, last_login_at |
| `inventories` | id, name, code, location, low_stock_threshold, is_archived |
| `inventory_managers` | user_id, inventory_id |
| `products` | id, name, sku, description, image_url, qr_token, is_deleted |
| `cartons` | id, product_id, inventory_id, carton_code, qty_per_carton, carton_count, status, is_deleted |
| `stock_movements` | id, type (`IN`/`OUT`), receipt_no, product_id, carton_id, inventory_id, cartons_moved, qty_moved, stock_before, stock_after, note, user_id, created_at (UTC), pdf_url |
| `activity_logs` | id, user_id, action, entity_type, entity_id, old_value, new_value, ip, user_agent, created_at (UTC) |
| `login_history` | id, user_id, ip, device, success, created_at |

**Time handling:** store everything in **UTC**, display and print in **Asia/Dhaka (UTC+6)**.

---

## 6. Suggested Tech Stack

| Layer | Suggestion |
|---|---|
| Frontend | Next.js (React) + Tailwind CSS |
| Backend | Next.js API routes or Node.js (NestJS/Express) |
| Database | PostgreSQL + Prisma ORM |
| Auth | Auth.js / custom JWT + TOTP (otplib) |
| QR generate / scan | `qrcode` + `html5-qrcode` (or `@zxing/browser`) |
| PDF | `pdf-lib`, `pdfkit`, or Puppeteer (HTML → PDF) |
| Time | `date-fns-tz` / `luxon` with `Asia/Dhaka` |
| File storage | S3-compatible (Cloudflare R2 / AWS S3) or local disk |
| Hosting | VPS / Vercel + managed Postgres, behind HTTPS |

---

## 7. Key API Endpoints (Outline)

```
POST   /api/auth/login
POST   /api/auth/2fa/verify
POST   /api/auth/logout

GET    /api/dashboard/summary

GET    /api/products            POST /api/products
GET    /api/products/:id        PUT  /api/products/:id     DELETE /api/products/:id
GET    /api/cartons             POST /api/cartons
PUT    /api/cartons/:id         DELETE /api/cartons/:id

GET    /api/inventories         POST /api/inventories
PUT    /api/inventories/:id

POST   /api/stock/in            (admin/manager)
POST   /api/stock/out           (admin/manager)
GET    /api/stock/:id/pdf

GET    /api/logs                (filters + pagination)

GET    /q/:qr_token             (PUBLIC — product image page only)
```

---

## 8. Pages / Screens

1. Login (+ 2FA)
2. Dashboard
3. Products list / detail / add-edit
4. Cartons list / add-edit
5. **Scan QR** (stock in / out)
6. Inventories list / detail
7. Activity Log
8. Users & Roles (admin)
9. Profile & Security (password, 2FA, login history)
10. **Public QR page** (image only)

---

## 9. Non-Functional Requirements

- **Responsive:** mobile-first (scanning happens on phones).
- **Performance:** pages load under 2 seconds; PDF generated in under 5 seconds.
- **Reliability:** database transactions for stock changes (no partial updates); daily automated backups.
- **Concurrency:** prevent negative stock when two users act at once (row locking / atomic updates).
- **Auditability:** every write creates a log entry.
- **Accessibility:** readable contrast, keyboard navigation, large touch targets.
- **Browser support:** latest Chrome, Safari, Edge, Firefox.

---

## 10. Development Phases

**Phase 1 — Foundation**
Project setup, database, auth (login, 2FA, roles), user management.

**Phase 2 — Core Inventory**
Inventories, products, cartons CRUD, image upload.

**Phase 3 — QR & Stock Movement**
QR generation/printing, public QR page, scan page, stock in/out logic.

**Phase 4 — PDF & Logs**
PDF receipts (Bangladesh time), activity log page, filters, exports.

**Phase 5 — Dashboard & Polish**
Dashboard charts, low-stock alerts, glassmorphism UI polish, testing, security review, deployment.

---

## 11. Acceptance Criteria

- [ ] Only admin/manager can log in; no public registration.
- [ ] Admin account requires 2FA.
- [ ] Scanning a QR while logged out shows **only** the product image.
- [ ] Scanning while logged in as admin/manager shows image + Stock In / Stock Out.
- [ ] Stock Out above available quantity is blocked.
- [ ] Each stock in/out creates a PDF with Bangladesh date & time and full details.
- [ ] Every action appears in the Activity Log and cannot be edited.
- [ ] Dashboard totals match actual stock.
- [ ] Deleting a carton/product is soft-delete and logged.
- [ ] Works smoothly on mobile.

---

## 12. Future Ideas (Optional)

- Barcode support, batch/expiry tracking
- Transfers between inventories
- Email/WhatsApp low-stock alerts
- Bangla language option
- Offline-friendly scanning with sync
