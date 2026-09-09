"""Retire the V1 translation marker before Odoo rebuilds snapshot fields."""
from odoo import api, SUPERUSER_ID


def _migrate_snapshot(cr, registry):
    cr.execute("""
        SELECT atttypid::regtype::text FROM pg_attribute
        WHERE attrelid = 'iot_th_reading'::regclass
          AND attname = 'sensor_location_detail' AND NOT attisdropped
    """)
    row = cr.fetchone()
    if row and row[0] == "jsonb":
        cr.execute("""
            ALTER TABLE iot_th_reading
            ALTER COLUMN sensor_location_detail TYPE varchar
            USING CASE
                WHEN jsonb_typeof(sensor_location_detail) = 'object' THEN
                    COALESCE(sensor_location_detail ->> 'en_US',
                             jsonb_path_query_first(sensor_location_detail, '$.*') #>> '{}')
                ELSE sensor_location_detail #>> '{}'
            END
        """)
    cr.execute("""
        SELECT atttypid::regtype::text FROM pg_attribute
        WHERE attrelid = 'iot_th_reading'::regclass
          AND attname = 'sensor_location_detail' AND NOT attisdropped
    """)
    if cr.fetchone() != ("character varying",):
        raise RuntimeError("IoT location snapshot must be a plain-text column")
    cr.execute("""
        UPDATE ir_model_fields SET translate = NULL
        WHERE model = 'iot.th.reading' AND name = 'sensor_location_detail'
    """)
    # Odoo 19 snapshots this metadata before pre-migrations and otherwise
    # overrides even an explicit translate=False during the current upgrade.
    registry._database_translated_fields.pop("iot.th.reading.sensor_location_detail", None)


def migrate(cr, version):
    _migrate_snapshot(cr, api.Environment(cr, SUPERUSER_ID, {}).registry)
