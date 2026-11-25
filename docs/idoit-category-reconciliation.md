# Category reconciliation and manual sync jobs

Each target category is read once per sync run; the in-memory snapshot is advanced after acknowledged writes. Missing, ambiguous or duplicate incoming identities are not written. Reads that fail prevent writes to that category. Only changed fields are sent for an existing entry. No deletion of foreign or stale inventory is performed. The category save response must supply an entry ID on create (see https://kb.i-doit.com/en/i-doit-add-ons/api/methods/v1/cmdb.category.html). No speculative retries after failed or uncertain saves.

Applications use object ID plus assigned version; parallel installed versions remain distinct. Old versions are not automatically removed. OS uses object ID. Memory module identity is stored in the title using the slot or valid serial; legacy observations without identity are skipped. Linux total memory is a separate aggregate; individual Linux modules require working dmidecode and sufficient privileges. Disk identity uses serial and the existing locator matching logic. Certificates use serial or common name plus expiry; connections use protocol and port range. Unknown categories require a title or a known singleton identity. Unresolved containers never produce raw application rows.

Unmatched applications remain warnings in the sync log, with a retryable synced_with_warnings state and no device last_error solely for missing applications. The bulk run shares an application catalog and title lookup cache. A matching revision change invalidates old payload hashes.

POST /api/idoit/devices/{id}/sync and POST /api/idoit/sync-all now return HTTP 202 with a job_id; GET /api/idoit/sync-jobs/{job_id} reports queued/running/completed/failed and bulk progress. Jobs and the manual/automatic synchronization lock are process-local (single backend worker). A restart interrupts a job; restart the sync to reconcile from the upstream snapshot. The sync log records per-category created, updated, unchanged, ambiguous, failed counts.

No live i-doit data is included in the regression fixtures.
