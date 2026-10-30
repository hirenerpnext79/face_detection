import json
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from face_detection.api import extract_embedding_from_file_or_data


class EmployeeFaceProfile(Document):
    def validate(self):
        try:
            self.validate_employee()
            self.set_employee_name()
            self.populate_embedding_from_employee_if_missing()
            self.check_enrollment_status()
        except frappe.ValidationError:
            raise
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Face Detection: validate employee profile failed")
            raise

    def validate_employee(self):
        try:
            if not self.employee:
                frappe.throw("Employee is required.")
            if not frappe.db.exists("Employee", self.employee):
                frappe.throw(f"Selected Employee {self.employee} does not exist.")
        except frappe.ValidationError:
            raise
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Face Detection: validate employee failed")
            raise

    def set_employee_name(self):
        try:
            if not self.employee_name:
                self.employee_name = frappe.db.get_value("Employee", self.employee, "employee_name")
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Face Detection: set employee name failed")
            raise

    def populate_embedding_from_employee_if_missing(self):
        try:
            if not self.embedding:
                employee_image = frappe.db.get_value("Employee", self.employee, "image")
                if employee_image:
                    try:
                        embedding = extract_embedding_from_file_or_data(employee_image)
                        self.embedding = json.dumps(embedding.tolist(), separators=(",", ":"))
                        self.enrolled_on = now_datetime()
                        self.enrolled_by = frappe.session.user
                        self.is_enrolled = 1
                    except Exception:
                        frappe.log_error(frappe.get_traceback(), "Face Detection: auto extraction from employee image failed")
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Face Detection: populate embedding failed")
            raise

    def check_enrollment_status(self):
        try:
            if self.embedding:
                self.is_enrolled = 1
                if not self.enrolled_on:
                    self.enrolled_on = now_datetime()
                if not self.enrolled_by:
                    self.enrolled_by = frappe.session.user
            else:
                self.is_enrolled = 0
                frappe.msgprint("Face profile saved. Face embedding is missing; please capture a photo using the camera to complete enrollment.", alert=True, indicator="orange")
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Face Detection: check enrollment status failed")
            raise
