import base64
import binascii
import json
import math
import os
import re
import uuid
import warnings

import cv2
import frappe
from frappe import _
import numpy as np
from frappe.utils import format_time, now_datetime, to_timedelta, today

warnings.filterwarnings("ignore", category=FutureWarning, message=r".*estimate.*")
warnings.filterwarnings("ignore", category=FutureWarning, module=r".*insightface.*")

MATCH_THRESHOLD = 0.45
MAX_IMAGE_BYTES = 5 * 1024 * 1024
CONFIRMATION_TTL_SECONDS = 180
ALLOWED_ENROLLMENT_ROLES = {"System Manager", "HR Manager"}

_face_app = None


def _require_login():
    if frappe.session.user == "Guest":
        frappe.throw("Login is required.", frappe.PermissionError)


def _require_enrollment_role():
    if frappe.session.user == "Guest":
        return
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not ALLOWED_ENROLLMENT_ROLES.intersection(user_roles):
        frappe.throw("Only HR Manager or System Manager can enroll face profiles.", frappe.PermissionError)


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
            _face_app.prepare(ctx_id=-1, det_size=(640, 640))
        except Exception:
            frappe.log_error(frappe.get_traceback(), "HNS Face Detection: model initialization failed")
            frappe.throw("Face model could not be initialized. Verify InsightFace installation and server logs.")
    return _face_app


@frappe.whitelist(allow_guest=True)
def warmup_model():
    try:
        _get_face_app()
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

    try:
        from io import BytesIO
        from PIL import Image, ImageOps
        pil_image = Image.open(BytesIO(raw))
        pil_image = ImageOps.exif_transpose(pil_image)
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")
        image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    except Exception:
        arr = np.frombuffer(raw, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if image is None:
        frappe.throw("Could not decode the image.")

    height, width = image.shape[:2]
    if width < 160 or height < 160:
        frappe.throw("Image resolution is too low. Ensure face is clearly visible.")

    max_dim = max(height, width)
    if max_dim > 640:
        scale = 640.0 / max_dim
        new_w = int(width * scale)
        new_h = int(height * scale)
        image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)

    return image


def _extract_embedding_from_array(image):
    faces = _get_face_app().get(image)
    if not faces:
        for angle in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
            rotated = cv2.rotate(image, angle)
            candidate_faces = _get_face_app().get(rotated)
            if candidate_faces:
                faces = candidate_faces
                break

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


def _cosine_similarity(left, right):
    left = np.asarray(left, dtype=np.float32)
    right = np.asarray(right, dtype=np.float32)
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 0:
        return -1.0
    return float(np.dot(left, right) / denom)


_cached_profiles = None
_cached_profiles_time = 0


def _get_active_profile_embeddings():
    global _cached_profiles, _cached_profiles_time
    import time
    now = time.time()
    if _cached_profiles is not None and (now - _cached_profiles_time) < 60:
        return _cached_profiles

    profiles = frappe.get_all(
        "Hns Employee Face Profile",
        filters={"active": 1},
        fields=["name", "employee", "embedding"],
        limit_page_length=10000,
    )
    loaded = []
    for profile in profiles:
        try:
            if not profile.embedding:
                continue
            arr = np.asarray(json.loads(profile.embedding), dtype=np.float32)
            norm = float(np.linalg.norm(arr))
            if norm > 0:
                loaded.append({
                    "name": profile.name,
                    "employee": profile.employee,
                    "embedding": arr / norm,
                })
        except Exception:
            continue
    _cached_profiles = loaded
    _cached_profiles_time = now
    return _cached_profiles


def _find_best_match(probe_embedding):
    try:
        profiles = _get_active_profile_embeddings()
        if not profiles:
            return None

        probe_norm = float(np.linalg.norm(probe_embedding))
        if probe_norm <= 0:
            return None
        normed_probe = probe_embedding / probe_norm

        best_match = None
        best_score = -1.0

        for profile in profiles:
            score = float(np.dot(normed_probe, profile["embedding"]))
            if score > best_score:
                best_score = score
                best_match = profile

        if best_match and best_score >= MATCH_THRESHOLD:
            return {"employee": best_match["employee"], "similarity": best_score}
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


def is_out_allowed(gate_settings):
    try:
        if not gate_settings or not gate_settings.out_time:
            return True, None

        out_td = to_timedelta(gate_settings.out_time)
        if not out_td:
            return True, None

        now_td = to_timedelta(now_datetime().time())
        if now_td < out_td:
            try:
                time_display = format_time(str(out_td), "hh:mm a")
            except Exception:
                time_display = str(out_td)
            return False, time_display
        return True, None
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: is_out_allowed error")
        return True, None


