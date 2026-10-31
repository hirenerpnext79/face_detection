import frappe
from frappe.model.document import Document


class FaceDetectionLog(Document):
    def validate(self):
        try:
            if not self.employee:
                frappe.throw("Employee is required.")
            if not frappe.db.exists("Employee", self.employee):
                frappe.throw(f"Employee {self.employee} does not exist.")
            if not self.employee_name:
                self.employee_name = frappe.db.get_value("Employee", self.employee, "employee_name")
            if not self.punch_category:
                gate_settings = frappe.get_single("Gate Face Punching")
                self.punch_category = gate_settings.punch_category if gate_settings else "Attendance"
            if not self.log_type:
                frappe.throw("Log Type is required.")
            if not self.time:
                self.time = frappe.utils.now_datetime()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Face Detection: validate log error")
            raise
