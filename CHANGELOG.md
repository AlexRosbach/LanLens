# Changelog

All notable changes to this project should be documented in this file.

## v1.3.0 — Flexible scan ranges and smarter subnet defaults

- Added automatic host network detection via `netifaces` so LanLens no longer defaults to `192.168.1.0/24` when deployed on a different subnet.
- The configured `dhcp_start` and `dhcp_end` values now define the real IPv4 scan range instead of forcing a `/24` derived only from `dhcp_start`.
- Added support for extended scan ranges by summarizing the configured start/end range into one or more scan targets.
- Settings now show the detected host subnet range by default when no explicit scan range has been saved yet.
- Added validation so `dhcp_start` cannot be greater than `dhcp_end`.
- Improved logging to show whether the active scan range came from configuration, host auto-detection, or fallback defaults.
- Fixes #17 and addresses the requested flexibility from #5 and #6.

## v1.2.5 — Update detection & notification hardening

- Added backend `/api/settings/update/check` endpoint so update detection no longer depends only on a direct frontend GitHub call.
- Frontend update hook now consumes backend update-check results instead of hitting GitHub directly.
- Update notification endpoint now skips cleanly when no newer release exists.
- Existing server-side dedupe for already-notified versions remains in place.

## v1.2.4 — Server-side sessions & NEW badge state

- Removed browser `localStorage` / `sessionStorage` persistence from the LanLens app flow.
- Switched authentication to HTTP-only cookie-based session handling instead of browser-stored bearer tokens.
- Added server-side per-user device view tracking via `device_views`.
- NEW badge state is now computed on the backend and stays consistent across direct access and reverse-proxy access.
- Added `/api/devices/{id}/mark-viewed` for server-side viewed-state updates.
- Hardened migration logic so the `device_views` unique index is created even when the table already exists.

## v1.2.3 — Reverse-proxy path fix

- Fixed frontend base-path handling for reverse-proxy / subpath deployments.
- BrowserRouter now respects the deployed Vite base path instead of assuming `/`.
- Login redirect on 401 now resolves through the frontend base path.
- Logo asset paths and RDP download URLs now work correctly behind proxied subpaths.
- Added `frontend/src/vite-env.d.ts` so `import.meta.env.BASE_URL` builds cleanly in TypeScript.

## v1.2.2 — Bug fix: TopBar new-device counter

- Fixed the TopBar new-device counter to stay consistent with the Dashboard logic.

## v1.2.1 — Bug fixes & segment enhancements

- Fixed unregistered counter behavior for viewed devices.
- Improved segment filtering and IP usage display.

## v1.2.0 — Server URL, Telegram update notifications, sortable table & more device classes

- Added server URL setting for reverse-proxy deployments.
- Added Telegram update notifications.
- Added sortable device table and more device classes.
