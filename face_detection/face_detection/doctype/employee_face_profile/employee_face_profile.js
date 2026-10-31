frappe.ui.form.on("Employee Face Profile", {
    refresh(frm) {
        update_enrollment_ui(frm);
    }
});

function update_enrollment_ui(frm) {
    frm.dashboard.clear_headline();
    frm.page.remove_inner_button(__("Capture Face"));
    frm.page.remove_inner_button(__("Re-enroll Face"));

    if (frm.is_new()) {
        frm.set_intro(__("Please select an Employee and save the profile first. The Capture Face button will appear after saving."), "blue");
        return;
    }

    if (!frm.doc.is_enrolled || !frm.doc.embedding) {
        frm.set_intro(__("Face is not enrolled yet. Click 'Capture Face' to capture a photo using the camera."), "orange");
        if (frm.doc.employee) {
            frm.add_custom_button(__("Capture Face"), () => {
                capture_face_dialog(frm, 0);
            });
        }
    } else {
        frm.set_intro(__("Face profile is already enrolled for this employee and active."), "green");
        if (frm.doc.employee) {
            frm.add_custom_button(__("Re-enroll Face"), () => {
                frappe.confirm(
                    __("Face profile is already enrolled for this employee ({0}). Do you want to capture a new photo and update their face profile?", [frm.doc.employee]),
                    () => {
                        capture_face_dialog(frm, 1);
                    }
                );
            });
        }
    }
}

function capture_face_dialog(frm, re_enroll = 0) {
    let stream = null;
    let video_element = null;
    let canvas_element = null;

    const dialog = new frappe.ui.Dialog({
        title: __("Capture Face for {0}", [frm.doc.employee]),
        fields: [
            {
                fieldname: "camera_html",
                fieldtype: "HTML"
            }
        ],
        primary_action_label: re_enroll ? __("Re-enroll Face") : __("Enroll Face"),
        primary_action() {
            if (!video_element || !video_element.videoWidth) {
                frappe.msgprint(__("Camera stream is not ready. Please ensure your camera is allowed and running."));
                return;
            }

            canvas_element.width = video_element.videoWidth;
            canvas_element.height = video_element.videoHeight;
            const ctx = canvas_element.getContext("2d");
            ctx.drawImage(video_element, 0, 0, canvas_element.width, canvas_element.height);
            const image_data = canvas_element.toDataURL("image/jpeg", 0.9);

            frappe.call({
                method: "face_detection.api.enroll_face",
                args: {
                    employee: frm.doc.employee,
                    image_data: image_data,
                    re_enroll: re_enroll
                },
                freeze: true,
                freeze_message: __("Extracting Face Embedding..."),
                callback(r) {
                    if (r.message && r.message.already_enrolled) {
                        dialog.hide();
                        frappe.show_alert({
                            message: __(r.message.message || "Face profile is already enrolled for this employee."),
                            indicator: "orange"
                        });
                        return;
                    }
                    if (r.message && r.message.ok) {
                        dialog.hide();
                        frm.reload_doc();
                        frappe.show_alert({
                            message: __("Face profile enrolled successfully!"),
                            indicator: "green"
                        });
                    }
                }
            });
        }
    });

    dialog.show();

    const html_wrapper = dialog.get_field("camera_html").$wrapper;
    html_wrapper.html(`
        <div style="text-align:center;">
            <video id="efp-camera" autoplay playsinline muted style="width:100%;max-height:360px;background:#111;border-radius:8px;"></video>
            <canvas id="efp-canvas" style="display:none;"></canvas>
            <div id="efp-cam-error" class="text-danger mt-2"></div>
        </div>
    `);

    video_element = html_wrapper.find("#efp-camera")[0];
    canvas_element = html_wrapper.find("#efp-canvas")[0];

    navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false })
        .then(s => {
            stream = s;
            video_element.srcObject = s;
            video_element.play();
        })
        .catch(err => {
            html_wrapper.find("#efp-cam-error").text(__("Could not access camera: ") + err.message);
        });

    dialog.$wrapper.on("hidden.bs.modal", () => {
        if (stream) {
            stream.getTracks().forEach(t => t.stop());
        }
    });
}
