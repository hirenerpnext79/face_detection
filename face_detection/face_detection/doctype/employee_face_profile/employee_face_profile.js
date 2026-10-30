frappe.ui.form.on("Employee Face Profile", {
    refresh(frm) {
        update_enrollment_ui(frm);
    }
});

function update_enrollment_ui(frm) {
    frm.dashboard.clear_headline();
    frm.page.remove_inner_button(__("Capture Face"));

    if (frm.is_new()) {
        frm.set_intro(__("Please select an Employee and save the profile first. The Capture Face button will appear after saving."), "blue");
        return;
    }

    if (frm.doc.employee) {
        frm.add_custom_button(__("Capture Face"), () => {
            capture_face_dialog(frm);
        });
    }

    if (!frm.doc.is_enrolled || !frm.doc.embedding) {
        frm.set_intro(__("Face is not enrolled yet. Click 'Capture Face' to capture a photo or upload an image."), "orange");
    } else {
        frm.set_intro(__("Face profile is enrolled and active."), "green");
    }
}

function capture_face_dialog(frm) {
    let stream = null;
    let video_element = null;
    let canvas_element = null;
    let uploaded_image_data = null;

    const dialog = new frappe.ui.Dialog({
        title: __("Enroll Face for {0}", [frm.doc.employee]),
        fields: [
            {
                fieldname: "camera_html",
                fieldtype: "HTML"
            }
        ],
        primary_action_label: __("Enroll Face"),
        primary_action() {
            let image_data = uploaded_image_data;

            if (!image_data && video_element && video_element.videoWidth) {
                canvas_element.width = video_element.videoWidth;
                canvas_element.height = video_element.videoHeight;
                const ctx = canvas_element.getContext("2d");
                ctx.drawImage(video_element, 0, 0, canvas_element.width, canvas_element.height);
                image_data = canvas_element.toDataURL("image/jpeg", 0.9);
            }

            if (!image_data) {
                frappe.msgprint(__("Please wait for camera stream or choose an image file."));
                return;
            }

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
            <video id="efp-camera" autoplay playsinline muted style="width:100%;max-height:300px;background:#111;border-radius:8px;"></video>
            <canvas id="efp-canvas" style="display:none;"></canvas>
            <div id="efp-cam-error" class="text-danger mt-2"></div>
        </div>
    `);

    video_element = html_wrapper.find("#efp-camera")[0];
    canvas_element = html_wrapper.find("#efp-canvas")[0];
    const file_input = html_wrapper.find("#efp-file-input")[0];

    file_input.addEventListener("change", (e) => {
        const file = e.target.files && e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (loadEvent) => {
            uploaded_image_data = loadEvent.target.result;
            frappe.show_alert({
                message: __("Photo selected: {0}", [file.name]),
                indicator: "blue"
            });
        };
        reader.readAsDataURL(file);
    });

    navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false })
        .then(s => {
            stream = s;
            video_element.srcObject = s;
            video_element.play();
        })
        .catch(err => {
            html_wrapper.find("#efp-cam-error").text(__("Could not access camera: ") + err.message + __(". Please choose a photo below."));
        });

    dialog.$wrapper.on("hidden.bs.modal", () => {
        if (stream) {
            stream.getTracks().forEach(t => t.stop());
        }
    });
}
