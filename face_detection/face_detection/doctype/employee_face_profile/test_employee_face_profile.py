import json
import frappe
from frappe.tests.utils import FrappeTestCase


class TestEmployeeFaceProfile(FrappeTestCase):
    def test_save_profile_without_embedding_allowed(self):
        emp_id = self._get_or_create_test_employee("TEST-SAVENOFACE-001")
        if frappe.db.exists("Employee Face Profile", emp_id):
            frappe.delete_doc("Employee Face Profile", emp_id, force=1)

        profile = frappe.get_doc({
            "doctype": "Employee Face Profile",
            "employee": emp_id,
        })
        profile.insert(ignore_permissions=True)

        self.assertEqual(profile.is_enrolled, 0)
        self.assertIsNone(profile.embedding)

        profile.delete(ignore_permissions=True)

    def test_save_profile_with_embedding(self):
        emp_id = self._get_or_create_test_employee("TEST-SAVEWITHFACE-001")
        if frappe.db.exists("Employee Face Profile", emp_id):
            frappe.delete_doc("Employee Face Profile", emp_id, force=1)

        sample_embedding = json.dumps([0.1, 0.2, 0.3])
        profile = frappe.get_doc({
            "doctype": "Employee Face Profile",
            "employee": emp_id,
            "embedding": sample_embedding,
        })
        profile.insert(ignore_permissions=True)

        self.assertEqual(profile.is_enrolled, 1)
        self.assertIsNotNone(profile.enrolled_on)

        profile.delete(ignore_permissions=True)

    def test_already_enrolled_prevention(self):
        emp_id = self._get_or_create_test_employee("TEST-ALREADYENROLLED-001")
        if frappe.db.exists("Employee Face Profile", emp_id):
            frappe.delete_doc("Employee Face Profile", emp_id, force=1)

        sample_embedding = json.dumps([0.1, 0.2, 0.3])
        profile = frappe.get_doc({
            "doctype": "Employee Face Profile",
            "employee": emp_id,
            "embedding": sample_embedding,
        })
        profile.insert(ignore_permissions=True)

        from face_detection.api import enroll_face, get_face_profile_status
        status = get_face_profile_status(employee=emp_id)
        self.assertTrue(status.get("enrolled"))

        frappe.set_user("Administrator")
        res = enroll_face(employee=emp_id, image_data="data:image/jpeg;base64,dummy", re_enroll=0)
        self.assertFalse(res.get("ok"))
        self.assertTrue(res.get("already_enrolled"))
        self.assertIn("already enrolled", res.get("message"))

        profile.delete(ignore_permissions=True)

    def _get_or_create_test_employee(self, emp_name):
        existing = frappe.db.get_value("Employee", {"employee_name": emp_name}, "name")
        if existing:
            return existing
        emp = frappe.get_doc({
            "doctype": "Employee",
            "first_name": emp_name,
            "employee_name": emp_name,
            "status": "Active",
            "gender": "Male",
            "date_of_birth": "1990-01-01",
            "date_of_joining": "2020-01-01",
        })
        emp.insert(ignore_permissions=True)
        return emp.name
