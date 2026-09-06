"""Convert the inherited V1 translated field into a V2 text snapshot."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT atttypid::regtype::text FROM pg_attribute
        WHERE attrelid = 'iot_th_reading'::regclass
          AND attname = 'sensor_location_detail' AND NOT attisdropped
    """)
    row = cr.fetchone()
    _logger.info("IoT location snapshot column before conversion: %r", row)
    if row and row[0] == "jsonb":
        # Odoo cannot automatically turn a translated related column back into
        # plain text. Keep an existing label, including a non-English fallback.
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
    row = cr.fetchone()
    if not row or row[0] != "character varying":
        raise RuntimeError("IoT location snapshot column was not converted to text")
    _logger.info("IoT location snapshot column conversion verified")
