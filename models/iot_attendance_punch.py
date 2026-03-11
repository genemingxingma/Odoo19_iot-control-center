import hashlib
import json

from odoo import api, fields, models


class IoTAttendancePunch(models.Model):
    _name = "iot.attendance.punch"
    _description = "IoT Attendance Punch"
    _order = "punch_time desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    device_id = fields.Many2one("iot.attendance.device", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="device_id.company_id", store=True, readonly=True)
    employee_id = fields.Many2one("hr.employee", index=True, ondelete="set null")
    attendance_id = fields.Many2one("hr.attendance", readonly=True, ondelete="set null")
    device_user_id = fields.Char(index=True)
    device_uid = fields.Char()
    punch_time = fields.Datetime(required=True, index=True)
    direction = fields.Selection([("auto", "Auto"), ("in", "Check In"), ("out", "Check Out")], default="auto", required=True, index=True)
    source = fields.Selection(
        [("device_pull", "Device Pull"), ("adms", "ADMS Push"), ("webhook", "Webhook"), ("manual", "Manual")],
        required=True,
        default="adms",
        index=True,
    )
    state = fields.Selection([("new", "New"), ("processed", "Processed"), ("ignored", "Ignored"), ("error", "Error")], default="new", required=True, index=True)
    raw_payload = fields.Text()
    message = fields.Char()
    unique_hash = fields.Char(required=True, copy=False, index=True)

    _sql_constraints = [
        ("iot_attendance_punch_unique_hash", "unique(unique_hash)", "The same punch cannot be imported twice."),
    ]

    @api.depends("employee_id.name", "device_user_id", "punch_time")
    def _compute_name(self):
        for rec in self:
            employee = rec.employee_id.name or rec.device_user_id or "Unknown"
            timestamp = fields.Datetime.to_string(rec.punch_time) if rec.punch_time else ""
            rec.name = f"{employee} @ {timestamp}"

    @api.model
    def _build_unique_hash(self, values):
        raw = "|".join(
            [
                str(values.get("device_id") or ""),
                str(values.get("device_user_id") or ""),
                str(values.get("device_uid") or ""),
                str(values.get("punch_time") or ""),
                str(values.get("direction") or "auto"),
            ]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("unique_hash"):
                vals["unique_hash"] = self._build_unique_hash(vals)
            raw_payload = vals.get("raw_payload")
            if raw_payload and not isinstance(raw_payload, str):
                vals["raw_payload"] = json.dumps(raw_payload, ensure_ascii=True)
        records = super().create(vals_list)
        records._process_punches()
        return records

    def _mark(self, state, message, attendance=None):
        values = {"state": state, "message": message}
        if attendance:
            values["attendance_id"] = attendance.id
        self.write(values)

    def _get_open_attendance(self):
        self.ensure_one()
        if not self.employee_id:
            return self.env["hr.attendance"]
        return self.env["hr.attendance"].search(
            [("employee_id", "=", self.employee_id.id), ("check_out", "=", False)],
            order="check_in desc, id desc",
            limit=1,
        )

    def _process_punches(self):
        for punch in self.sorted(key=lambda rec: (rec.punch_time or fields.Datetime.now(), rec.id)):
            if punch.state != "new":
                continue
            if not punch.employee_id:
                punch._mark("error", "No employee mapping found for this punch.")
                continue
            open_attendance = punch._get_open_attendance()
            if punch.direction == "out":
                if not open_attendance:
                    punch._mark("error", "Cannot check out without an open attendance.")
                    continue
                if punch.punch_time <= open_attendance.check_in:
                    punch._mark("ignored", "Checkout time is not later than check-in.")
                    continue
                open_attendance.write({"check_out": punch.punch_time})
                punch._mark("processed", "Matched to an open attendance.", attendance=open_attendance)
                continue
            if punch.direction == "in":
                if open_attendance:
                    punch._mark("ignored", "Employee already has an open attendance.")
                    continue
                attendance = self.env["hr.attendance"].create({"employee_id": punch.employee_id.id, "check_in": punch.punch_time})
                punch._mark("processed", "Created check-in attendance.", attendance=attendance)
                continue
            if open_attendance and punch.punch_time > open_attendance.check_in:
                open_attendance.write({"check_out": punch.punch_time})
                punch._mark("processed", "Auto-matched as check-out.", attendance=open_attendance)
            else:
                attendance = self.env["hr.attendance"].create({"employee_id": punch.employee_id.id, "check_in": punch.punch_time})
                punch._mark("processed", "Auto-created as check-in.", attendance=attendance)

    @api.model
    def cron_reprocess_pending(self):
        self.search([("state", "=", "new")], order="punch_time asc, id asc", limit=500)._process_punches()
