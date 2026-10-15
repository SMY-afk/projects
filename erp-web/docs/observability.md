# Observability integration

The application has vendor-neutral browser observability hooks. It does not include a monitoring SDK. Configure HTTP collection endpoints directly, or replace the `send` function in `src/services/observability/observability.ts` with the SDK adapter selected by the team.

## Release variables

All values are Vite public variables and must not contain secrets. Set them in the CI/CD build environment, not only at container runtime.

| Variable                        | Purpose                                                              |
| ------------------------------- | -------------------------------------------------------------------- |
| `VITE_OBSERVABILITY_ENABLED`    | Set to `false` to disable all reporting.                             |
| `VITE_ERROR_REPORTING_ENDPOINT` | JSON `POST` endpoint for browser errors.                             |
| `VITE_METRICS_ENDPOINT`         | JSON `POST` endpoint for browser performance metrics.                |
| `VITE_RELEASE_ENVIRONMENT`      | Release environment, such as `staging` or `production`.              |
| `VITE_RELEASE_VERSION`          | Immutable build identifier, such as a Git commit SHA or release tag. |

## Event contract

Error events include `type`, `environment`, `release`, `url`, `timestamp`, and `error`. Performance events include the same release context plus `name`, `value`, `unit`, and `tags`. Events are sent with `navigator.sendBeacon` when available and otherwise with a keepalive `fetch` request.

The initial metrics cover navigation duration, paint timing, and Axios request duration. Global runtime errors, unhandled promise rejections, and React rendering errors are captured through the same error endpoint.

## Backend sync metrics

Keep the backend adapter vendor-neutral and use these metric semantics consistently:

| Metric                             | Type      | Definition                                                                      |
| ---------------------------------- | --------- | ------------------------------------------------------------------------------- |
| `sync_job_active_duration_seconds` | Histogram | Sum of time spent in `running` across attempts; excludes queue and retry waits. |
| `sync_job_elapsed_seconds`         | Histogram | Time from initial enqueue until a terminal state.                               |
| `sync_records_received_total`      | Counter   | Source records received by sync workers.                                        |
| `sync_records_succeeded_total`     | Counter   | Records whose page transaction committed successfully.                          |
| `sync_records_failed_total`        | Counter   | Records still not persisted when the task reaches a terminal failure state.     |
| `sync_attempt_errors_total`        | Counter   | Transient or terminal processing errors per attempt.                            |
| `tiktok_rate_limit_total`          | Counter   | Every TikTok HTTP `429`, including request-level retries.                       |

Persist `last_successful_at` by tenant, shop, and entity type for operational queries. Update it only after a range, full, or incremental job reaches `succeeded`; partial completion, cancellation, dead letter, and individual Webhook processing do not advance it.

Time-series metric labels are limited to bounded enums such as `platform`, `entity_type`, `mode`, `status`, and `error_class`. Keep `tenant_id`, `shop_id`, and `sync_job_id` in access-controlled operational data, logs, or trace correlation fields instead of unbounded metric labels. Never attach cursors, external business IDs, buyer addresses, phone numbers, tokens, or secrets.
