frappe.pages["face-detection-page"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "",
        single_column: true
    });

    $(frappe.render_template("face_detection_page", {})).appendTo(page.main);
    window.scrollTo(0, 0);
    $(wrapper).find(".page-head, .page-title, .title-area, .title-text").remove();

    const video = page.main.find("#fa-video")[0];
    const canvas = page.main.find("#fa-canvas")[0];
    const captureBtn = page.main.find("#fa-capture-face");
    const stopBtn = page.main.find("#fa-stop-camera");
    const startBtn = page.main.find("#fa-start-camera");
    const enrollBtn = page.main.find("#fa-enroll");
    const punchAlert = page.main.find("#fa-punch-alert");
    const punchBadge = page.main.find("#fa-punch-type-badge");
    const punchEmp = page.main.find("#fa-punch-emp");
    const punchMeta = page.main.find("#fa-punch-meta");
    const scanIndicator = page.main.find("#fa-scan-indicator");
    const scanTarget = page.main.find("#fa-scan-target");
    const stoppedOverlay = page.main.find("#fa-stopped-overlay");
    const overlayTitle = page.main.find("#fa-overlay-title");
    const overlaySub = page.main.find("#fa-overlay-sub");

    let stream = null;
    let busy = false;
    let autoScanTimer = null;
    let logRefreshTimer = null;
    let currentTab = "kiosk";
    let isEnrollmentMode = false;
    let lastIdentifiedEmployee = null;
    let lastIdentifiedTime = 0;
    let resetMatchTimer = null;
    let kioskSettings = { auto_detect: 0, mode: "", punch_category: "" };
    let selectedEmployeeIsEnrolled = false;
    let lastCheckedEmployee = null;

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
                onEmployeeChanged();
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

    async function onEmployeeChanged() {
        const employee = (employeeControl.get_value() || "").trim();
        const statusEl = page.main.find("#fa-enroll-employee-status");

        if (currentTab !== "enrollment") {
            return;
        }

        if (!employee) {
            lastCheckedEmployee = null;
            selectedEmployeeIsEnrolled = false;
            statusEl.hide().empty();
            enrollBtn.prop("disabled", true);
            return;
        }

        if (employee === lastCheckedEmployee) {
            enrollBtn.prop("disabled", selectedEmployeeIsEnrolled || !stream);
            return;
        }

        lastCheckedEmployee = employee;

        try {
            const r = await frappe.call({
                method: "face_detection.api.get_face_profile_status",
                args: { employee }
            });
            const status = r.message;
            if (status && status.enrolled) {
                selectedEmployeeIsEnrolled = true;
                const enrolledDate = status.enrolled_on ? frappe.datetime.str_to_user(status.enrolled_on) : "";
                const dateText = enrolledDate ? ` (${frappe.datetime.comment_when(status.enrolled_on)})` : "";
                statusEl.html(`
                    <div class="fa-enroll-status-alert fa-status-warning">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0; margin-top:2px;">
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="12" y1="8" x2="12" y2="12"></line>
                            <line x1="12" y1="16" x2="12.01" y2="16"></line>
                        </svg>
                        <span>${__("Face profile is already enrolled for this employee ({0}){1}. No need to enroll again.", [employee, dateText])}</span>
                    </div>
                `).show();

                frappe.show_alert({
                    message: __("Face profile is already enrolled for this employee ({0}).", [employee]),
                    indicator: "orange"
                }, 5);

                enrollBtn.prop("disabled", true);
                return;
            }

            selectedEmployeeIsEnrolled = false;
            statusEl.hide().empty();
            enrollBtn.prop("disabled", !stream || !employee);
        } catch (e) {
            selectedEmployeeIsEnrolled = false;
            statusEl.hide().empty();
            enrollBtn.prop("disabled", !stream || !employee);
        }
    }

    employeeControl.$input && employeeControl.$input.on("input change blur", function () {
        updateLinkIconsVisibility();
        onEmployeeChanged();
    });
    setTimeout(updateLinkIconsVisibility, 200);

    function switchTab(tabName) {
        currentTab = tabName;
        page.main.find(".fa-tab-item").removeClass("active");
        page.main.find(`.fa-tab-item[data-tab="${tabName}"]`).addClass("active");

        const mainRow = page.main.find("#fa-main-row");
        const enrollCard = page.main.find("#fa-enroll-card");
        const logsPanel = page.main.find("#fa-logs-panel");
        const topLogsInfo = page.main.find("#fa-top-logs-info");

        if (tabName === "kiosk") {
            mainRow.removeClass("is-enrollment-view");
            enrollCard.hide();
            logsPanel.show();
            topLogsInfo.show();
            isEnrollmentMode = false;
            employeeControl.set_value("");
            selectedEmployeeIsEnrolled = false;
            lastCheckedEmployee = null;
            page.main.find("#fa-enroll-employee-status").hide().empty();
            updateScannerState();
            fetchLogs();
        } else {
            mainRow.addClass("is-enrollment-view");
            logsPanel.hide();
            topLogsInfo.hide();
            enrollCard.show();
            isEnrollmentMode = true;
            stopAutoScan();
            scanIndicator.html('<span class="fa-pulse-dot fa-dot-blue"></span> Profile Enrollment').show();
            employeeControl.refresh();
            onEmployeeChanged();
        }
        updateCameraButtons();
    }

    page.main.find(".fa-tab-item").on("click", function () {
        const tab = $(this).data("tab");
        switchTab(tab);
    });

    async function loadSettings() {
        try {
            const r = await frappe.call({
                method: "face_detection.api.get_kiosk_settings"
            });
            if (r.message) {
                kioskSettings = r.message;
            }
        } catch (e) {
            console.error("Failed to load kiosk settings", e);
        }
        updateScannerState();
        updateCameraButtons();
    }

    function updateCameraButtons() {
        if (!stream) {
            captureBtn.hide();
            stopBtn.hide();
            startBtn.show();
        } else {
            startBtn.hide();
            stopBtn.show();
            if (currentTab === "enrollment" || kioskSettings.auto_detect === 1) {
                captureBtn.hide();
            } else {
                captureBtn.show();
            }
        }
    }

    function updateScannerState() {
        if (currentTab === "enrollment") {
            stopAutoScan();
            scanIndicator.html('<span class="fa-pulse-dot fa-dot-blue"></span> Profile Enrollment').show();
            enrollBtn.prop("disabled", !stream || !employeeControl.get_value() || selectedEmployeeIsEnrolled);
            return;
        }

        enrollBtn.prop("disabled", true);
        if (stream) {
            if (kioskSettings.auto_detect === 1) {
                scanIndicator.html('<span class="fa-pulse-dot"></span> Auto-Detecting').show();
                startAutoScan();
            } else {
                scanIndicator.html('<span class="fa-pulse-dot fa-dot-gray"></span> Manual Mode').show();
                stopAutoScan();
            }
        } else {
            scanIndicator.hide();
            stopAutoScan();
        }
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
        enrollBtn.prop("disabled", value || !stream || currentTab !== "enrollment" || !employeeControl.get_value() || selectedEmployeeIsEnrolled);
        if (value) {
            scanTarget.addClass("active");
        } else {
            scanTarget.removeClass("active");
        }
    }

    function startAutoScan() {
        stopAutoScan();
        if (!stream || currentTab === "enrollment" || kioskSettings.auto_detect !== 1) {
            return;
        }
        autoScanTimer = setInterval(async () => {
            if (busy || !stream || currentTab === "enrollment") return;
            await performIdentification(false);
        }, 2200);
    }

    function stopAutoScan() {
        if (autoScanTimer) {
            clearInterval(autoScanTimer);
            autoScanTimer = null;
        }
    }

    function stopCamera() {
        stopAutoScan();
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }
        video.srcObject = null;
        stoppedOverlay.show();
        overlayTitle.text("Camera Stopped");
        overlaySub.text("Click 'Start Camera' to resume.");
        scanIndicator.hide();
        updateCameraButtons();
    }

    async function initCamera() {
        try {
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                throw new Error("Camera API unavailable. Use HTTPS or localhost in a supported browser.");
            }
            if (stream) {
                stoppedOverlay.hide();
                updateScannerState();
                updateCameraButtons();
                return;
            }
            overlayTitle.text("Connecting Camera...");
            overlaySub.text("Please allow camera access if prompted");
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
            stoppedOverlay.hide();
            updateScannerState();
            updateCameraButtons();
        } catch (e) {
            stoppedOverlay.show();
            overlayTitle.text("Camera Unavailable");
            overlaySub.text(e.message || "Please connect camera or grant permissions, then click Start Camera.");
            scanIndicator.hide();
            stopAutoScan();
            updateCameraButtons();
        }
    }

    function renderLogs(logs, formattedDate, count) {
        if (formattedDate) {
            page.main.find("#fa-current-date").text(formattedDate);
        }
        page.main.find("#fa-logs-count").text(`${count || 0} ${count === 1 ? "log" : "logs"}`);

        const tbody = page.main.find("#fa-logs-tbody");
        if (!logs || !logs.length) {
            tbody.html('<tr><td colspan="4" class="text-center text-muted py-4">No attendance logs found for today.</td></tr>');
            return;
        }

        const rows = logs.map(row => {
            const inOutClass = row.log_type === "IN" ? "fa-badge-log-in" : "fa-badge-log-out";
            const empName = row.employee_name || row.employee || "--";
            const empId = row.employee && row.employee !== row.employee_name ? row.employee : "";

            return `
                <tr>
                    <td>
                        <div class="fa-emp-cell">
                            <span class="fa-emp-name">${frappe.utils.escape_html(empName)}</span>
                            ${empId ? `<span class="fa-emp-id">${frappe.utils.escape_html(empId)}</span>` : ""}
                        </div>
                    </td>
                    <td>${frappe.utils.escape_html(row.time || "--")}</td>
                    <td><span class="fa-badge-log ${inOutClass}">${frappe.utils.escape_html(row.log_type || "--")}</span></td>
                    <td><span class="fa-badge-category">${frappe.utils.escape_html(row.category || "Attendance")}</span></td>
                </tr>
            `;
        }).join("");

        tbody.html(rows);
    }

    async function fetchLogs() {
        try {
            const r = await frappe.call({
                method: "face_detection.api.get_face_detection_logs"
            });
            if (r.message) {
                renderLogs(r.message.logs, r.message.formatted_date, r.message.count);
            }
        } catch (e) {
            console.error("Failed to fetch face detection logs", e);
        }
    }

    async function performIdentification(isManual = false) {
        if (busy || currentTab === "enrollment") return;

        try {
            setBusy(true);
            if (isManual) {
                captureBtn.prop("disabled", true).find("span").text("Capturing...");
            }

            const image_data = captureDataUrl();
            const r = await frappe.call({
                method: "face_detection.api.identify_employee",
                args: { image_data }
            });
            const result = r.message;
            if (!result || !result.employee) {
                if (isManual) {
                    frappe.show_alert({
                        message: __("No matching employee found. Ensure face is clearly visible."),
                        indicator: "orange"
                    }, 4);
                }
                return;
            }

            const emp = result.employee;
            const empName = result.employee_name || emp;
            const now = Date.now();

            if (!isManual && emp === lastIdentifiedEmployee && (now - lastIdentifiedTime) < 8000) {
                return;
            }

            lastIdentifiedEmployee = emp;
            lastIdentifiedTime = now;

            if (result.already_completed) {
                const msg = result.message || __("Already today IN and OUT log created");
                punchAlert.removeClass("fa-punch-in fa-punch-out")
                          .addClass("fa-punch-warning");
                punchBadge.text("LOGGED");
                punchEmp.text(empName && empName !== emp ? `${empName} (${emp})` : emp);
                punchMeta.text(msg);
                punchAlert.stop(true, true).slideDown(200);

                frappe.show_alert({
                    message: `${empName}: ${msg}`,
                    indicator: "orange"
                }, 5);

                if (resetMatchTimer) clearTimeout(resetMatchTimer);
                resetMatchTimer = setTimeout(() => {
                    punchAlert.slideUp(250);
                }, 5000);
                return;
            }

            const action = result.auto_action;

            if (action === "IN" || action === "OUT") {
                const confirmRes = await frappe.call({
                    method: "face_detection.api.confirm_attendance",
                    args: {
                        confirmation_token: result.confirmation_token,
                        log_type: action
                    }
                });

                if (confirmRes.message && confirmRes.message.ok) {
                    const isIN = action === "IN";
                    punchAlert.removeClass("fa-punch-in fa-punch-out fa-punch-warning")
                              .addClass(isIN ? "fa-punch-in" : "fa-punch-out");
                    punchBadge.text(action);
                    punchEmp.text(empName && empName !== emp ? `${empName} (${emp})` : emp);
                    const nowTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                    punchMeta.text(`Marked ${action} Successfully • ${nowTime}`);
                    punchAlert.stop(true, true).slideDown(200);

                    frappe.show_alert({
                        message: __("Successfully recorded {0} for {1}", [action, empName]),
                        indicator: isIN ? "green" : "red"
                    }, 5);

                    fetchLogs();

                    if (resetMatchTimer) clearTimeout(resetMatchTimer);
                    resetMatchTimer = setTimeout(() => {
                        punchAlert.slideUp(250);
                    }, 5000);
                }
            }
        } catch (e) {
            if (isManual) {
                frappe.show_alert({
                    message: __(e.message || "Failed to identify employee. Ensure face is clearly visible."),
                    indicator: "red"
                }, 4);
            }
        } finally {
            setBusy(false);
            if (isManual) {
                captureBtn.prop("disabled", false).find("span").text("Capture Face");
            }
        }
    }

    captureBtn.on("click", async () => {
        if (busy) return;
        if (!stream) {
            await initCamera();
            if (!stream) return;
        }
        await performIdentification(true);
    });

    stopBtn.on("click", function () {
        stopCamera();
    });

    startBtn.on("click", async function () {
        await initCamera();
    });

    enrollBtn.on("click", async () => {
        if (busy) return;
        const employee = (employeeControl.get_value() || "").trim();
        if (!employee) {
            frappe.show_alert({
                message: __("Please select an employee from the dropdown before enrolling."),
                indicator: "orange"
            }, 4);
            return;
        }
        if (selectedEmployeeIsEnrolled) {
            frappe.show_alert({
                message: __("Face profile is already enrolled for this employee ({0}). No need to enroll again.", [employee]),
                indicator: "orange"
            }, 5);
            return;
        }
        if (!stream) {
            frappe.show_alert({
                message: __("Camera is not active. Please start camera first."),
                indicator: "orange"
            }, 4);
            return;
        }

        try {
            setBusy(true);
            enrollBtn.prop("disabled", true).find("span").text("Enrolling...");
            const image_data = captureDataUrl();
            const r = await frappe.call({
                method: "face_detection.api.enroll_face",
                args: { employee, image_data }
            });

            if (r.message && r.message.already_enrolled) {
                selectedEmployeeIsEnrolled = true;
                const statusEl = page.main.find("#fa-enroll-employee-status");
                statusEl.html(`
                    <div class="fa-enroll-status-alert fa-status-warning">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0; margin-top:2px;">
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="12" y1="8" x2="12" y2="12"></line>
                            <line x1="12" y1="16" x2="12.01" y2="16"></line>
                        </svg>
                        <span>${r.message.message}</span>
                    </div>
                `).show();

                frappe.show_alert({
                    message: __(r.message.message),
                    indicator: "orange"
                }, 5);
                enrollBtn.prop("disabled", true);
                return;
            }

            if (r.message && r.message.ok) {
                selectedEmployeeIsEnrolled = false;
                lastCheckedEmployee = null;
                frappe.show_alert({
                    message: __("Face profile enrolled successfully for {0}", [employee]),
                    indicator: "green"
                }, 5);

                employeeControl.set_value("");
                updateLinkIconsVisibility();
                page.main.find("#fa-enroll-employee-status").hide().empty();
                enrollBtn.prop("disabled", true);
            }
        } catch (e) {
            const msg = e.message || "Enrollment failed. Ensure single face is centered.";
            frappe.show_alert({
                message: __(msg),
                indicator: "red"
            }, 5);
        } finally {
            setBusy(false);
            enrollBtn.prop("disabled", selectedEmployeeIsEnrolled || !stream || !employeeControl.get_value()).find("span").text("Capture & Enroll Face");
        }
    });

    page.main.find("#fa-btn-refresh-logs").on("click", function () {
        fetchLogs();
    });

    loadSettings().then(() => {
        initCamera();
    });

    fetchLogs();
    logRefreshTimer = setInterval(fetchLogs, 8000);

    $(wrapper).on("show", function () {
        window.scrollTo(0, 0);
        $(wrapper).find(".page-head, .page-title, .title-area, .title-text").remove();
        if (!stream) {
            initCamera();
        }
        fetchLogs();
        if (!logRefreshTimer) {
            logRefreshTimer = setInterval(fetchLogs, 8000);
        }
    });

    $(wrapper).on("hide", function () {
        stopAutoScan();
        if (logRefreshTimer) {
            clearInterval(logRefreshTimer);
            logRefreshTimer = null;
        }
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }
    });
};
