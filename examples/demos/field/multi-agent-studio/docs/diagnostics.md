# Support diagnostics

`./bac logs` remains a short recent console view. The structured diagnostics file is separate; it does not increase normal console output.

## Share a report

1. Reproduce the issue and note the actions and approximate time.
2. Open **Resources → About Multi-Agent Studio → Issue report → Copy diagnostics** and paste the result into the issue report.
3. **Download** saves a text report with more recent events when needed.

Both reports include the browser build and server build, source commit, server build fingerprint/run ID, pinned runtime versions, server OS/Python, current observed model connections, current-session job counts and recent job states. Runtime observation time is included so an old status is not mistaken for a fresh probe. Creating a report does not call a model or restart anything.

Server records cover API errors and slow requests, mutations, job progress and failures, completed model-turn usage, observed policy denials, cleanup failures and reaction failures. Request IDs connect API calls to queued jobs. Job IDs connect background execution and failure locations. Elapsed job time includes queue time; model turn time is recorded separately when reported by the runtime. A category inferred from an error is a triage hint, not independent proof. Only `policy.denial-observed` represents a denial observed in native OpenShell policy logs.

Browser records capture API failures, uncaught JavaScript errors and unhandled rejections using codes and source line locations. These are held only in the current tab, up to 40 events, and included when the user exports. Refreshing the page clears this browser history. If the server is unreachable when exporting, the report explicitly says so and still includes browser/build details.

## Files and retention

- Structured log: `$BAC_DATA_DIR/studio/logs/diagnostics.jsonl`.
- Packaged container location: `/var/lib/bac/studio/logs/diagnostics.jsonl`, on the persistent data volume.
- The active log rotates at 1 MB with three backups, approximately 4 MB total. Files are created with owner-only access.
- The export cache retains the latest 1,200 events and reloads retained files at startup. Copy selects at most 80 session/global-system events with a 48 KB event-data budget; Download selects at most 400 with a 200 KB event-data budget. Formatting and build/status metadata add overhead. Omitted event counts are included.
- In-app scenario resets remove task data but do not delete these rotated files. Full data removal, including a clean `./bac start` where the data directory is cleared, can remove them. Export before clearing data.
- Reports include only the authenticated participant's records plus content-free global startup/runtime changes. A new browser session cannot export a retired session's private task records; the host can inspect the retained structured files when necessary.
- Disk errors fall back to bounded memory and report `storage: memory-only`. Diagnostic database reads have a short timeout and do not block task execution on a busy database.

## Excluded by design

No request or response bodies, prompts, agent names, custom instructions, source documents, generated files, authorization headers, cookies, API keys, endpoint URLs, query strings or raw gateway logs are copied into these records. Exception messages, source code lines and locals are excluded; exception type, category and source locations are retained. Model IDs are filtered before inclusion. Pinned runtime versions describe the build, not a probe of every installed component.

This report will not explain every external failure: provider-internal details, host crashes and native gateway messages can require additional investigation. Raw `./bac logs`, `gateway.log` and `gateway-native.log` remain operator tools and are not automatically included in support exports. Review them before sharing.
