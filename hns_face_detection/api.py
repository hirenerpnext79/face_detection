import base64
import binascii
import json
import math
import os
import re
import time
import uuid
import warnings

try:
    import cv2
except ImportError as _cv2_err:
    if "libGL" in str(_cv2_err) or "cannot open shared object file" in str(_cv2_err):
        import subprocess
        import sys
        try:
            subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "opencv-python"], check=False)
            subprocess.run([sys.executable, "-m", "pip", "install", "opencv-python-headless"], check=False)
            import cv2
        except Exception:
            raise _cv2_err
    else:
        raise
import frappe
from frappe import _
import numpy as np
from frappe.utils import format_time, now_datetime, today

warnings.filterwarnings("ignore", category=FutureWarning, message=r".*estimate.*")
warnings.filterwarnings("ignore", category=FutureWarning, module=r".*insightface.*")

MATCH_THRESHOLD = 0.45
MAX_IMAGE_BYTES = 5 * 1024 * 1024
CONFIRMATION_TTL_SECONDS = 180
ALLOWED_ENROLLMENT_ROLES = {"System Manager", "HR Manager"}

_face_app = None
_cached_matrix = None
_cached_employees = None
_cached_profiles_time = 0
_cached_profiles_version = None


def _require_enrollment_role():
    if frappe.session.user == "Guest":
        return
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not ALLOWED_ENROLLMENT_ROLES.intersection(user_roles):
        frappe.throw("Only HR Manager or System Manager can enroll face profiles.", frappe.PermissionError)


