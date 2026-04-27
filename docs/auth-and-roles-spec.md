# Auth & Roles — Specification v1.0

**Status:** Draft · **Owner:** Hesam · **Last updated:** 2026-04-25 · **Target:** Sundance June 2026

This document is the single source of truth for the XProject authentication
flow, role-permission matrix, login UX, and crash-handling expectations.

When this spec and any older document disagree, **this spec wins.**

---

## 1. Why this spec exists

The login page is the door. Every user touches it. Today's implementation
has real problems caught in browser testing 2026-04-25:

- Empty-form submit causes a blank white page (real crash)
- Pre-filled dev credentials confuse new users
- Quick-login dev panel exposed in production builds
- Hardcoded `navigate('/dashboard')` redirect breaks for warehouse staff
- No accessibility (no aria-live, no focus management on error)
- Role permissions scattered across `usePermissions`, `Sidebar.tsx` switch
  statements, route-level `RequirePermission` flags, and ad-hoc service
  layer checks. No single source of truth to audit.
- No documented crash scenarios

This spec fixes the door and formalizes how role-based access works for
the rest of the app.

Three pillars:

1. **Honest UX.** Empty fields produce a clear inline error, not a blank
   page. Network errors say "can't reach server," not "wrong password."
   Loading states everywhere there's a network call.
2. **Single source of truth for roles.** A role registry in code that
   drives the sidebar, route guards, landing pages, and service-layer
   permission checks. Adding a new role is one file edit, not a hunt.
3. **Production-safe defaults.** Dev shortcuts disabled in production
   builds. Generic error copy that doesn't leak internals. Accessibility
   defaults that meet WCAG AA on the login page (the only public page).

---

## 2. What we are NOT building in v1.0

| Item | Status | Why |
|---|---|---|
| Password reset / forgot password flow | ❌ Deferred to its own spec | Real feature, ~3h scope. Email infra + 2 endpoints + 2 pages + token security model. Until shipped, Owner resets via direct DB update or admin tool. |
| Magic-link / passwordless login | ❌ v2.0 | Requires same email infra prereq. |
| OAuth / SSO (Google, Apple) | ❌ v2.0 | No clear product need yet. |
| Multi-factor authentication | ❌ v2.0 | Tenant scope is small enough that 2FA is overkill for v1.0. |
| Subdomain-split admin portal | ❌ v2.0 | One login URL is sufficient at current scale. |
| Italian translation of login UI | ❌ Phase 5 (post-Sundance) | Per your roadmap; whole-app translation pass happens at the end. Login stays English-only for v1.0. |
| Italian aria-label translation | ❌ Phase 5 | Tied to UI translation. English aria for v1.0. |
| Email-domain role heuristics | ❌ Rejected | Brittle. Real role is set in the database when the user is created. |
| Per-role custom URLs (`/login/owner` etc.) | ❌ Rejected | "How does anyone find this URL" problem. Single page with role landing post-login is the industry standard. |
| Account self-signup | ❌ v2.0+ | Tenant-managed. Owner provisions accounts; signup creates security and billing complexity. |
| Login analytics / failed-attempt monitoring | ⚠️ Partial in v1.0 | We log via existing FastAPI access log. Dedicated security event log is v1.1. |

---

## 3. The 4 roles

| Role | DB enum value | Mental model | Headcount per tenant |
|---|---|---|---|
| **Owner** | `owner` | Tenant admin. Sees everything, controls everything. | Typically 1, max ~3 |
| **Manager** | `manager` | Bar/area manager. Owns ONE bar; sees only that bar's operational data. | 1 per bar (~2-5 per event) |
| **Bartender** | `bartender` | Front-of-bar staff. Scans POS sales, sees own bar status only. | 1-3 per bar |
| **Warehouse keeper** | `warehouse` | Backstage stock handler. Receives invoices, dispatches to bars. Has NO bar context. | 1-2 per tenant |

**Tenant isolation:** roles are scoped per tenant. An Owner of Tenant A is
not an Owner of Tenant B. Today only 1 tenant exists (Noma Group), but the
data model already enforces tenant FKs everywhere.

