import json
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime
from face_attendance.api import extract_embedding_from_file_or_data


class EmployeeFaceProfile(Document):
    def validate(self):
        try:
            self.validate_employee()
            self.set_employee_name()
            self.process_face_image()
            self.check_enrollment_status()
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Face Attendance: validate employee profile failed")
            raise

    def validate_employee(self):
        if not self.employee:
            frappe.throw("Employee is required.")
        if not frappe.db.exists("Employee", self.employee):
            frappe.throw(f"Selected Employee {self.employee} does not exist.")

    def set_employee_name(self):
        if not self.employee_name:
            self.employee_name = frappe.db.get_value("Employee", self.employee, "employee_name")

    def process_face_image(self):
        if self.image and (self.has_value_changed("image") or not self.embedding):
            embedding = extract_embedding_from_file_or_data(self.image)
            self.embedding = json.dumps(embedding.tolist(), separators=(",", ":"))
            self.enrolled_on = now_datetime()
            self.enrolled_by = frappe.session.user
            self.is_enrolled = 1

        if not self.image and not self.embedding:
            employee_image = frappe.db.get_value("Employee", self.employee, "image")
            if employee_image:
                embedding = extract_embedding_from_file_or_data(employee_image)
                self.image = employee_image
                self.embedding = json.dumps(embedding.tolist(), separators=(",", ":"))
                self.enrolled_on = now_datetime()
                self.enrolled_by = frappe.session.user
                self.is_enrolled = 1

    def check_enrollment_status(self):
        if self.embedding:
            self.is_enrolled = 1
        else:
            self.is_enrolled = 0
            frappe.throw("Face Embedding is required. Please attach a Face Image or capture a photo using the camera.")
