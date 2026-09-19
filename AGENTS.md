# IoT Project Operations

- Run server-side tests in a new isolated database on `imytestth`, not on
  `imytestlan`. Never point a test runner at `odoo-26-1-16`.
- Use synthetic fixtures, a separate addon directory and data directory,
  loopback-only preview ports, disabled cron/email and restricted egress.
- Rehearse upgrades from the installed production version before release.
  Match the tested artifact hashes and retain verified database, filestore,
  addon and bridge backups.
- A platform release does not authorize device flashing, relay switching,
  protection resets or rebinding an unverified temperature-gateway source IP.
- Keep physical commissioning and unfinished washer requirements explicit.
  Passing simulated tests is not hardware acceptance.
- Reuse the approved deployment credential helper and host-key verification.
  Never print or commit credentials, real device configuration or database dumps.
