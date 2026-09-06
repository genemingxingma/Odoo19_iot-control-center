"""Explicit cutover, not a compatibility layer for mixed-granularity history."""


def _check_gateway_identities(cr):
    # V1 created identities from changing source IPs. Do not guess ownership,
    # silently archive named probes, or try to add V2 uniqueness over duplicates.
    checks = (
        ("duplicate gateway identities", """
            SELECT count(*) FROM (
                SELECT serial FROM iot_th_gateway GROUP BY serial HAVING count(*) > 1
            ) duplicates
        """),
        ("empty gateway identities", """
            SELECT count(*) FROM iot_th_gateway WHERE serial IS NULL OR btrim(serial) = ''
        """),
        ("active gateways without company ownership", """
            SELECT count(*) FROM iot_th_gateway WHERE active AND company_id IS NULL
        """),
        ("active probes with inconsistent gateway ownership", """
            SELECT count(*) FROM iot_th_sensor s
            LEFT JOIN iot_th_gateway g ON g.id = s.gateway_id
            WHERE s.active AND (g.id IS NULL OR g.company_id IS NULL
                                OR s.company_id IS DISTINCT FROM g.company_id)
        """),
    )
    blockers = []
    for label, query in checks:
        cr.execute(query)
        count = cr.fetchone()[0]
        if count:
            blockers.append(f"{label}: {count}")
    if blockers:
        raise RuntimeError(
            "V2 gateway identity preflight failed before deleting monitoring history: "
            + "; ".join(blockers)
            + ". Reconcile identities and company ownership in V1 before cutover."
        )


def migrate(cr, version):
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", ["iot_control_center.v2_discard_monitoring_history"])
    confirmed = cr.fetchone()
    if not confirmed or confirmed[0].lower() != "true":
        raise RuntimeError("V2 cutover requires a verified backup and explicit v2_discard_monitoring_history=true authorization")
    _check_gateway_identities(cr)
    # Only module monitoring history. HR attendance and other business data stay intact.
    cr.execute("DELETE FROM iot_th_alert")
    cr.execute("DELETE FROM iot_th_reading")
    cr.execute("DROP INDEX IF EXISTS iot_th_reading_identity_uniq")
    cr.execute("ALTER TABLE iot_th_sensor DROP CONSTRAINT IF EXISTS iot_th_sensor_node_probe_uniq")
    cr.execute("UPDATE iot_th_sensor SET reading_count=0, last_reported_at=NULL, last_temperature=0, last_humidity=0")
    cr.execute("UPDATE ir_config_parameter SET value='True' WHERE key='iot_control_center.middleware_enabled'")