**Role mutation:** roles are set at user-create time and only Owner can
change them via a future Settings page admin section (not in v1.0). For
v1.0, role changes happen via direct DB update.

**Role snapshot in audit data:** any audit row that includes a role
(warehouse_scans.scanned_by_role, future audit logs) records a SNAPSHOT
of the role at action time, not a live FK lookup. Already established in
the warehouse module — same convention applies to all future audit data.

---

## 4. Login UX

### 4.1 The single page at `/login`

One URL for everyone. Backend decides role via JWT, frontend redirects
post-login (§5.1).

### 4.2 Visual layout

```
┌──────────────────────────────────────────────┐
│  [XProject brand bar — full width, navy]     │
├──────────────────────────────────────────────┤
│                                              │
│              ┌────────────────────┐          │
│              │  Sign in           │          │
│              │  Sundance 2026     │          │
│              ├────────────────────┤          │
│              │                    │          │
│              │  Email             │          │
│              │  [____________]    │          │
│              │                    │          │
│              │  Password          │          │
│              │  [____________]    │          │
│              │                    │          │
│              │  [⚠ inline error]  │          │
│              │                    │          │
│              │  [   Sign in   ]   │          │
│              │                    │          │
│              │  Forgot password?  │          │ ← link, opens future modal
│              │                    │          │
│              │  ─────  DEV  ─────│          │ ← only in import.meta.env.DEV
│              │  [Owner] [Manager] │          │
│              │  [Bartender] [Warehouse]      │
│              │                    │          │
│              └────────────────────┘          │
│                                              │
└──────────────────────────────────────────────┘
```

Design tokens (already in use across the app):
- Brand blue: `#1E5A8D`
- Surface white: `#FFFFFF`
- Background: `#F7FAFC`
- Error red: `#E74C3C`
- Border neutral: `#E2E8F0`
- Text primary: `#1A202C`, secondary: `#4A5568`, tertiary: `#718096`

### 4.3 Form fields

**Email**
- type=email, autoComplete=username, required
- Empty default in production; pre-fill via Quick Login (dev only)
- Auto-focused on mount and after error
- Browser-native email validation as baseline

**Password**
- type=password, autoComplete=current-password, required
- Empty after submit error (so retype is intentional)
- No visibility toggle in v1.0 (icon button is v1.1 polish)

**Forgot password? link**
- Visible but inert until reset flow ships. Click opens a modal saying
  "Password reset will be available soon. For now, contact your tenant
  admin." OR (if Omar prefers) hide entirely until shipped.
- Decision: **show with disabled message** — better than vanishing UI.

**Sign in button**
- Full-width, brand blue, disabled when loading
- Label: "Sign in" / "Signing in…"

**Quick Login row (dev only)**
- Wrapped in `{import.meta.env.DEV && <DevPanel />}` — never renders in
  prod build
- Lists all 4 roles with one button each, color-coded to match role badges
  used elsewhere in the app
- Button click pre-fills email + password fields, does NOT auto-submit

### 4.4 States

| State | Trigger | UI |
|---|---|---|
| `idle` | Page mount | Empty fields, email focused, button enabled, no error |
| `submitting` | User clicks Sign in | Button disabled, label "Signing in…", inputs read-only |
| `error_credentials` | Backend returns 401/422 | Error banner: backend `detail` if present, else "Sign in failed. Check email and password." Password field cleared. Email field re-focused. |
| `error_network` | Request never gets a response | Error banner: "Can't reach the server. Check your connection and try again." Password cleared. Email refocused. Email VALUE preserved. |
| `error_locked` | Backend returns 423 (future) | Error banner: backend message, account-locked styling (orange). |
| `success` | 200 OK, JWT received | Form unmounts → AuthContext hydrates → role-aware redirect (§5.1). No success banner needed; the redirect IS the feedback. |

### 4.5 Accessibility (WCAG AA baseline)

- Email + password labels properly tied via `htmlFor`/`id`
- All inputs visible focus rings (Tailwind `focus:border-[#1E5A8D]`)
- Error banner: `role="alert"` + `aria-live="assertive"`. Screen readers
  announce login failures immediately
