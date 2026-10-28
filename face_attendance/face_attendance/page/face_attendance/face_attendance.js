frappe.pages["face-attendance"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "Face Attendance",
        single_column: true
    });

    page.main.html(`
        <div class="face-attendance-wrap" style="max-width:900px;margin:0 auto">
          <div class="alert alert-info">
            Face identification only suggests an employee. You must confirm IN or OUT to create an Employee Checkin.
            Camera access requires HTTPS (or localhost) and browser permission.
          </div>
          <div class="row">
            <div class="col-md-7">
              <video id="fa-video" autoplay playsinline muted style="width:100%;max-height:440px;background:#111;border-radius:8px"></video>
              <canvas id="fa-canvas" style="display:none"></canvas>
              <div class="mt-3">
                <button class="btn btn-default" id="fa-start">Start Camera</button>
                <button class="btn btn-primary" id="fa-identify" disabled>Identify Employee</button>
              </div>
            </div>
            <div class="col-md-5">
              <div class="form-group">
                <label for="fa-employee">Employee ID (HR enrollment only)</label>
                <input class="form-control" id="fa-employee" placeholder="e.g. HR-EMP-0001" autocomplete="off">
                <p class="text-muted small">Enrollment/re-enrollment is restricted to HR Manager and System Manager.</p>
                <button class="btn btn-default" id="fa-enroll" disabled>Enroll Face</button>
              </div>
              <hr>
              <div id="fa-status" class="alert alert-secondary">Start the camera to begin.</div>
              <div id="fa-match" style="display:none">
                <h4>Identified employee</h4>
                <p><strong id="fa-match-name"></strong></p>
                <p>Similarity: <span id="fa-score"></span></p>
                <p class="text-muted small">Verify the displayed identity before confirming attendance.</p>
                <button class="btn btn-success" id="fa-in">Confirm IN</button>
                <button class="btn btn-warning" id="fa-out">Confirm OUT</button>
              </div>
            </div>
          </div>
        </div>
    `);

    const video = page.main.find("#fa-video")[0];
    const canvas = page.main.find("#fa-canvas")[0];
    const startBtn = page.main.find("#fa-start");
    const identifyBtn = page.main.find("#fa-identify");
    const enrollBtn = page.main.find("#fa-enroll");
    const status = page.main.find("#fa-status");
    const matchBox = page.main.find("#fa-match");
    const employeeInput = page.main.find("#fa-employee");
    let stream = null;
    let confirmationToken = null;
    let busy = false;

    function setStatus(message, kind = "secondary") {
        status.removeClass("alert-secondary alert-info alert-success alert-warning alert-danger")
              .addClass("alert-" + kind).text(message);
    }

    function captureDataUrl() {
        if (!video.videoWidth || !video.videoHeight) {
            throw new Error("Camera is not ready. Wait for the live video, then try again.");
        }
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        return canvas.toDataURL("image/jpeg", 0.9);
    }

    function setBusy(value) {
        busy = value;
        identifyBtn.prop("disabled", value || !stream);
        enrollBtn.prop("disabled", value || !stream);
        page.main.find("#fa-in, #fa-out").prop("disabled", value || !confirmationToken);
    }

    startBtn.on("click", async () => {
        try {
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                throw new Error("Camera API unavailable. Use HTTPS or localhost in a supported browser.");
            }
            stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: "user" }, audio: false
            });
            video.srcObject = stream;
            await video.play();
            identifyBtn.prop("disabled", false);
            enrollBtn.prop("disabled", false);
            setStatus("Camera started. Center one employee's face in the frame.", "success");
        } catch (e) {
            setStatus(e.message || "Unable to access camera.", "danger");
        }
    });

    identifyBtn.on("click", async () => {
        if (busy) return;
        try {
            setBusy(true);
            matchBox.hide();
            confirmationToken = null;
            setStatus("Checking face…", "info");
            const image_data = captureDataUrl();
            const r = await frappe.call({
                method: "face_attendance.api.identify_employee",
                args: { image_data }
            });
            const result = r.message;
            if (!result || !result.employee) throw new Error("No matching employee was returned.");
            confirmationToken = result.confirmation_token;
            page.main.find("#fa-match-name").text(result.employee_name + " (" + result.employee + ")");
            page.main.find("#fa-score").text(Number(result.similarity).toFixed(3));
            matchBox.show();
            setStatus("Employee identified. Confirm the correct person before selecting IN or OUT.", "success");
        } catch (e) {
            const msg = e.message || (e.responseJSON && e.responseJSON._server_messages) || "Face identification failed.";
            setStatus(typeof msg === "string" ? msg : "Face identification failed.", "danger");
        } finally {
            setBusy(false);
        }
    });

    enrollBtn.on("click", async () => {
        if (busy) return;
        const employee = (employeeInput.val() || "").trim();
        if (!employee) {
            setStatus("Enter an Employee ID before enrollment.", "warning");
            return;
        }
        try {
            setBusy(true);
            setStatus("Enrolling face…", "info");
            const image_data = captureDataUrl();
            await frappe.call({
                method: "face_attendance.api.enroll_face",
                args: { employee, image_data }
            });
            setStatus("Face profile enrolled successfully for " + employee + ". The image itself was not stored.", "success");
        } catch (e) {
            const msg = e.message || "Enrollment failed. Check your role and the server logs.";
            setStatus(msg, "danger");
        } finally {
            setBusy(false);
        }
    });

    async function confirm(log_type) {
        if (!confirmationToken || busy) return;
        try {
            setBusy(true);
            setStatus("Creating Employee Checkin…", "info");
            const r = await frappe.call({
                method: "face_attendance.api.confirm_attendance",
                args: { confirmation_token: confirmationToken, log_type }
            });
            confirmationToken = null;
            matchBox.hide();
            setStatus((r.message && r.message.message) || ("Employee Checkin created (" + log_type + ")."), "success");
        } catch (e) {
            setStatus(e.message || "Could not create Employee Checkin.", "danger");
        } finally {
            setBusy(false);
        }
    }

    page.main.find("#fa-in").on("click", () => confirm("IN"));
    page.main.find("#fa-out").on("click", () => confirm("OUT"));

    // Stop camera when the user leaves this Desk page.
    $(wrapper).on("hide", function () {
        if (stream) stream.getTracks().forEach(track => track.stop());
    });
};
