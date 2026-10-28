import frappe


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.throw("Please sign in to use Face Attendance.", frappe.PermissionError)
    return context