- Buttons have descriptive `aria-label` when icon-only (none in v1.0)
- Color contrast: error red on light pink background passes AA (≥4.5:1)
- Keyboard: Tab order email → password → submit → forgot → dev row
- Enter key in either field submits the form
- No reliance on color alone (error has icon + text)

i18n: aria labels are English-only for v1.0 per §2.

---

## 5. Role landing & permission matrix

### 5.1 Post-login landing route

After successful login, AuthContext populates `user`. The login form reads
`user.role` and navigates to the role's home route from this map:

```ts
const LANDING_BY_ROLE: Record<AuthUser['role'], string> = {
  owner:     '/dashboard',
  manager:   '/dashboard',
  bartender: '/dashboard',
  warehouse: '/warehouse',
}
```

`/dashboard` is the same URL but renders different content per role
(it's already role-aware via the existing `<DashboardPage>` logic).
Warehouse staff land directly on `/warehouse` because Dashboard isn't
a useful surface for them.

**Future expansion:** when role-specific dashboards diverge enough, this
map gets a real per-role URL (`/owner-home`, `/bar-manager-home`, etc.).

### 5.2 Per-route permission matrix

This is the canonical matrix. Today's `RequirePermission` route guards
must match this. When adding routes, update this table first.

| Route | Owner | Manager | Bartender | Warehouse |
|---|---|---|---|---|
| `/login` | ✅ public | ✅ public | ✅ public | ✅ public |
| `/dashboard` | ✅ all bars | ✅ own bar | ✅ own bar | ❌ → /warehouse |
| `/events` (list) | ✅ | ❌ | ❌ | ❌ |
| `/events/create` | ✅ | ❌ | ❌ | ❌ |
| `/events/:id` | ✅ | ❌ | ❌ | ❌ |
| `/inventory` | ✅ | ✅ own bar | ✅ own bar | ❌ |
| `/alerts` | ✅ | ✅ own bar | ❌ | ❌ |
| `/warehouse` | ✅ | ❌ | ❌ | ✅ |
| `/warehouse/scan` | ✅ | ❌ | ❌ | ✅ |
| `/warehouse/pending-review` | ✅ | ❌ | ❌ | ❌ (Owner-only action) |
| `/predictions` | ✅ | ❌ | ❌ | ❌ |
| `/reports` | ✅ | ✅ own-bar report | ❌ | ❌ |
| `/reports/:reportId` | ✅ | ✅ own-bar report only | ❌ | ❌ |
| `/chat` | ✅ | ✅ | ✅ | ❌ |
| `/scan` (bartender mobile) | ❌ | ❌ | ✅ | ❌ |
| `/settings` | ✅ | ✅ | ✅ | ✅ |

Roles denied access redirect to their landing route per §5.1.

### 5.3 Per-action permission matrix (intra-page)

Some pages allow read by multiple roles but write by fewer. These are
enforced at the API level AND in the UI (button hidden, not just disabled).

| Action | Owner | Manager | Bartender | Warehouse |
|---|---|---|---|---|
| Create/edit event | ✅ | ❌ | ❌ | ❌ |
| Acknowledge alert | ✅ | ✅ own-bar alerts | ❌ | ❌ |
| Submit POS scan | ❌ | ❌ | ✅ own bar | ❌ |
| Submit warehouse INTAKE scan | ✅ | ❌ | ❌ | ✅ |
| Submit DISPATCH/RETURN scan | ✅ | ✅ own bar | ❌ | ✅ |
| Approve/reject pending review | ✅ | ❌ | ❌ | ❌ |
| Generate prediction | ✅ | ❌ | ❌ | ❌ |
| Generate report | ✅ | ✅ own bar | ❌ | ❌ |
| Send chat message | ✅ | ✅ | ✅ | ❌ |
| Modify warehouse allocations | ✅ | ❌ | ❌ | ❌ |
| Create delivery invoice | ✅ | ❌ | ❌ | ✅ |
| Open dispute on invoice | ✅ | ❌ | ❌ | ❌ |
| Sign out | ✅ | ✅ | ✅ | ✅ |

### 5.4 The role registry (code structure)

Today: permissions live in 4 places — `usePermissions.ts`,
`Sidebar.tsx` switch statements, route-level `RequirePermission` flags,
service-layer role checks (e.g. ScanService).

**Target structure** (not implemented in v1.0 spec; documented for the
implementation PR):

```
features/auth/
  roles.ts              ← single role registry (this file is the truth)
  usePermissions.ts     ← derived from roles.ts
  AuthContext.tsx       ← unchanged
  useAuth.ts            ← unchanged

shared/layout/
  Sidebar.tsx           ← getNavItems(role) reads from roles.ts

app/
  routes.tsx            ← <RoleGate roles={['owner','manager']}> wraps Routes
```

`roles.ts` exports the matrices in §5.2 and §5.3 as typed objects.
`getNavItems`, `usePermissions`, `RoleGate`, and backend role guards
all consume the same source.

This refactor is **out of scope for the v1.0 spec implementation.**
Tracked in roadmap as T2.x (post-Sundance polish). For v1.0, the
matrices in this spec are the contract; implementation may have
duplication during the transition.

---

## 6. Crash & error scenarios

### 6.1 Catalog of every failure mode + handling

| Scenario | Trigger | Expected handling |
|---|---|---|
| Empty email | User submits with email blank | HTML5 `required` blocks submit. Native browser tooltip "Please fill out this field." Form does NOT make a network call. |
| Empty password | User submits with password blank | Same as above. |
| Malformed email | `not-an-email` | HTML5 `type=email` blocks submit. Native browser validation. |
| Wrong credentials | 401 from backend | Error banner with backend `detail`. Password cleared. Email refocused. |
| Account disabled | 403 from backend with specific code | Error banner: "Your account is disabled. Contact your tenant admin." |
| Tenant suspended | 403 with `tenant_suspended` | Error banner: "This workspace is currently suspended." |
| Server 500 | 500 from backend | Error banner: "Server error. Please try again in a moment." Log to console. |
| Network unreachable | `err.request` exists, no `err.response` | Error banner: "Can't reach the server. Check your connection and try again." |
| Slow response (>5s) | No special handling in v1.0; spinner stays | v1.1: cancel after 30s with "Request timed out, try again." |
| JWT received but malformed | Should never happen; backend bug | AuthContext throws on hydrate. Login form catches. Error banner: "Sign in failed. Try again." |
| Multiple submits during pending | Double-click "Sign in" rapidly | Button disabled during `submitting` state. Second click is a no-op. |
| User edits email while submitting | Onchange during pending | Edit allowed but doesn't matter; the in-flight request uses the snapshot from the moment Submit was clicked. |
| Browser autofill triggers submit | Password manager autofill + Enter | Same path as manual submit. |
| Stale JWT in localStorage on mount | Existing token expired | AuthContext hydrate fails. App stays on /login (no redirect). User logs in fresh. |
| Browser back-nav after login | User pressed Back from /dashboard to /login | If still authenticated, /login redirects forward to landing. |
| Browser direct-nav to /login while logged in | Manual URL paste | Same as above — redirect forward. |
| Direct-nav to protected URL while logged out | `/dashboard` typed in address bar | RequireAuth redirects to /login with `state.from`. After login, user lands on `state.from` (not the role landing). This restores deep links. |

### 6.2 The blank-page bug discovered 2026-04-25

**Trigger:** Submit with empty fields, login() throws, my error parser
referenced `user.role` from `useAuth()` hook before the error path.

**Root cause:** Inside `handleSubmit`, after `await login()` rejected, the
catch block reads `user?.role` (closure capture) — but `user` was `null`
at the time the closure formed (before login). The destructure of `user`
happens at component-render scope, not inside the awaited promise; so by
the time the catch runs, `user` is still null.

The actual blank-page came from a different code path: when `login()`
throws, my code DID call `setError(...)`, which triggers a re-render. But
something in the re-render unmounted the form. **Likely cause:** the
`useEffect(() => emailRef.current?.focus(), [error])` runs on the new
error and tries to focus a ref that's been unmounted by some parent
effect. Need to verify in DevTools console.

**Resolution path:** when we implement, log full stack trace to console
on any caught error. If the React reconciler error appears, fix the ref
guard (`emailRef.current?.focus()` is already null-safe; the actual
crash is somewhere else and we need to see the stack).

---

## 7. Implementation plan

3 dedicated patches across 3 separate commits. No mixing.

### Patch 1 — Spec land
- This document committed to `docs/auth-and-roles-spec.md`
- No code changes
- Roadmap updated

### Patch 2 — Login form rewrite
- LoginForm rewritten to match §4 spec exactly
- Empty-form crash fixed (verify with DevTools console first)
- Production-safe: dev panel hidden via `import.meta.env.DEV`
- Role-aware landing redirect from §5.1
- Accessibility: `role="alert"`, `aria-live`, focus management
- Network vs credential error differentiation
- Forgot password link rendered as inert "coming soon" message
- Visual cleanup: Omar pill color uses brand `#1E5A8D` not random teal

### Patch 3 — Permission matrix audit
- Walk every route in `routes.tsx` and verify `RequirePermission`
  flag matches §5.2 matrix exactly. Patch any divergence.
- Walk every page that has action buttons (Acknowledge, Approve,
  Generate, etc.) and verify hide-vs-disable matches §5.3. Patch any
  divergence.
- Walk every backend service that has role checks and verify against
  §5.3. Patch any divergence.
- Output: a single commit listing every diff found and fixed.

---

## 8. Testing checklist

When Patch 2 + Patch 3 ship, manually verify:

- [ ] Empty submit → native browser validation message, no crash
- [ ] Wrong password → red banner, password cleared, email refocused
- [ ] Network down (kill backend) → "Can't reach server" message
- [ ] Owner login → lands on `/dashboard`
- [ ] Warehouse keeper login → lands on `/warehouse`
- [ ] Manager login → lands on `/dashboard`
- [ ] Bartender login → lands on `/dashboard`
- [ ] Hard-refresh `/warehouse` while logged in as Manager → redirect to `/dashboard` (not blank page, not 403 — soft redirect)
- [ ] Hard-refresh `/dashboard` while logged in as Warehouse → redirect to `/warehouse`
- [ ] Hard-refresh `/scan` (bartender route) as Owner → redirect (Owner shouldn't see bartender mobile UI)
- [ ] Hard-refresh `/login` while authenticated → redirect to landing
- [ ] Direct nav to `/predictions` while logged out → redirect to `/login`. Sign in. Lands at `/predictions` (deep link restored).
- [ ] Production build (`npm run build && npm run preview`) → dev quick-login row NOT visible
- [ ] Tab key flow works correctly: email → password → submit → forgot
- [ ] Screen reader announces error banner (test via VoiceOver Cmd+F5)

---

## 9. Future scope (not v1.0)

| Item | Tier in roadmap | Notes |
|---|---|---|
| Password reset / forgot password | Tier 2 | Own spec doc. ~3h. Email infra dependency. |
| Italian translation pass | Phase 5 (post-Sundance) | Whole-app translation. Login is part of it. |
| Two-factor auth | v2.0 | Consider after Tier 2 ML and warehouse v1.1 ship. |
| Magic-link login | v2.0 | Same email infra as password reset. Consider unifying. |
| Login-attempt rate limiting | v1.1 | Currently relies on FastAPI default; Sundance may need stronger. |
| Failed-login security event log | v1.1 | Dedicated table/feed for Owner to audit. |
| Session expiration warning ("you'll be logged out in 5 min") | v1.1 | UX polish for active sessions. |
| Roles registry refactor (single source for permissions) | T2.x | Tracked in roadmap as a polish-only structural improvement. |
| Per-role login URL theming | v2.0 | Spec rejected for v1.0; revisit if tenant scale grows. |
| OAuth / SSO providers | v2.0+ | No identified need yet. |

---

## 10. Document history

| Version | Date | Author | Notes |
|---|---|---|---|
| 1.0 | 2026-04-25 | Hesam | Initial spec. Locks 4-role matrix, login UX, crash catalog, accessibility baseline. Defers password reset to its own spec. |
