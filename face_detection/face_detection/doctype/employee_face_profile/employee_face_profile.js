frappe.ui.form.on("Employee Face Profile", {
    refresh(frm) {
        if (!frm.is_new() && frm.doc.employee) {
            frm.add_custom_button(__("Capture Face"), () => {
                capture_face_dialog(frm);
            }, __("Actions"));
        }
    }
});

function capture_face_dialog(frm) {
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
        primary_action_label: __("Enroll Face"),
        primary_action() {
            if (!video_element || !video_element.videoWidth) {
                frappe.msgprint(__("Camera stream is not ready."));
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
                    image_data: image_data
                },
                freeze: true,
                freeze_message: __("Extracting Face Embedding..."),
                callback(r) {
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