def get_employee_details(employee_or_user):
    try:
        if not employee_or_user:
            return None
        emp_id = None
        if frappe.db.exists("Employee", employee_or_user):
            emp_id = employee_or_user
        else:
            emp_id = frappe.db.get_value("Employee", {"user_id": employee_or_user}, "name")
        if not emp_id or not frappe.db.exists("Employee", emp_id):
            return None
        emp = frappe.get_doc("Employee", emp_id)
        return {
            "name": emp.name,
            "employee": emp.name,
            "employee_name": emp.employee_name or emp.name,
            "status": emp.status or "Active",
            "designation": emp.designation or "",
            "department": emp.department or "",
            "company": emp.company or "",
            "user_id": emp.user_id or "",
            "doc": emp,
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: get_employee_details error")
        return None


@frappe.whitelist(allow_guest=True)
def get_employee_info(employee=None):
    try:
        target = employee or frappe.session.user
        details = get_employee_details(target)
        if details:
            details_copy = dict(details)
            details_copy.pop("doc", None)
            return details_copy
        return None
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: get_employee_info failed")
        return None


def _get_face_app():
    global _face_app
    if _face_app is None:
        try:
            from insightface.app import FaceAnalysis
            _face_app = FaceAnalysis(
                name="buffalo_l",
                providers=["CPUExecutionProvider"],
                allowed_modules=["detection", "recognition"],
            )
            _face_app.prepare(ctx_id=-1, det_size=(480, 480))
        except Exception:
            frappe.log_error(frappe.get_traceback(), "HNS Face Detection: model initialization failed")
            frappe.throw("Face model could not be initialized. Verify InsightFace installation and server logs.")
    return _face_app


@frappe.whitelist(allow_guest=True)
def warmup_model():
    try:
        app = _get_face_app()
        dummy = np.zeros((240, 240, 3), dtype=np.uint8)
        app.get(dummy)
        return {"ok": True, "message": "Face model ready."}
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: warmup failed")
        return {"ok": False, "message": "Model warmup failed."}


def _decode_image(image_data):
    if not isinstance(image_data, str) or not image_data:
        frappe.throw("Image data is required.")

    if image_data.startswith("data:"):
        match = re.match(r"^data:image/(?:jpeg|jpg|png|webp);base64,(.*)$", image_data, re.I | re.S)
        if not match:
            frappe.throw("Unsupported image format. Send a JPEG, PNG, or WebP data URL.")
        image_data = match.group(1)

    if len(image_data) > ((MAX_IMAGE_BYTES * 4 // 3) + 16):
        frappe.throw("Image is too large. Maximum size is 5 MB.")

    try:
        raw = base64.b64decode(image_data, validate=True)
    except (binascii.Error, ValueError):
        frappe.throw("Invalid base64 image data.")

    if not raw or len(raw) > MAX_IMAGE_BYTES:
        frappe.throw("Image is empty or exceeds the 5 MB limit.")

    arr = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if image is None:
        try:
            from io import BytesIO
            from PIL import Image, ImageOps
            pil_image = Image.open(BytesIO(raw))
            pil_image = ImageOps.exif_transpose(pil_image)
            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")
            image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        except Exception:
            pass

    if image is None:
        frappe.throw("Could not decode the image.")

    height, width = image.shape[:2]
    if width < 120 or height < 120:
        frappe.throw("Image resolution is too low. Ensure face is clearly visible.")

    max_dim = max(height, width)
    if max_dim > 480:
        scale = 480.0 / max_dim
        new_w = int(width * scale)
        new_h = int(height * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)

    return image


def _extract_embedding_from_array(image):
    faces = _get_face_app().get(image)
    if not faces:
        frappe.throw("No face detected. Center one face clearly in the camera and try again.")
    if len(faces) != 1:
        frappe.throw("More than one face detected. Ensure only one person is in the frame.")

    face = faces[0]
    embedding = np.asarray(face.normed_embedding, dtype=np.float32)
    norm = float(np.linalg.norm(embedding))
    if not math.isfinite(norm) or norm <= 0:
        frappe.throw("Could not create a valid face embedding.")

    return embedding / norm


def extract_embedding_from_file_or_data(image_input):
    if not image_input or not isinstance(image_input, str):
        frappe.throw("Valid image input is required.")
    image = _decode_image(image_input)
    return _extract_embedding_from_array(image)


def _invalidate_profiles_cache(doc=None, method=None):
    global _cached_matrix, _cached_employees, _cached_profiles_time, _cached_profiles_version
    _cached_matrix = None
    _cached_employees = None
    _cached_profiles_time = 0
    _cached_profiles_version = None
    try:
        new_version = frappe.generate_hash(length=12)
        frappe.cache().set_value("hns_face_profiles_version", new_version)
    except Exception:
        pass


def _load_active_profiles():
    global _cached_matrix, _cached_employees, _cached_profiles_time, _cached_profiles_version
    now = time.time()
    try:
        current_version = frappe.cache().get_value("hns_face_profiles_version")
    except Exception:
        current_version = None

    if (
        _cached_matrix is not None
        and _cached_profiles_version == current_version
        and (now - _cached_profiles_time) < 30
    ):
        return _cached_matrix, _cached_employees

    profiles = frappe.get_all(
        "Hns Employee Face Profile",
        filters={"active": 1, "is_enrolled": 1},
        fields=["employee", "embedding"],
        limit_page_length=10000,
    )

    valid_embeddings = []
    valid_employees = []
    for profile in profiles:
        try:
            if not profile.embedding:
                continue
            arr = np.asarray(json.loads(profile.embedding), dtype=np.float32)
            norm = float(np.linalg.norm(arr))
            if norm > 0:
                valid_embeddings.append(arr / norm)
                valid_employees.append(profile.employee)
        except Exception:
            continue

    if valid_embeddings:
        _cached_matrix = np.vstack(valid_embeddings)
        _cached_employees = valid_employees
    else:
        _cached_matrix = np.empty((0, 512), dtype=np.float32)
        _cached_employees = []

    _cached_profiles_time = now
    _cached_profiles_version = current_version
    return _cached_matrix, _cached_employees


def _find_best_match(probe_embedding):
    try:
        matrix, employees = _load_active_profiles()
        if matrix.shape[0] == 0:
            return None

        probe_norm = float(np.linalg.norm(probe_embedding))
        if probe_norm <= 0:
            return None
        normed_probe = probe_embedding / probe_norm

        scores = np.dot(matrix, normed_probe)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])

        if best_score >= MATCH_THRESHOLD:
            matched_employee = employees[best_idx]
            is_active_in_db = frappe.db.exists(
                "Hns Employee Face Profile",
                {"employee": matched_employee, "active": 1, "is_enrolled": 1},
            )
            if not is_active_in_db:
                _invalidate_profiles_cache()
                return None
            return {"employee": matched_employee, "similarity": best_score}
        return None
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: _find_best_match error")
        return None


def get_employee_today_logs(employee):
    try:
        today_date = today()
        logs = frappe.db.get_all(
            "Hns Face Detection Log",
            filters={
                "employee": employee,
                "time": [">=", f"{today_date} 00:00:00"]
            },
            fields=["name", "log_type", "time"],
            order_by="time asc, creation asc",
        )

        if not logs and frappe.db.exists("DocType", "Employee Checkin"):
            logs = frappe.db.get_all(
                "Employee Checkin",
                filters={
                    "employee": employee,
                    "time": [">=", f"{today_date} 00:00:00"]
                },
                fields=["name", "log_type", "time"],
                order_by="time asc, creation asc",
            )
        return logs or []
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: get_employee_today_logs error")
        return []


def check_today_attendance_status(employee):
    try:
        logs = get_employee_today_logs(employee)
        last_log_type = logs[-1].log_type if logs else None
        next_action = "OUT" if last_log_type == "IN" else "IN"
        return {
            "completed": False,
            "next_action": next_action,
            "message": None,
            "logs_count": len(logs),
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: check_today_attendance_status error")
        return {
            "completed": False,
            "next_action": "IN",
            "message": None,
            "logs_count": 0,
        }


def _parse_activity_log(log_input):
    if not log_input:
        return {}
    if isinstance(log_input, dict):
        return dict(log_input)
    try:
        return frappe.parse_json(log_input) or {}
    except Exception:
        return {"raw": str(log_input)}


def record_attendance_log(employee, log_type, similarity=None, punch_category=None, employee_name=None, notes=None, longitude=None, latitude=None, log=None, designation=None, department=None):
    try:
        checkin_time = now_datetime()
        if not employee_name:
            emp_info = get_employee_details(employee)
            employee_name = emp_info["employee_name"] if emp_info else employee
        if not punch_category:
            gate_settings = frappe.get_single("Hns Gate Face Punching")
            punch_category = gate_settings.punch_category if gate_settings and gate_settings.punch_category else "Attendance"

        activity_dict = _parse_activity_log(log)
        loc = activity_dict.get("location") if isinstance(activity_dict.get("location"), dict) else {}
        eff_latitude = loc.get("latitude") if loc.get("latitude") is not None else latitude
        eff_longitude = loc.get("longitude") if loc.get("longitude") is not None else longitude

        log_data = {
            "doctype": "Hns Face Detection Log",
            "employee": employee,
            "employee_name": employee_name,
            "department": department,
            "designation": designation,
            "log_type": log_type,
            "action": "Confirm",
            "punch_category": punch_category,
            "time": checkin_time,
            "similarity_score": similarity,
            "notes": notes or "",
            "log": json.dumps(activity_dict, indent=2),
        }
        if eff_longitude is not None and str(eff_longitude).strip():
            log_data["longitude"] = str(eff_longitude)
        if eff_latitude is not None and str(eff_latitude).strip():
            log_data["latitude"] = str(eff_latitude)

        log_doc = frappe.get_doc(log_data)
        log_doc.insert(ignore_permissions=True)

        if frappe.db.exists("DocType", "Employee Checkin"):
            employee_checkin = frappe.get_doc({
                "doctype": "Employee Checkin",
                "employee": employee,
                "time": checkin_time,
                "log_type": log_type,
                "device_id": "Face Detection",
            })
            employee_checkin.insert(ignore_permissions=True)

        frappe.db.commit()
        return log_doc
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: failed to record attendance")
        raise


@frappe.whitelist(allow_guest=True)
def enroll_face(employee, image_data, re_enroll=0):
    try:
        _require_enrollment_role()
        emp_info = get_employee_details(employee)
        if not emp_info:
            frappe.throw("A valid Employee ID is required.")

        employee_doc = emp_info["doc"]
        if emp_info["status"] != "Active":
            frappe.throw("Only active employees can be enrolled.")

        existing_profile = frappe.db.get_value(
            "Hns Employee Face Profile",
            {"employee": employee},
            ["name", "is_enrolled", "embedding"],
            as_dict=True,
        )

        if existing_profile and existing_profile.is_enrolled and existing_profile.embedding and not frappe.utils.cint(re_enroll):
            return {
                "ok": False,
                "status": "warning",
                "already_enrolled": True,
                "employee": employee,
                "employee_name": employee_doc.employee_name or employee,
                "message": f"Face profile is already enrolled for this employee ({employee}).",
            }

        embedding = extract_embedding_from_file_or_data(image_data)
        profile_name = existing_profile.name if existing_profile else None

        values = {
            "employee": employee,
            "employee_name": employee_doc.employee_name or employee,
            "active": 1,
            "is_enrolled": 1,
            "embedding": json.dumps(embedding.tolist(), separators=(",", ":")),
            "enrolled_by": frappe.session.user if frappe.session.user != "Guest" else "Kiosk Enrollment",
            "enrolled_on": now_datetime(),
        }

        if profile_name:
            profile = frappe.get_doc("Hns Employee Face Profile", profile_name)
            profile.update(values)
            profile.save(ignore_permissions=True)
        else:
            profile = frappe.get_doc({"doctype": "Hns Employee Face Profile", **values})
            profile.insert(ignore_permissions=True)

        _invalidate_profiles_cache()
        frappe.db.commit()
        return {
            "ok": True,
            "status": "success",
            "employee": employee,
            "employee_name": employee_doc.employee_name or employee,
            "message": f"Face profile enrolled successfully for {employee}."
        }
    except frappe.ValidationError as e:
        return {
            "ok": False,
            "status": "error",
            "message": _get_clean_error_message(e),
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: enroll_face failed")
        return {
            "ok": False,
            "status": "error",
            "message": "Enrollment failed. Please try again.",
        }


@frappe.whitelist(allow_guest=True)
def identify_employee(image_data):
    try:
        probe = extract_embedding_from_file_or_data(image_data)
        match = _find_best_match(probe)

        if not match:
            return {
                "ok": False,
                "matched": False,
                "message": "No enrolled employee matched confidently. Please adjust lighting or verify enrollment.",
            }

        matched_employee = match["employee"]
        is_active_profile = frappe.db.exists(
            "Hns Employee Face Profile",
            {"employee": matched_employee, "active": 1, "is_enrolled": 1},
        )
        if not is_active_profile:
            _invalidate_profiles_cache()
            return {
                "ok": False,
                "matched": False,
                "message": "No enrolled employee matched confidently. Please adjust lighting or verify enrollment.",
            }

        emp_info = get_employee_details(matched_employee)
        if not emp_info or emp_info["status"] != "Active":
            return {
                "ok": False,
                "matched": False,
                "message": "The matched employee is not active.",
            }

        status = check_today_attendance_status(matched_employee)
        token = uuid.uuid4().hex
        cache_key = "hns_face_detection:confirmation:" + token
        frappe.cache().set_value(
            cache_key,
            {"employee": matched_employee, "user": frappe.session.user, "similarity": match["similarity"]},
            expires_in_sec=CONFIRMATION_TTL_SECONDS,
        )

        auto_action = status.get("next_action") or "IN"
        return {
            "ok": True,
            "matched": True,
            "already_completed": False,
            "employee": matched_employee,
            "employee_name": emp_info["employee_name"],
            "department": emp_info["department"],
            "designation": emp_info["designation"],
            "similarity": round(match["similarity"], 4),
            "confirmation_token": token,
            "expires_in_seconds": CONFIRMATION_TTL_SECONDS,
            "auto_action": auto_action,
        }
    except frappe.ValidationError as e:
        return {
            "ok": False,
            "matched": False,
            "message": _get_clean_error_message(e),
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: identify_employee failed")
        return {
            "ok": False,
            "matched": False,
            "message": "Face identification failed. Please try again.",
        }


@frappe.whitelist(allow_guest=True)
def confirm_attendance(confirmation_token=None, log_type="IN", punch_category=None, employee=None, employee_name=None, designation=None, department=None, notes=None, longitude=None, latitude=None, log=None, activity_log=None):
    try:
        eff_log = log or activity_log
        final_log_type = (log_type or "IN").upper()
        if final_log_type not in ("IN", "OUT"):
            final_log_type = "IN"

        similarity = None
        if confirmation_token and isinstance(confirmation_token, str) and re.fullmatch(r"[a-f0-9]{32}", confirmation_token):
            cache_key = "hns_face_detection:confirmation:" + confirmation_token
            payload = frappe.cache().get_value(cache_key)
            if payload:
                frappe.cache().delete_value(cache_key)
                if not employee:
                    employee = payload.get("employee")
                similarity = payload.get("similarity")

        emp_info = get_employee_details(employee)
        if not emp_info:
            frappe.throw("Valid employee record is required.")

        employee_doc = emp_info["doc"]
        if emp_info["status"] != "Active":
            frappe.throw("Only active employees can check in/out.")

        has_emp_changes = False
        if employee_name and employee_name.strip() and employee_doc.employee_name != employee_name.strip():
            employee_doc.employee_name = employee_name.strip()
            has_emp_changes = True
        if designation and frappe.db.exists("Designation", designation) and employee_doc.designation != designation:
            employee_doc.designation = designation
            has_emp_changes = True
        if department and frappe.db.exists("Department", department) and employee_doc.department != department:
            employee_doc.department = department
            has_emp_changes = True

        if has_emp_changes:
            employee_doc.save(ignore_permissions=True)

        log_record = record_attendance_log(
            employee=employee,
            log_type=final_log_type,
            similarity=similarity,
            punch_category=punch_category,
            employee_name=employee_name or employee_doc.employee_name,
            notes=notes,
            longitude=longitude,
            latitude=latitude,
            log=eff_log,
            designation=designation or employee_doc.designation,
            department=department or employee_doc.department,
        )

        return {
            "ok": True,
            "status": "success",
            "name": log_record.name,
            "employee": employee,
            "employee_name": employee_name or employee_doc.employee_name or employee,
            "log_type": final_log_type,
            "punch_category": punch_category or log_record.punch_category,
            "time": str(log_record.time),
            "similarity": round(float(similarity or 0.0), 4) if similarity else None,
            "message": f"Successfully marked {final_log_type} for {employee_name or employee_doc.employee_name or employee}",
        }
    except frappe.ValidationError as e:
        return {
            "ok": False,
            "status": "error",
            "message": _get_clean_error_message(e),
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: confirm_attendance failed")
        return {
            "ok": False,
            "status": "error",
            "message": "Failed to record attendance. Please try again.",
        }


@frappe.whitelist(allow_guest=True)
def record_rejected_punch(employee=None, employee_name=None, reason="", log_type="IN", punch_category="Attendance", longitude=None, latitude=None, log=None, activity_log=None, designation=None, department=None):
    try:
        eff_log = log or activity_log
        checkin_time = now_datetime()
        final_log_type = (log_type or "IN").upper()
        if final_log_type not in ("IN", "OUT"):
            final_log_type = "IN"

        emp_info = None
        if employee:
            emp_info = get_employee_details(employee)
        if not employee_name:
            employee_name = emp_info["employee_name"] if emp_info else "Unidentified Person"

        activity_dict = _parse_activity_log(eff_log)
        loc = activity_dict.get("location") if isinstance(activity_dict.get("location"), dict) else {}
        eff_latitude = loc.get("latitude") if loc.get("latitude") is not None else latitude
        eff_longitude = loc.get("longitude") if loc.get("longitude") is not None else longitude

        log_data = {
            "doctype": "Hns Face Detection Log",
            "employee": employee if (employee and frappe.db.exists("Employee", employee)) else None,
            "employee_name": employee_name,
            "department": department or (emp_info.get("department") if emp_info else None),
            "designation": designation or (emp_info.get("designation") if emp_info else None),
            "log_type": final_log_type,
            "action": "Reject",
            "punch_category": punch_category or "Attendance",
            "time": checkin_time,
            "notes": reason or "",
            "log": json.dumps(activity_dict, indent=2),
        }
        if eff_longitude is not None and str(eff_longitude).strip():
            log_data["longitude"] = str(eff_longitude)
        if eff_latitude is not None and str(eff_latitude).strip():
            log_data["latitude"] = str(eff_latitude)

        log_doc = frappe.get_doc(log_data)
        log_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return {
            "ok": True,
            "status": "success",
            "name": log_doc.name,
            "message": "Rejection logged successfully."
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: record_rejected_punch failed")
        return {
            "ok": False,
            "status": "error",
            "message": "Failed to record rejection log."
        }


@frappe.whitelist(allow_guest=True)
def get_master_options():
    try:
        designations = frappe.get_all("Designation", pluck="name", order_by="name asc")
        departments = frappe.get_all("Department", pluck="name", order_by="name asc")
        return {
            "designations": designations,
            "departments": departments,
        }
    except Exception:
        return {"designations": [], "departments": []}


@frappe.whitelist(allow_guest=True)
def get_today_attendance(employee=None):
    try:
        if frappe.session.user != "Guest" and not employee and frappe.session.user != "Administrator":
            emp_info = get_employee_details(frappe.session.user)
            if emp_info:
                employee = emp_info["name"]

        today_start = today() + " 00:00:00"
        filters = {"time": [">=", today_start]}
        if employee:
            filters["employee"] = employee

        logs = frappe.get_all(
            "Hns Face Detection Log",
            filters=filters,
            fields=["name", "employee", "employee_name", "log_type", "time", "similarity_score"],
            order_by="time asc",
            limit_page_length=50,
        )

        status = check_today_attendance_status(employee) if employee else {}
        return {
            "employee": employee,
            "logs": logs,
            "next_action": status.get("next_action") if employee else ("OUT" if logs and logs[-1].log_type == "IN" else "IN"),
            "already_completed": False,
            "message": None,
            "count": len(logs)
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: get_today_attendance failed")
        raise


@frappe.whitelist(allow_guest=True)
def get_face_profile_status(employee=None):
    try:
        if not employee and frappe.session.user not in ("Administrator", "Guest"):
            emp_info = get_employee_details(frappe.session.user)
            if emp_info:
                employee = emp_info["name"]

        if not employee:
            frappe.throw("Employee is required.")

        profile = frappe.db.get_value(
            "Hns Employee Face Profile",
            {"employee": employee},
            ["name", "employee", "employee_name", "active", "is_enrolled", "enrolled_on", "embedding"],
            as_dict=True,
        )

        if not profile:
            return {"enrolled": False, "employee": employee}

        enrolled_on_val = profile.enrolled_on
        if enrolled_on_val:
            try:
                enrolled_on_val = frappe.utils.format_datetime(enrolled_on_val, "dd-MM-yyyy hh:mm a")
            except Exception:
                enrolled_on_val = str(enrolled_on_val).split(".")[0]

        return {
            "enrolled": bool(profile.is_enrolled and profile.active and profile.embedding),
            "employee": profile.employee,
            "employee_name": profile.employee_name,
            "enrolled_on": enrolled_on_val,
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: get_face_profile_status failed")
        raise


@frappe.whitelist(allow_guest=True)
def get_kiosk_settings():
    try:
        settings = frappe.get_single("Hns Gate Face Punching")
        return {
            "auto_detect": frappe.utils.cint(settings.auto_detect),
            "mode": settings.mode or "",
            "punch_category": settings.punch_category or ""
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: get_kiosk_settings failed")
        return {
            "auto_detect": 0,
            "mode": "",
            "punch_category": ""
        }


@frappe.whitelist(allow_guest=True)
def update_kiosk_settings(auto_detect=None, mode=None, punch_category=None):
    try:
        settings = frappe.get_single("Hns Gate Face Punching")
        if auto_detect is not None:
            settings.auto_detect = frappe.utils.cint(auto_detect)
        if mode is not None:
            settings.mode = mode
        if punch_category is not None:
            settings.punch_category = punch_category
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        return {
            "ok": True,
            "auto_detect": frappe.utils.cint(settings.auto_detect),
            "mode": settings.mode or "",
            "punch_category": settings.punch_category or ""
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: update_kiosk_settings failed")
        raise


@frappe.whitelist(allow_guest=True)
def get_hns_face_detection_logs(log_date=None, limit=50):
    return _get_face_logs(log_date, limit)


@frappe.whitelist(allow_guest=True)
def get_face_detection_logs(log_date=None, limit=50):
    return _get_face_logs(log_date, limit)


def _get_face_logs(log_date=None, limit=50):
    try:
        target_date = log_date or today()
        start_datetime = f"{target_date} 00:00:00"
        end_datetime = f"{target_date} 23:59:59"

        logs = frappe.db.get_all(
            "Hns Face Detection Log",
            filters={
                "time": ["between", [start_datetime, end_datetime]]
            },
            fields=["name", "employee", "employee_name", "department", "designation", "time", "log_type", "punch_category", "action", "notes", "log"],
            order_by="time desc, creation desc",
            limit_page_length=frappe.utils.cint(limit) or 100,
        )

        employee_names = {}
        formatted_logs = []
        for row in logs:
            emp = row.employee
            if not row.employee_name:
                if emp not in employee_names:
                    emp_info = get_employee_details(emp)
                    employee_names[emp] = emp_info["employee_name"] if emp_info else emp
                emp_name = employee_names[emp]
            else:
                emp_name = row.employee_name

            time_str = ""
            if row.time:
                try:
                    time_str = frappe.utils.format_time(row.time, "hh:mm:ss a")
                except Exception:
                    time_str = frappe.utils.format_time(row.time)
            category = row.punch_category or "Attendance"
            is_rejected = (row.action == "Reject")
            reject_reason = ""
            if row.notes:
                try:
                    notes_obj = json.loads(row.notes)
                    if isinstance(notes_obj, dict):
                        reject_reason = notes_obj.get("reject_reason") or notes_obj.get("reason", "")
                    elif isinstance(notes_obj, str):
                        reject_reason = notes_obj
                except Exception:
                    reject_reason = str(row.notes)

            formatted_logs.append({
                "name": row.name,
                "employee": emp,
                "employee_name": emp_name,
                "department": row.department or "",
                "designation": row.designation or "",
                "time": time_str,
                "log_type": row.log_type,
                "action": row.action or ("Reject" if is_rejected else "Confirm"),
                "category": category,
                "is_rejected": is_rejected,
                "reject_reason": reject_reason,
            })

        return {
            "date": target_date,
            "formatted_date": frappe.utils.formatdate(target_date),
            "logs": formatted_logs,
            "count": len(formatted_logs)
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: get_face_detection_logs failed")
        return {
            "date": log_date or today(),
            "formatted_date": frappe.utils.formatdate(log_date or today()),
            "logs": [],
            "count": 0
        }


def _get_clean_error_message(e):
    error_msg = str(e)
    if "TimestampMismatchError" in repr(e) or "has been modified" in error_msg:
        match = re.search(r"Error: Document has been modified.*?Please refresh to get the latest document\.", error_msg)
        if match:
            return match.group(0)
        return "Document has been modified after you opened it. Please refresh to get the latest document."
    elif "PermissionError" in repr(e) or "Does not have permission" in error_msg:
        return "Permission Denied: You do not have access to this document or printer."
    return error_msg
