import json

from odoo import _, fields, models
from odoo.exceptions import UserError


class IoTFirmwarePushWizard(models.TransientModel):
    _name = "iot.firmware.push.wizard"
    _description = "Push Firmware to Devices"

    firmware_id = fields.Many2one("iot.firmware", required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    department_id = fields.Many2one("iot.department", domain="[('company_id', '=', company_id)]")
    location_id = fields.Many2one("iot.location", domain="[('company_id', '=', company_id)]")
    device_ids = fields.Many2many("iot.device", string="Devices")

    def _domain_devices(self):
        self.ensure_one()
        domain = [("company_id", "=", self.company_id.id), ("active", "=", True)]
        if self.department_id:
            domain.append(("department_id", "=", self.department_id.id))
        if self.location_id:
            domain.append(("location_id", "=", self.location_id.id))
        if self.device_ids:
            domain.append(("id", "in", self.device_ids.ids))
        return domain

    def action_push(self):
        self.ensure_one()
        devices = self.env["iot.device"].search(self._domain_devices())
        if not devices:
            raise UserError(_("No matched devices for push."))

        firmware = self.firmware_id
        ok_count = 0
        failed = []
        for device in devices:
            try:
                url = firmware.build_download_url(device)
                payload = {
                    "url": url,
                    "version": firmware.version,
                }
                # Keep batch push robust: one failure should not abort all devices.
                published = device._publish_command("upgrade", payload, raise_on_fail=False)
                if not published:
                    failed.append("%s: MQTT publish failed" % (device.switch_id_display or device.display_name))
                    continue
                now = fields.Datetime.now()
                device.write(
                    {
                        "firmware_target_version": firmware.version,
                        "firmware_upgrade_requested_at": now,
                        "firmware_upgrade_state": "pending",
                    }
                )
                self.env["iot.firmware.upgrade.log"].create(
                    {
                        "device_id": device.id,
                        "firmware_id": firmware.id,
                        "target_version": firmware.version or "",
                        "state": "pending",
                        "requested_at": now,
                        "command_payload": json.dumps(payload, ensure_ascii=False),
                    }
                )
                ok_count += 1
            except Exception as exc:
                failed.append("%s: %s" % ((device.switch_id_display or device.display_name), str(exc)))

        if ok_count == 0:
            detail = "\n".join(failed[:5]) if failed else _("Unknown error")
            raise UserError(_("No upgrade command sent successfully.\n%s") % detail)

        msg = _("Upgrade command sent to %s device(s).") % ok_count
        if failed:
            msg += "\n" + _("Failed: %s") % len(failed)
            msg += "\n" + "\n".join(failed[:3])
            if len(failed) > 3:
                msg += "\n..."

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Firmware Push"),
                "message": msg,
                "sticky": bool(failed),
                "type": "warning" if failed else "success",
            },
        }
