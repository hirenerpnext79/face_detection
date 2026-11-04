import frappe
from frappe.model.document import Document


class HnsFaceDetectionLog(Document):
    def validate(self):
        try:
            if self.action != "Reject":
                if not self.employee:
                    frappe.throw("Employee is required.")
                if not frappe.db.exists("Employee", self.employee):
                    frappe.throw(f"Employee {self.employee} does not exist.")
                if not self.employee_name:
                    self.employee_name = frappe.db.get_value("Employee", self.employee, "employee_name")
            else:
                if self.employee and frappe.db.exists("Employee", self.employee) and not self.employee_name:
                    self.employee_name = frappe.db.get_value("Employee", self.employee, "employee_name")
                elif not self.employee_name:
                    self.employee_name = "Unidentified Person"

            if not self.punch_category:
                gate_settings = frappe.get_single("Hns Gate Face Punching")
                self.punch_category = gate_settings.punch_category if gate_settings and gate_settings.punch_category else "Attendance"
            if not self.log_type:
                self.log_type = "IN"
            if not self.time:
                self.time = frappe.utils.now_datetime()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Face Detection: validate log error")
            raise
