# Frontend rendering warning

The browser error stack on `/weekend/2026-18` identified Next.js `InnerLayoutRouter` calling React `use()` while unwrapping a deferred server-component response. Application components do not call `use()` directly. This was a framework rendering warning, separate from missing upstream practice timing.

Updated Next.js 16.4.0 → 16.4.3 and React / React DOM 19.3.0 → 19.3.1, including the dependency lockfile. Kept the existing automatic refresh implementation, design and models. Explicitly allowed image qualities `[75, 85]` for the restored hero photo, resolving its separate configuration warning.

Verification after the patch update:

- Production build, including TypeScript and route generation, succeeded.
- npm installation reported zero known vulnerabilities.
- Read-only HTTP smoke checks passed for overview, methodology, race list, archived results, session data, real-only API reports and the self-hosted font.
- In Chrome, reloaded the affected session page and navigated to overview, race list, model reports and back to session data. No new application console errors were captured.
- Selected FP2 and the long-run proxy sort. The page remained visible for an automatic refresh: server log requests to the session route increased from 5 to 6 without further navigation, and both selections persisted. The application error log remained empty.
- Screenshot: `tmp/react-rendering-fixed.jpg`.

Practice timing remains unavailable where the source has not published usable laps. The patch does not invent timing or predictions to fill those waiting states. Browser-extension warnings, where present, are distinct from application errors.
