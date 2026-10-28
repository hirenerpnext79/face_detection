frappe.pages["face-attendance"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "Face Attendance",
        single_column: true
    });

    const template_html = frappe.templates["face_attendance"] || `
        <div class="fa-container">
            <div class="fa-header-bar">
                <div class="fa-header-title">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M9 3H5a2 2 0 0 0-2 2v4m0 6v4a2 2 0 0 0 2 2h4m6 0h4a2 2 0 0 0 2-2v-4m0-6V5a2 2 0 0 0-2-2h-4"></path>
                        <circle cx="12" cy="10" r="3"></circle>
                        <path d="M7 21v-1a4 4 0 0 1 4-4h2a4 4 0 0 1 4 4v1"></path>
                    </svg>
                    <span>Smart Face Attendance</span>
                    <span class="fa-badge-pill fa-badge-live">
                        <span class="fa-pulse-dot"></span> Live Scan
                    </span>
                </div>
                <div class="fa-header-rule">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                    <span>Auto-marks <strong>IN</strong> on 1st scan &bull; <strong>OUT</strong> on 2nd scan &bull; Max 1 IN / 1 OUT per day</span>
                </div>
            </div>

            <div class="fa-grid-layout">
                <div class="fa-card fa-camera-card">
                    <div class="fa-camera-viewport">
                        <video id="fa-video" autoplay playsinline muted></video>
                        <div class="fa-camera-hud">
                            <div class="fa-scan-target" id="fa-scan-target"></div>
                            <div class="fa-hud-badge" id="fa-scan-indicator">
                                <span class="fa-pulse-dot"></span> Auto-Detecting Face
                            </div>
                        </div>
                        <div class="fa-camera-stopped-overlay" id="fa-stopped-overlay" style="display:none;">
                            <div class="fa-stopped-icon">
                                <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <rect x="6" y="4" width="4" height="16"></rect>
                                    <rect x="14" y="4" width="4" height="16"></rect>
                                </svg>
                            </div>
                            <div class="fa-stopped-msg">Camera Paused</div>
                            <div class="fa-stopped-sub">Click "Start Camera" to scan next employee</div>
                        </div>
                    </div>
                    <canvas id="fa-canvas" style="display:none"></canvas>

                    <div id="fa-status" class="fa-status-banner fa-status-info">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                        <span id="fa-status-text">Click "Start Camera" to begin scanning</span>
                    </div>

                    <div class="mt-3">
                        <button class="fa-btn-action" id="fa-start">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                                <polygon points="5 3 19 12 5 21 5 3"></polygon>
                            </svg>
                            <span>Start Camera</span>
                        </button>
                    </div>
                </div>

                <div class="d-flex flex-column" style="gap:20px;">
                    <div class="fa-card" id="fa-match" style="display:none;">
                        <div class="fa-result-hero">
                            <div class="fa-avatar-circle" id="fa-avatar">?</div>
                            <div class="fa-employee-title" id="fa-match-name">--</div>
                            <div class="fa-employee-subtitle" id="fa-match-id">--</div>
                            <div class="fa-metric-tag">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                                <span>Similarity Match: <strong id="fa-score">0.00</strong></span>
                            </div>
                            <div id="fa-attendance-badge"></div>
                        </div>
                    </div>

                    <div class="fa-card text-center" id="fa-idle-card" style="padding:36px 20px;">
                        <div style="opacity: 0.35; margin-bottom: 12px;">
                            <svg width="54" height="54" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <circle cx="12" cy="8" r="5"></circle>
                                <path d="M20 21a8 8 0 1 0-16 0"></path>
                            </svg>
                        </div>
                        <h4 style="font-weight:600; color:#475569; margin-bottom:6px;">Waiting for Employee</h4>
                        <p class="text-muted small" style="margin:0;">Look into the camera frame. Identification and attendance logging is automatic.</p>
                    </div>

                    <div class="fa-enroll-box">
                        <div class="fa-section-header">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="8.5" cy="7.5" r="4"></circle><line x1="20" y1="8" x2="20" y2="14"></line><line x1="23" y1="11" x2="17" y2="11"></line></svg>
                            <span>Enroll New Face Profile</span>
                        </div>
                        <div class="form-group mb-2">
                            <div id="fa-employee-container"></div>
                        </div>
                        <div class="d-flex align-items-center justify-content-between mt-3">
                            <span class="text-muted small">Restricted to HR / System Managers</span>
                            <button class="fa-btn-primary" id="fa-enroll" disabled>
                                Enroll Face
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

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

    employeeControl.$input && employeeControl.$input.on("input change blur", updateLinkIconsVisibility);
    setTimeout(updateLinkIconsVisibility, 200);

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
        enrollBtn.prop("disabled", value || !stream);
        if (value) {
            scanTarget.addClass("active");
        } else {
            scanTarget.removeClass("active");
        }
    }

    function startAutoScan() {
        stopAutoScan();
        if (!stream) {
            scanIndicator.hide();
            return;
        }
        scanIndicator.show();
        autoScanTimer = setInterval(async () => {
            if (busy || !stream) return;
            await performIdentification();
        }, 2200);
    }

    function stopAutoScan() {
        if (autoScanTimer) {
            clearInterval(autoScanTimer);
            autoScanTimer = null;
        }
        scanIndicator.hide();
    }

    function stopCamera(message = "Camera stopped. Click 'Start Camera' for the next employee.") {
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
            enrollBtn.prop("disabled", false);
            startBtn.hide();
            setStatus("Camera active & scanning. Stand in front to record attendance.", "success");
            startAutoScan();
        } catch (e) {
            startBtn.show();
            stoppedOverlay.show();
            setStatus(e.message || "Unable to access camera. Check permissions or click Start Camera.", "danger");
        }
    }

    startBtn.on("click", initCamera);

    async function performIdentification() {
        if (busy) return;
        try {
            setBusy(true);
            const image_data = captureDataUrl();
            const r = await frappe.call({
                method: "face_attendance.api.identify_employee",
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
                    method: "face_attendance.api.confirm_attendance",
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
            // Background scan skips silently without error alert
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
        try {
            setBusy(true);
            setStatus("Enrolling facial profile…", "info");
            const image_data = captureDataUrl();
            await frappe.call({
                method: "face_attendance.api.enroll_face",
                args: { employee, image_data }
            });
            setStatus(`Face profile successfully enrolled for ${employee}.`, "success");
            frappe.show_alert({
                message: __("Face profile enrolled for {0}", [employee]),
                indicator: "green"
            }, 5);
        } catch (e) {
            const msg = e.message || "Enrollment failed. Ensure single face is centered.";
            setStatus(msg, "danger");
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
