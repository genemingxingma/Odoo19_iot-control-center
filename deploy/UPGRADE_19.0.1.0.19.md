# IoT Control Center 19.0.1.0.19 Upgrade Runbook

Status: prepared only. Do not run on `imytestth` without explicit production approval.

## Scope

- Preserve custom probe names and use location details for readable chart labels.
- Normalize timezone-aware gateway timestamps to UTC before storage.
- Reject duplicate readings by sensor, timestamp, and rollup type.
- Preserve minimum, maximum, and sample count when raw history is rolled up.
- Add location/group filters, units, daily view, and probe-scoped trend access.

## Read-only preflight

Run these queries against the target database before stopping services:

```sql
SELECT installed_version
FROM ir_module_module
WHERE name = 'iot_control_center';

WITH duplicate_groups AS (
    SELECT
        sensor_id,
        reported_at,
        COALESCE(is_hourly_rollup, FALSE) AS is_hourly_rollup,
        COALESCE(is_daily_rollup, FALSE) AS is_daily_rollup,
        COUNT(*) AS row_count,
        COUNT(DISTINCT (temperature, humidity)) AS value_count
    FROM iot_th_reading
    GROUP BY 1, 2, 3, 4
    HAVING COUNT(*) > 1
)
SELECT
    COUNT(*) AS duplicate_groups,
    COALESCE(SUM(row_count - 1), 0) AS rows_to_remove,
    COUNT(*) FILTER (WHERE value_count > 1) AS conflicting_groups
FROM duplicate_groups;

SELECT
    COUNT(*) AS total_readings,
    MIN(reported_at) AS first_reading,
    MAX(reported_at) AS latest_reading
FROM iot_th_reading;
```

Export all conflicting groups before the upgrade. The migration keeps the latest row and the export is the audit/rollback evidence:

```sql
COPY (
    WITH conflicts AS (
        SELECT
            sensor_id,
            reported_at,
            COALESCE(is_hourly_rollup, FALSE) AS is_hourly_rollup,
            COALESCE(is_daily_rollup, FALSE) AS is_daily_rollup
        FROM iot_th_reading
        GROUP BY 1, 2, 3, 4
        HAVING COUNT(DISTINCT (temperature, humidity)) > 1
    )
    SELECT reading.*
    FROM iot_th_reading reading
    JOIN conflicts USING (sensor_id, reported_at)
    WHERE COALESCE(reading.is_hourly_rollup, FALSE) = conflicts.is_hourly_rollup
      AND COALESCE(reading.is_daily_rollup, FALSE) = conflicts.is_daily_rollup
    ORDER BY reading.sensor_id, reading.reported_at, reading.create_date, reading.id
) TO '/tmp/iot_th_conflicting_readings_before_19.0.1.0.19.csv' CSV HEADER;
```

## Controlled upgrade

1. Record the exact Git commit and create checksums for the module artifact.
2. Back up the database and current module directory; verify both artifacts are readable.
3. Stop the IoT bridge and Odoo so no readings arrive during schema migration.
4. Install the exact tested artifact and run the non-HTTP Odoo module upgrade with `--stop-after-init`.
5. Start Odoo, then the IoT bridge, and verify service health before accepting the upgrade.

## Post-upgrade gates

```sql
SELECT installed_version
FROM ir_module_module
WHERE name = 'iot_control_center';

SELECT COUNT(*) AS duplicate_groups
FROM (
    SELECT 1
    FROM iot_th_reading
    GROUP BY
        sensor_id,
        reported_at,
        COALESCE(is_hourly_rollup, FALSE),
        COALESCE(is_daily_rollup, FALSE)
    HAVING COUNT(*) > 1
) duplicates;

SELECT indexdef
FROM pg_indexes
WHERE indexname = 'iot_th_reading_identity_uniq';

SELECT COUNT(*) AS missing_rollup_extrema
FROM iot_th_reading
WHERE temperature_min IS NULL
   OR temperature_max IS NULL
   OR humidity_min IS NULL
   OR humidity_max IS NULL
   OR sample_count < 1;
```

Also verify:

- Chart legends show a custom probe name or location label plus the technical code.
- Hourly, daily, and raw modes do not mix incompatible rollup rows.
- The latest value, online status, alerts, and reading counts continue updating.
- No new duplicate/conflict or traceback messages appear in scoped Odoo/bridge logs.
- Threshold/group assignments are reviewed manually; the upgrade must not auto-correct them.

## Rollback

Stop the bridge and Odoo, restore both the database backup and previous module artifact, then restart Odoo followed by the bridge. Re-run service, ingestion, chart, alert, and log checks before declaring rollback complete.
