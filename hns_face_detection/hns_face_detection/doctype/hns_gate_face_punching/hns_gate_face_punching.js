// Copyright (c) 2026, Face Detection and contributors
// For license information, please see license.txt

frappe.ui.form.on("Hns Gate Face Punching", {
	refresh(frm) {
		frm.add_custom_button(__("Open Live Face Scanner"), function() {
			frappe.set_route("hns-face-detection-page");
		}).addClass("btn-primary");

		frm.add_custom_button(__("Open in OMS App"), function() {
			window.open("/oms/face-punching", "_blank");
		});
	},
});
