"""Explicit cutover, not a compatibility layer for mixed-granularity history."""

def migrate(cr, version):
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", ["iot_control_center.v2_discard_monitoring_history"])
    confirmed = cr.fetchone()
    if not confirmed or confirmed[0].lower() != "true":
        raise RuntimeError("V2 cutover requires a verified backup and explicit v2_discard_monitoring_history=true authorization")
    # Only module monitoring history. HR attendance and other business data stay intact.
    cr.execute("DELETE FROM iot_th_alert")
    cr.execute("DELETE FROM iot_th_reading")
    cr.execute("DROP INDEX IF EXISTS iot_th_reading_identity_uniq")
    cr.execute("ALTER TABLE iot_th_sensor DROP CONSTRAINT IF EXISTS iot_th_sensor_node_probe_uniq")
    cr.execute("UPDATE iot_th_sensor SET reading_count=0, last_reported_at=NULL, last_temperature=0, last_humidity=0")
    cr.execute("UPDATE iot_th_sensor s SET active=FALSE FROM iot_th_gateway g WHERE s.gateway_id=g.id AND (g.company_id IS NULL OR s.company_id IS DISTINCT FROM g.company_id)")
    cr.execute("UPDATE ir_config_parameter SET value='True' WHERE key='iot_control_center.middleware_enabled'")
