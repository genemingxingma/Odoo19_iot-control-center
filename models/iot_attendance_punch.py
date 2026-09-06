import hashlib
import json
from datetime import timedelta

from odoo import _, SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError, ValidationError


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
    device_uid = fields.Char(string="Device UID")
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
    display_message = fields.Char(compute="_compute_display_message", string="Message")

    @api.depends("message", "error_code", "state")
    @api.depends_context("lang")
    def _compute_display_message(self):
        labels = {
            "no_employee_mapping": _("No employee mapping found for this punch."),
            "no_open_attendance": _("Cannot check out without an open attendance."),
            "stale_open_attendance": _("The open attendance is outside the allowed shift duration."),
            "open_attendance_exists": _("Employee already has an open attendance."),
            "processing_error": _("Could not match this punch. Review overlapping or incomplete attendance records."),
            "employee_company_mismatch": _("The employee and device belong to different companies."),
            "duplicate_attendance": _("This timestamp is already recorded in attendance."),
        }
        for rec in self:
            rec.display_message = labels.get(rec.error_code) or (_("Processed") if rec.state == "processed" else rec.message)

    error_code = fields.Char(index=True)
    unique_hash = fields.Char(required=True, copy=False, index=True)

    _unique_hash = models.Constraint(
        "UNIQUE(unique_hash)",
        "The same punch cannot be imported twice.",
    )

    @api.constrains("employee_id", "device_id")
    def _check_employee_company(self):
        for rec in self:
            if rec.employee_id and rec.employee_id.company_id != rec.device_id.company_id:
                raise ValidationError(_("The employee and attendance device must belong to the same company."))

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
        creator = self.with_user(SUPERUSER_ID).sudo() if self.env.context.get("iot_attendance_ingest") else self
        records = super(IoTAttendancePunch, creator).create(vals_list)
        records._process_punches()
        return records

    def _mark(self, state, message, attendance=None, error_code=False):
        values = {"state": state, "message": message, "error_code": error_code or False}
        if attendance:
            values["attendance_id"] = attendance.id
        self.write(values)

    def _max_open_delta(self):
        raw = self.env["ir.config_parameter"].sudo().get_param("iot_control_center.attendance_max_open_hours", "16")
        try:
            hours = max(int(raw or 16), 1)
        except Exception:
            hours = 16
        return timedelta(hours=hours)

    def _is_open_attendance_matchable(self, attendance):
        self.ensure_one()
        if not attendance or not self.punch_time or not attendance.check_in:
            return False
        if self.punch_time <= attendance.check_in:
            return False
        if self.punch_time - attendance.check_in > self._max_open_delta():
            return False
        return True  # A bounded shift may cross midnight; the execution user timezone is irrelevant.

    def _get_open_attendance(self):
        self.ensure_one()
        if not self.employee_id:
            return self.env["hr.attendance"]
        return self.env["hr.attendance"].with_user(SUPERUSER_ID).sudo().search(
            [("employee_id", "=", self.employee_id.id), ("check_out", "=", False)],
            order="check_in desc, id desc",
            limit=1,
        )

    def _attendance_service(self):
        return self.env["hr.attendance"].with_user(SUPERUSER_ID).sudo().with_context(
            mail_create_nolog=True,
            mail_create_nosubscribe=True,
            mail_notrack=True,
            tracking_disable=True,
        )

    def _process_punches(self):
        for punch in self.sorted(key=lambda rec: (rec.punch_time or fields.Datetime.now(), rec.id)):
            if punch.state != "new":
                continue
            try:
                with self.env.cr.savepoint():
                    punch._process_one()
            except UserError:
                # Preserve the punch for review without poisoning the remaining
                # employees in this batch. Database failures still propagate.
                punch._mark("error", "Attendance matching needs review.", error_code="processing_error")

    def _process_one(self):
        self.ensure_one()
        if not self.employee_id:
            employee = self.device_id._resolve_employee(self.device_user_id, device_uid=self.device_uid)
            if not employee:
                self._mark("error", "No employee mapping found for this punch.", error_code="no_employee_mapping")
                return
            self.employee_id = employee.id
        if self.employee_id.company_id != self.company_id:
            self._mark("error", "Employee company mismatch.", error_code="employee_company_mismatch")
            return
        # Different terminals may report the same employee concurrently.
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", [490021, self.employee_id.id])
        attendance_model = self._attendance_service()
        existing = attendance_model.search([("employee_id", "=", self.employee_id.id),
            "|", ("check_in", "=", self.punch_time), ("check_out", "=", self.punch_time)], limit=1)
        if existing:
            self._mark("ignored", "Timestamp already recorded.", attendance=existing, error_code="duplicate_attendance")
            return
        open_attendance = self._get_open_attendance()
        if self.direction == "out" and not open_attendance:
            self._mark("error", "Cannot check out without an open attendance.", error_code="no_open_attendance")
            return
        if self.direction == "in" and open_attendance:
            self._mark("error", "Employee already has an open attendance.", error_code="open_attendance_exists")
            return
        if open_attendance:
            if not self._is_open_attendance_matchable(open_attendance):
                self._mark("error", "The open attendance is outside the allowed shift duration.", error_code="stale_open_attendance")
                return
            open_attendance.write({"check_out": self.punch_time})
            self._mark("processed", "Matched to an open attendance.", attendance=open_attendance)
        else:
            attendance = attendance_model.create({"employee_id": self.employee_id.id, "check_in": self.punch_time})
            self._mark("processed", "Created check-in attendance.", attendance=attendance)

    @api.model
    def cron_reprocess_pending(self):
        pending = self.search([("state", "=", "new")], order="punch_time asc, id asc", limit=500)
        retry = self.search(
            [
                ("state", "=", "error"),
                ("error_code", "in", ["no_employee_mapping", "transient_error"]),
            ],
            order="punch_time asc, id asc",
            limit=500,
        )
        (pending | retry).write({"state": "new", "message": False, "error_code": False})
        (pending | retry)._process_punches()
