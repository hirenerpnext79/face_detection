frappe.pages["face-detection-kiosk"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "Face Detection",
        single_column: true
    });

    let template_html = "";
    if (typeof frappe.templates["face_detection_kiosk"] === "function") {
        template_html = frappe.render_template("face_detection_kiosk", {});
    } else if (typeof frappe.templates["face_detection_kiosk"] === "string") {
        template_html = frappe.templates["face_detection_kiosk"];
    } else {
        template_html = `
            <div class="fa-kiosk-container">
                <div class="fa-grid-layout">
                    <div class="fa-panel fa-info-panel">
                        <div class="fa-panel-header">
                            <div class="fa-panel-title">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                                    <polyline points="14 2 14 8 20 8"></polyline>
                                    <line x1="16" y1="13" x2="8" y2="13"></line>
                                    <line x1="16" y1="17" x2="8" y2="17"></line>
                                    <polyline points="10 9 9 9 8 9"></polyline>
                                </svg>
                                <span>Attendance Status</span>
                            </div>
                            <span class="fa-badge-pill fa-badge-live">
                                <span class="fa-pulse-dot"></span> Live
                            </span>
                        </div>
                        <div class="fa-card fa-result-card" id="fa-match" style="display:none;">
                            <div class="fa-result-hero">
                                <div class="fa-avatar-circle" id="fa-avatar">?</div>
                                <div class="fa-employee-title" id="fa-match-name">--</div>
                                <div class="fa-employee-subtitle" id="fa-match-id">--</div>
                                <div class="fa-metric-tag">
                                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                                    <span>Similarity: <strong id="fa-score">0.00</strong></span>
                                </div>
                                <div id="fa-attendance-badge"></div>
                            </div>
                        </div>
                        <div class="fa-card text-center fa-idle-card" id="fa-idle-card">
                            <div style="opacity: 0.35; margin-bottom: 6px;">
                                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                    <circle cx="12" cy="8" r="5"></circle>
                                    <path d="M20 21a8 8 0 1 0-16 0"></path>
                                </svg>
                            </div>
                            <h4 style="font-weight:600; color:#475569; margin-bottom:4px; font-size:14px;">Waiting for Employee</h4>
                            <p class="text-muted small" style="margin:0;">Attendance log and employee details will appear here upon scanning.</p>
                        </div>
                    </div>
                    <div class="fa-panel fa-camera-panel">
                        <div class="fa-panel-header">
                            <div class="fa-panel-title">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
                                    <circle cx="12" cy="13" r="4"></circle>
                                </svg>
                                <span>Camera Scanner</span>
                            </div>
                            <div class="fa-hud-badge" id="fa-scan-indicator">
                                <span class="fa-pulse-dot"></span> Auto-Detecting
                            </div>
                        </div>
                        <div class="fa-card fa-camera-card">
                            <div class="fa-camera-viewport">
                                <video id="fa-video" autoplay playsinline muted></video>
                                <div class="fa-camera-hud"></div>
                                <div class="fa-camera-stopped-overlay" id="fa-stopped-overlay">
                                    <div class="fa-stopped-icon">
                                        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <circle cx="12" cy="12" r="10"></circle>
                                            <polygon points="10 8 16 12 10 16 10 8" fill="currentColor"></polygon>
                                        </svg>
                                    </div>
                                    <div class="fa-stopped-msg">Camera Idle</div>
                                    <div class="fa-stopped-sub">Click "Start Camera" to scan employee</div>
                                </div>
                            </div>
                            <canvas id="fa-canvas" style="display:none"></canvas>
                            <div id="fa-status" class="fa-status-banner fa-status-info">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                                <span id="fa-status-text">Click "Start Camera" to begin scanning</span>
                            </div>
                            <div class="fa-card-footer mt-auto">
                                <button class="fa-btn-action" id="fa-start">
                                    <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
                                        <polygon points="5 3 19 12 5 21 5 3"></polygon>
                                    </svg>
                                    <span>Start Camera</span>
                                </button>
                            </div>
                        </div>
                    </div>
                    <div class="fa-panel fa-enrollment-panel">
                        <div class="fa-panel-header">
                            <div class="fa-panel-title">
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                                    <circle cx="8.5" cy="7.5" r="4"></circle>
                                    <line x1="20" y1="8" x2="20" y2="14"></line>
                                    <line x1="23" y1="11" x2="17" y2="11"></line>
                                </svg>
                                <span>Profile Enrollment</span>
                            </div>
                            <span class="fa-badge-pill fa-badge-admin">HR Admin</span>
                        </div>
                        <div class="fa-card fa-enroll-card">
                            <div class="fa-enroll-instruction">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                                <span>Select an employee and align their face in the camera to register face data.</span>
                            </div>
                            <div class="form-group mb-3">
                                <label class="fa-field-label">Select Employee</label>
                                <div id="fa-employee-container"></div>
                            </div>
                            <div class="fa-card-footer mt-auto">
                                <button class="fa-btn-action fa-btn-enroll" id="fa-enroll" disabled>
                                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="8.5" cy="7.5" r="4"></circle><polyline points="17 11 19 13 23 9"></polyline></svg>
                                    <span>Capture & Enroll Face</span>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    page.main.html(template_html);

    const video = page.main.find("#fa-video")[0];
    const canvas = page.main.find("#fa-canvas")[0];
    const startBtn = page.main.find("#fa-start");
    const enrollBtn = page.main.find("#fa-enroll");
    const statusBox = page.main.find("#fa-status");
    const statusText = page.main.find("#fa-status-text");
    const matchBox = page.main.find("#fa-match");
    const idleCard = page.main.find("#fa-idle-card");
    const scanIndicator = page.main.find("#fa-scan-indicator");
    const scanTarget = page.main.find("#fa-scan-target");
    const stoppedOverlay = page.main.find("#fa-stopped-overlay");

    let stream = null;
    let busy = false;
    let autoScanTimer = null;
    let isEnrollmentMode = false;
    let lastIdentifiedEmployee = null;
    let lastIdentifiedTime = 0;

    const employeeControl = frappe.ui.form.make_control({
        parent: page.main.find("#fa-employee-container"),
        df: {
            fieldtype: "Link",
            fieldname: "employee",
            options: "Employee",
            placeholder: "Search & Select Employee...",
            only_input: true,
            change: function () {
                updateLinkIconsVisibility();
                syncEnrollmentState();
            },
            get_query: function () {
                return {
                    filters: {
                        status: "Active"
                    }
                };
            }
        },
        render_input: true
    });
    employeeControl.refresh();

    function updateLinkIconsVisibility() {
        const hasVal = !!(employeeControl.get_value() || "").trim();
        page.main.find("#fa-employee-container").toggleClass("has-value", hasVal);
    }

    employeeControl.$input && employeeControl.$input.on("input change blur", function () {
        updateLinkIconsVisibility();
        syncEnrollmentState();
    });
    setTimeout(updateLinkIconsVisibility, 200);

    function syncEnrollmentState() {
        const selectedEmployee = (employeeControl.get_value() || "").trim();
        isEnrollmentMode = Boolean(selectedEmployee);

        if (isEnrollmentMode) {
            stopAutoScan();
            scanIndicator.html('<span class="fa-pulse-dot" style="background:#3b82f6;"></span> Enrollment Active').show();
            if (stream) {
                enrollBtn.prop("disabled", false);
                setStatus(`Enrollment mode active for ${selectedEmployee}. Center face and click "Capture & Enroll Face".`, "info");
            } else {
                enrollBtn.prop("disabled", true);
                setStatus(`Selected ${selectedEmployee}. Click "Start Camera" to capture and enroll face.`, "warning");
            }
        } else {
            scanIndicator.html('<span class="fa-pulse-dot"></span> Auto-Detecting');
            enrollBtn.prop("disabled", true);
            if (stream) {
                scanIndicator.show();
                startAutoScan();
                setStatus("Camera active & scanning. Stand in front to record attendance.", "success");
            } else {
                scanIndicator.hide();
            }
        }
    }

    function setStatus(message, kind = "info") {
        statusBox.removeClass("fa-status-info fa-status-success fa-status-warning fa-status-danger")
                 .addClass("fa-status-" + kind);
        statusText.text(message);
    }

    function captureDataUrl() {
        if (!video.videoWidth || !video.videoHeight) {
            throw new Error("Camera is not ready. Wait for live video feed.");
        }
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        return canvas.toDataURL("image/jpeg", 0.9);
    }

    function setBusy(value) {
        busy = value;
        enrollBtn.prop("disabled", value || !stream || !isEnrollmentMode);
        if (value) {
            scanTarget.addClass("active");
        } else {
            scanTarget.removeClass("active");
        }
    }

    function startAutoScan() {
        stopAutoScan();
        if (!stream || isEnrollmentMode) {
            scanIndicator.hide();
            return;
        }
        scanIndicator.show();
        autoScanTimer = setInterval(async () => {
            if (busy || !stream || isEnrollmentMode) return;
            await performIdentification();
        }, 2200);
    }

    function stopAutoScan() {
        if (autoScanTimer) {
            clearInterval(autoScanTimer);
            autoScanTimer = null;
        }
        if (!isEnrollmentMode) {
            scanIndicator.hide();
        }
    }

    function stopCamera(message = "Camera stopped. Click 'Start Camera' to begin.") {
        stopAutoScan();
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }
        video.srcObject = null;
        stoppedOverlay.show();
        startBtn.show();
        enrollBtn.prop("disabled", true);
        setStatus(message, "warning");
    }

    async function initCamera() {
        try {
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                throw new Error("Camera API unavailable. Use HTTPS or localhost in a supported browser.");
            }
            stoppedOverlay.hide();
            stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: "user",
                    width: { ideal: 1280 },
                    height: { ideal: 720 }
                },
                audio: false
            });
            video.srcObject = stream;
            await video.play();
            startBtn.hide();

            const selectedEmployee = (employeeControl.get_value() || "").trim();
            if (selectedEmployee) {
                isEnrollmentMode = true;
                stopAutoScan();
                enrollBtn.prop("disabled", false);
                scanIndicator.html('<span class="fa-pulse-dot" style="background:#3b82f6;"></span> Enrollment Active').show();
                setStatus(`Camera active. Center face for ${selectedEmployee} and click "Capture & Enroll Face".`, "info");
            } else {
                isEnrollmentMode = false;
                enrollBtn.prop("disabled", true);
                scanIndicator.html('<span class="fa-pulse-dot"></span> Auto-Detecting').show();
                setStatus("Camera active & scanning. Stand in front to record attendance.", "success");
                startAutoScan();
            }
        } catch (e) {
            startBtn.show();
            stoppedOverlay.show();
            enrollBtn.prop("disabled", true);
            setStatus(e.message || "Unable to access camera. Check permissions or click Start Camera.", "danger");
        }
    }

    startBtn.on("click", initCamera);

    async function performIdentification() {
        if (busy || isEnrollmentMode) return;
        const currentEmployee = (employeeControl.get_value() || "").trim();
        if (currentEmployee) return;

        try {
            setBusy(true);
            const image_data = captureDataUrl();
            const r = await frappe.call({
                method: "face_detection.api.identify_employee",
                args: { image_data }
            });
            const result = r.message;
            if (!result || !result.employee) {
                return;
            }

            const emp = result.employee;
            const empName = result.employee_name || emp;
            const now = Date.now();

            if (emp === lastIdentifiedEmployee && (now - lastIdentifiedTime) < 8000) {
                return;
            }

            lastIdentifiedEmployee = emp;
            lastIdentifiedTime = now;

            const initials = empName.split(" ").map(p => p[0]).filter(Boolean).slice(0, 2).join("").toUpperCase() || "E";
            page.main.find("#fa-avatar").text(initials);
            page.main.find("#fa-match-name").text(empName);
            page.main.find("#fa-match-id").text(emp);
            page.main.find("#fa-score").text(Number(result.similarity).toFixed(3));

            idleCard.hide();
            matchBox.fadeIn(250);

            const action = result.auto_action;

            if (action === "ALREADY_COMPLETED") {
                page.main.find("#fa-attendance-badge").html(
                    '<div class="fa-action-badge fa-badge-completed">Attendance Completed Today (IN & OUT already logged)</div>'
                );
                setStatus(`Attendance already completed today for ${empName}. Camera stopped.`, "warning");
                frappe.show_alert({
                    message: __("Attendance already completed today for {0} (IN & OUT marked).", [empName]),
                    indicator: "blue"
                }, 4);
                stopCamera(`Attendance already completed today for ${empName}. Click "Start Camera" for next employee.`);
                return;
            }

            if (action === "IN" || action === "OUT") {
                setStatus(`Auto-recording ${action} entry for ${empName}…`, "info");
                const confirmRes = await frappe.call({
                    method: "face_detection.api.confirm_attendance",
                    args: {
                        confirmation_token: result.confirmation_token,
                        log_type: action
                    }
                });

                if (confirmRes.message && confirmRes.message.ok) {
                    const badgeClass = action === "IN" ? "fa-badge-in" : "fa-badge-out";
                    page.main.find("#fa-attendance-badge").html(
                        `<div class="fa-action-badge ${badgeClass}">Marked ${action} Successfully</div>`
                    );
                    setStatus(`Successfully recorded ${action} for ${empName}! Camera stopped. Click "Start Camera" for next employee.`, "success");
                    frappe.show_alert({
                        message: __("Successfully recorded {0} for {1}", [action, empName]),
                        indicator: action === "IN" ? "green" : "orange"
                    }, 5);

                    stopCamera(`Marked ${action} for ${empName}. Click "Start Camera" for next employee.`);
                }
            }
        } catch (e) {
        } finally {
            setBusy(false);
        }
    }

    enrollBtn.on("click", async () => {
        if (busy) return;
        const employee = (employeeControl.get_value() || "").trim();
        if (!employee) {
            setStatus("Please select an employee from the dropdown before enrolling.", "warning");
            return;
        }
        if (!stream) {
            setStatus("Camera is not active. Click 'Start Camera' to capture face photo.", "warning");
            return;
        }

        try {
            setBusy(true);
            setStatus("Extracting face features and enrolling profile…", "info");
            const image_data = captureDataUrl();
            const r = await frappe.call({
                method: "face_detection.api.enroll_face",
                args: { employee, image_data }
            });

            if (r.message && r.message.ok) {
                frappe.show_alert({
                    message: __("Face profile enrolled successfully for {0}", [employee]),
                    indicator: "green"
                }, 5);

                employeeControl.set_value("");
                updateLinkIconsVisibility();

                stopCamera(`Face profile enrolled for ${employee}. Camera turned off.`);
                setStatus(`Face profile successfully enrolled for ${employee}. Camera turned off.`, "success");
            }
        } catch (e) {
            const msg = e.message || "Enrollment failed. Ensure single face is centered.";
            setStatus(msg, "danger");
            frappe.show_alert({
                message: __(msg),
                indicator: "red"
            }, 5);
        } finally {
            setBusy(false);
        }
    });

    stopCamera("Camera idle. Click 'Start Camera' to begin.");

    $(wrapper).on("hide", function () {
        stopAutoScan();
        if (stream) stream.getTracks().forEach(track => track.stop());
    });
};