def check_today_attendance_status(employee):
    try:
        logs = get_employee_today_logs(employee)
        has_in = any(l.log_type == "IN" for l in logs)
        has_out = any(l.log_type == "OUT" for l in logs)

        gate_settings = frappe.get_single("Hns Gate Face Punching")
        is_auto_detect = bool(gate_settings and gate_settings.auto_detect)
        kiosk_mode = (gate_settings.mode or "").strip().upper() if (gate_settings and not is_auto_detect) else ""
        out_allowed, allowed_time = is_out_allowed(gate_settings)

        if has_in and has_out:
            return {
                "completed": True,
                "next_action": None,
                "message": _("Already today IN and OUT log created"),
                "logs_count": len(logs),
            }

        if kiosk_mode == "IN":
            if has_in:
                msg = (
                    _("Already today IN log created. OUT entry is allowed after {0}").format(allowed_time)
                    if not out_allowed
                    else _("Already today IN log created")
                )
                return {
                    "completed": True,
                    "next_action": None,
                    "out_time_blocked": not out_allowed,
                    "allowed_time": allowed_time if not out_allowed else None,
                    "message": msg,
                    "logs_count": len(logs),
                }
            return {
                "completed": False,
                "next_action": "IN",
                "message": None,
                "logs_count": len(logs),
            }

        if kiosk_mode == "OUT":
            if has_out:
                return {
                    "completed": True,
                    "next_action": None,
                    "message": _("Already today OUT log created"),
                    "logs_count": len(logs),
                }
            if not out_allowed:
                msg = (
                    _("Already today IN log created. OUT entry is allowed after {0}").format(allowed_time)
                    if has_in
                    else _("OUT entry is allowed after {0}").format(allowed_time)
                )
                return {
                    "completed": True,
                    "next_action": None,
                    "out_time_blocked": True,
                    "allowed_time": allowed_time,
                    "message": msg,
                    "logs_count": len(logs),
                }
            return {
                "completed": False,
                "next_action": "OUT",
                "message": None,
                "logs_count": len(logs),
            }

        if has_in:
            if not out_allowed:
                return {
                    "completed": True,
                    "next_action": None,
                    "out_time_blocked": True,
                    "allowed_time": allowed_time,
                    "message": _("Already today IN log created. OUT entry is allowed after {0}").format(allowed_time),
                    "logs_count": len(logs),
                }
            return {
                "completed": False,
                "next_action": "OUT",
                "message": None,
                "logs_count": len(logs),
            }

        return {
            "completed": False,
            "next_action": "IN",
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


def get_auto_log_type(employee):
    try:
        status = check_today_attendance_status(employee)
        return status.get("next_action")
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: auto log type error")
        return "IN"


def record_attendance_log(employee, log_type, similarity=None):
    try:
        checkin_time = now_datetime()
        employee_name = frappe.db.get_value("Employee", employee, "employee_name") or employee
        gate_settings = frappe.get_single("Hns Gate Face Punching")
        punch_category = gate_settings.punch_category if gate_settings and gate_settings.punch_category else "Attendance"

        log_doc = frappe.get_doc({
            "doctype": "Hns Face Detection Log",
            "employee": employee,
            "employee_name": employee_name,
            "log_type": log_type,
            "punch_category": punch_category,
            "time": checkin_time,
            "similarity_score": similarity,
        })
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
        if not employee or not frappe.db.exists("Employee", employee):
            frappe.throw("A valid Employee ID is required.")

        employee_doc = frappe.get_doc("Employee", employee)
        if employee_doc.status and employee_doc.status != "Active":
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

        global _cached_profiles
        _cached_profiles = None
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
        employee_doc = frappe.get_doc("Employee", matched_employee)
        if employee_doc.status and employee_doc.status != "Active":
            return {
                "ok": False,
                "matched": False,
                "message": "The matched employee is not active.",
            }

        status = check_today_attendance_status(matched_employee)
        if status.get("completed"):
            return {
                "ok": False,
                "matched": True,
                "already_completed": True,
                "employee": matched_employee,
                "employee_name": employee_doc.employee_name or matched_employee,
                "department": employee_doc.department or "",
                "designation": employee_doc.designation or "",
                "similarity": round(match["similarity"], 4),
                "out_time_blocked": status.get("out_time_blocked", False),
                "allowed_time": status.get("allowed_time"),
                "message": status.get("message") or _("Already today IN and OUT log created"),
                "auto_action": None,
            }

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
            "employee_name": employee_doc.employee_name or matched_employee,
            "department": employee_doc.department or "",
            "designation": employee_doc.designation or "",
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
def confirm_attendance(confirmation_token, log_type):
    try:
        final_log_type = (log_type or "").upper()
        if final_log_type not in ("IN", "OUT"):
            frappe.throw("log_type must be IN or OUT.")

        if not isinstance(confirmation_token, str) or not re.fullmatch(r"[a-f0-9]{32}", confirmation_token):
            frappe.throw("Invalid confirmation token. Identify the employee again.")

        cache_key = "hns_face_detection:confirmation:" + confirmation_token
        payload = frappe.cache().get_value(cache_key)
        if not payload:
            frappe.throw("Confirmation expired or already used. Identify the employee again.")

        token_user = payload.get("user")
        if token_user != frappe.session.user and token_user != "Guest" and frappe.session.user != "Guest":
            frappe.throw("This confirmation belongs to another user.", frappe.PermissionError)

        frappe.cache().delete_value(cache_key)
        employee = payload.get("employee")
        if not employee or not frappe.db.exists("Employee", employee):
            frappe.throw("Employee record no longer exists.")

        employee_doc = frappe.get_doc("Employee", employee)
        if employee_doc.status and employee_doc.status != "Active":
            frappe.throw("Only active employees can check in/out.")

        status = check_today_attendance_status(employee)
        if status.get("completed"):
            return {
                "ok": False,
                "status": "warning",
                "already_completed": True,
                "message": status.get("message") or _("Already today IN and OUT log created"),
                "employee": employee,
                "employee_name": employee_doc.employee_name or employee,
            }

        if final_log_type == "OUT":
            gate_settings = frappe.get_single("Hns Gate Face Punching")
            out_allowed, allowed_time = is_out_allowed(gate_settings)
            if not out_allowed:
                return {
                    "ok": False,
                    "status": "warning",
                    "already_completed": True,
                    "message": _("Already today IN log created. OUT entry is allowed after {0}").format(allowed_time),
                    "employee": employee,
                    "employee_name": employee_doc.employee_name or employee,
                }

        log_record = record_attendance_log(
            employee=employee,
            log_type=final_log_type,
            similarity=payload.get("similarity"),
        )

        return {
            "ok": True,
            "status": "success",
            "name": log_record.name,
            "employee": employee,
            "employee_name": employee_doc.employee_name or employee,
            "log_type": final_log_type,
            "time": str(log_record.time),
            "similarity": round(float(payload.get("similarity") or 0.0), 4),
            "message": f"Successfully marked {final_log_type} for {employee_doc.employee_name or employee}",
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
def get_today_attendance(employee=None):
    try:
        if frappe.session.user != "Guest" and not employee and frappe.session.user != "Administrator":
            employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")

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
            "already_completed": status.get("completed", False) if employee else False,
            "message": status.get("message") if employee else None,
            "count": len(logs)
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "HNS Face Detection: get_today_attendance failed")
        raise


@frappe.whitelist()
def get_face_profile_status(employee=None):
    try:
        _require_login()
        if not employee and frappe.session.user != "Administrator":
            employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")

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

        return {
            "enrolled": bool(profile.is_enrolled and profile.active and profile.embedding),
            "employee": profile.employee,
            "employee_name": profile.employee_name,
            "enrolled_on": profile.enrolled_on,
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


@frappe.whitelist()
def get_hns_face_detection_logs(log_date=None, limit=50):
    return _get_face_logs(log_date, limit)

@frappe.whitelist()
def get_face_detection_logs(log_date=None, limit=50):
    return _get_face_logs(log_date, limit)

def _get_face_logs(log_date=None, limit=50):
    try:
        _require_login()
        target_date = log_date or today()
        start_datetime = f"{target_date} 00:00:00"
        end_datetime = f"{target_date} 23:59:59"

        logs = frappe.db.get_all(
            "Hns Face Detection Log",
            filters={
                "time": ["between", [start_datetime, end_datetime]]
            },
            fields=["name", "employee", "employee_name", "time", "log_type", "punch_category"],
            order_by="time desc, creation desc",
            limit_page_length=frappe.utils.cint(limit) or 50,
        )

        employee_names = {}
        formatted_logs = []
        for row in logs:
            emp = row.employee
            if not row.employee_name:
                if emp not in employee_names:
                    employee_names[emp] = frappe.db.get_value("Employee", emp, "employee_name") or emp
                emp_name = employee_names[emp]
            else:
                emp_name = row.employee_name

            time_str = frappe.utils.format_time(row.time) if row.time else ""
            category = row.punch_category or "Attendance"

            formatted_logs.append({
                "name": row.name,
                "employee": emp,
                "employee_name": emp_name,
                "time": time_str,
                "log_type": row.log_type,
                "category": category,
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