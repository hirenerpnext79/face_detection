// Copyright (c) 2026, Face Detection and contributors
// For license information, please see license.txt

frappe.ui.form.on("Hns Face Detection Log", {
	refresh(frm) {
		frm.page.clear_primary_action();
		frm.disable_save();
	}
});