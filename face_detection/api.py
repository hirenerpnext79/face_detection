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
import numpy as np
from frappe.utils import now_datetime, today

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
    _require_login()
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
            )
            _face_app.prepare(ctx_id=-1, det_size=(640, 640))
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Face Detection: model initialization failed")
            frappe.throw("Face model could not be initialized. Verify InsightFace installation and server logs.")
    return _face_app


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


def load_image_from_file(image_value):
    try:
        if not image_value:
            return None

        clean_path = image_value.lstrip("/")
        candidate_paths = [
            frappe.get_site_path("public", clean_path),
            frappe.get_site_path(clean_path),
            frappe.get_site_path("public", "files", os.path.basename(image_value)),
            frappe.get_site_path("private", "files", os.path.basename(image_value)),
        ]

        for path in candidate_paths:
            if os.path.exists(path):
                img = cv2.imread(path)
                if img is not None:
                    return img

        file_doc = frappe.db.get_value("File", {"file_url": image_value}, ["file_name", "is_private"], as_dict=True)
        if file_doc:
            folder = "private/files" if file_doc.is_private else "public/files"
            db_path = frappe.get_site_path(folder, file_doc.file_name)
            if os.path.exists(db_path):
                img = cv2.imread(db_path)
                if img is not None:
                    return img

        return None
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Face Detection: load_image_from_file error")
        return None


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

    if image_input.startswith("data:") or len(image_input) > 500:
        image = _decode_image(image_input)
    else:
        image = load_image_from_file(image_input)
        if image is None:
            frappe.throw(f"Could not load image from file {image_input}")

    return _extract_embedding_from_array(image)


def _cosine_similarity(left, right):
    left = np.asarray(left, dtype=np.float32)
    right = np.asarray(right, dtype=np.float32)
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 0:
        return -1.0
    return float(np.dot(left, right) / denom)


def _find_best_match(probe_embedding):
    profiles = frappe.get_all(
        "Employee Face Profile",
        filters={"active": 1},
        fields=["name", "employee", "embedding"],
        limit_page_length=10000,
    )

    best_match = None
    best_score = -1.0

    for profile in profiles:
        try:
            if not profile.embedding:
                continue
            candidate = np.asarray(json.loads(profile.embedding), dtype=np.float32)
            if candidate.ndim != 1 or candidate.size != probe_embedding.size:
                continue
            score = _cosine_similarity(probe_embedding, candidate)
            if score > best_score:
                best_score = score
                best_match = profile
        except (ValueError, TypeError, json.JSONDecodeError):
            frappe.log_error(f"Invalid embedding in {profile.name}", "Face Detection: corrupt embedding")

    if best_match and best_score >= MATCH_THRESHOLD:
        return {"employee": best_match.employee, "similarity": best_score}

    return None


def get_auto_log_type(employee):
    try:
        today_date = today()
        today_logs = frappe.db.get_all(
            "Face Detection Log",
            filters={
                "employee": employee,
                "time": [">=", f"{today_date} 00:00:00"]
            },
            fields=["log_type", "time"],
            order_by="time asc, creation asc",
        )

        if not today_logs and frappe.db.exists("DocType", "Employee Checkin"):
            today_logs = frappe.db.get_all(
                "Employee Checkin",
                filters={
                    "employee": employee,
                    "time": [">=", f"{today_date} 00:00:00"]
                },
                fields=["log_type", "time"],
                order_by="time asc, creation asc",
            )

        if not today_logs:
            return "IN"

        last_log_type = today_logs[-1].log_type
        if last_log_type == "IN":
            return "OUT"
        return "IN"
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Face Detection: auto log type error")
        return "IN"


def record_attendance_log(employee, log_type, similarity=None, device_id=None, latitude=None, longitude=None):
    try:
        checkin_time = now_datetime()
        employee_name = frappe.db.get_value("Employee", employee, "employee_name") or employee

        log_doc = frappe.get_doc({
            "doctype": "Face Detection Log",
            "employee": employee,
            "employee_name": employee_name,
            "log_type": log_type,
            "time": checkin_time,
            "similarity_score": similarity,
        })
        log_doc.insert(ignore_permissions=True)

        if frappe.db.exists("DocType", "Employee Checkin"):
            checkin_data = {
                "doctype": "Employee Checkin",
                "employee": employee,
                "time": checkin_time,
                "log_type": log_type,
                "device_id": device_id or "Face Detection",
            }
            if latitude and hasattr(frappe.get_meta("Employee Checkin"), "latitude"):
                checkin_data["latitude"] = latitude
            if longitude and hasattr(frappe.get_meta("Employee Checkin"), "longitude"):
                checkin_data["longitude"] = longitude

            employee_checkin = frappe.get_doc(checkin_data)
            employee_checkin.insert(ignore_permissions=True)

        frappe.db.commit()
        return log_doc
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Face Detection: failed to record attendance")
        raise


@frappe.whitelist()
def enroll_face(employee, image_data):
    try:
        _require_enrollment_role()
        if not employee or not frappe.db.exists("Employee", employee):
            frappe.throw("A valid Employee ID is required.")

        employee_doc = frappe.get_doc("Employee", employee)
        if employee_doc.status and employee_doc.status != "Active":
            frappe.throw("Only active employees can be enrolled.")

        embedding = extract_embedding_from_file_or_data(image_data)
        profile_name = frappe.db.get_value("Employee Face Profile", {"employee": employee}, "name")

        values = {
            "employee": employee,
            "employee_name": employee_doc.employee_name or employee,
            "active": 1,
            "is_enrolled": 1,
            "embedding": json.dumps(embedding.tolist(), separators=(",", ":")),
            "enrolled_by": frappe.session.user,
            "enrolled_on": now_datetime(),
        }

        if profile_name:
            profile = frappe.get_doc("Employee Face Profile", profile_name)
            profile.update(values)
            profile.save(ignore_permissions=True)
        else:
            profile = frappe.get_doc({"doctype": "Employee Face Profile", **values})
            profile.insert(ignore_permissions=True)

        frappe.db.commit()
        return {
            "ok": True,
            "employee": employee,
            "employee_name": employee_doc.employee_name or employee,
            "message": f"Face profile enrolled successfully for {employee}."
        }
    except frappe.ValidationError:
        raise
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Face Detection: enroll_face failed")
        raise


@frappe.whitelist()
def identify_employee(image_data):
    try:
        _require_login()
        probe = extract_embedding_from_file_or_data(image_data)
        match = _find_best_match(probe)

        if not match:
            frappe.throw("No enrolled employee matched confidently. Please adjust lighting or verify enrollment.")

        matched_employee = match["employee"]
        employee_doc = frappe.get_doc("Employee", matched_employee)
        if employee_doc.status and employee_doc.status != "Active":
            frappe.throw("The matched employee is not active.")

        token = uuid.uuid4().hex
        cache_key = "face_detection:confirmation:" + token
        frappe.cache().set_value(
            cache_key,
            {"employee": matched_employee, "user": frappe.session.user, "similarity": match["similarity"]},
            expires_in_sec=CONFIRMATION_TTL_SECONDS,
        )

        auto_action = get_auto_log_type(matched_employee)

        return {
            "employee": matched_employee,
            "employee_name": employee_doc.employee_name or matched_employee,
            "similarity": round(match["similarity"], 4),
            "confirmation_token": token,
            "expires_in_seconds": CONFIRMATION_TTL_SECONDS,
            "auto_action": auto_action,
        }
    except frappe.ValidationError:
        raise
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Face Detection: identify_employee failed")
        raise


@frappe.whitelist()
def confirm_attendance(confirmation_token, log_type):
    try:
        _require_login()
        if log_type not in ("IN", "OUT"):
            frappe.throw("log_type must be IN or OUT.")

        if not isinstance(confirmation_token, str) or not re.fullmatch(r"[a-f0-9]{32}", confirmation_token):
            frappe.throw("Invalid confirmation token. Identify the employee again.")

        cache_key = "face_detection:confirmation:" + confirmation_token
        payload = frappe.cache().get_value(cache_key)
        if not payload:
            frappe.throw("Confirmation expired or already used. Identify the employee again.")

        if payload.get("user") != frappe.session.user:
            frappe.throw("This confirmation belongs to another user.", frappe.PermissionError)

        frappe.cache().delete_value(cache_key)
        employee = payload.get("employee")
        if not employee or not frappe.db.exists("Employee", employee):
            frappe.throw("Employee record no longer exists.")

        employee_doc = frappe.get_doc("Employee", employee)
        if employee_doc.status and employee_doc.status != "Active":
            frappe.throw("Only active employees can check in/out.")

        log_record = record_attendance_log(
            employee=employee,
            log_type=log_type,
            similarity=payload.get("similarity"),
            device_id="Face Detection Kiosk",
        )

        return {
            "ok": True,
            "name": log_record.name,
            "employee": employee,
            "employee_name": employee_doc.employee_name or employee,
            "log_type": log_type,
            "message": f"Attendance recorded for {employee_doc.employee_name or employee} ({log_type}).",
        }
    except frappe.ValidationError:
        raise
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Face Detection: confirm_attendance failed")
        raise


@frappe.whitelist(allow_guest=True)
def mobile_face_checkin(image_data=None, log_type=None, employee=None, latitude=None, longitude=None, device_id=None, probe_embedding=None, similarity_score=None):
    try:
        matched_employee = None
        matched_score = 0.0

        if probe_embedding is not None and similarity_score is not None and employee:
            matched_employee = employee
            matched_score = float(similarity_score)
        else:
            if not image_data:
                frappe.throw("Image data is required.")

            probe_vec = extract_embedding_from_file_or_data(image_data)

            if employee:
                profile = frappe.db.get_value(
                    "Employee Face Profile",
                    {"employee": employee, "active": 1},
                    ["name", "employee", "embedding"],
                    as_dict=True,
                )
                if not profile or not profile.embedding:
                    frappe.throw(f"No active face profile enrolled for employee {employee}.")

                candidate_vec = np.asarray(json.loads(profile.embedding), dtype=np.float32)
                score = _cosine_similarity(probe_vec, candidate_vec)
                if score < MATCH_THRESHOLD:
                    frappe.throw("Face verification failed. Face does not match the employee.")
                matched_employee = employee
                matched_score = score
            else:
                match = _find_best_match(probe_vec)
                if not match:
                    frappe.throw("No enrolled employee matched confidently. Please verify lighting and camera positioning.")
                matched_employee = match["employee"]
                matched_score = match["similarity"]

        employee_doc = frappe.get_doc("Employee", matched_employee)
        if employee_doc.status and employee_doc.status != "Active":
            frappe.throw(f"Employee {matched_employee} is not active.")

        final_log_type = (log_type or "").upper()
        if final_log_type not in ("IN", "OUT"):
            final_log_type = get_auto_log_type(matched_employee)

        log_record = record_attendance_log(
            employee=matched_employee,
            log_type=final_log_type,
            similarity=round(float(matched_score), 4),
            device_id=device_id or "Mobile App",
            latitude=latitude,
            longitude=longitude,
        )

        return {
            "status": "success",
            "ok": True,
            "message": f"Successfully marked {final_log_type} for {employee_doc.employee_name or matched_employee}",
            "employee": matched_employee,
            "employee_name": employee_doc.employee_name or matched_employee,
            "log_type": final_log_type,
            "time": str(log_record.time),
            "similarity": round(float(matched_score), 4),
            "log_name": log_record.name,
        }
    except frappe.ValidationError as e:
        return {
            "status": "error",
            "ok": False,
            "message": _get_clean_error_message(e),
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Face Detection: mobile_face_checkin failed")
        return {
            "status": "error",
            "ok": False,
            "message": "Face checkin failed. Please try again.",
        }


@frappe.whitelist(allow_guest=True)
def mobile_detect_and_verify(image_data, employee=None):
    try:
        if not image_data:
            frappe.throw("Image data is required.")

        probe_embedding = extract_embedding_from_file_or_data(image_data)

        if employee:
            profile = frappe.db.get_value(
                "Employee Face Profile",
                {"employee": employee, "active": 1},
                ["name", "employee", "embedding"],
                as_dict=True,
            )
            if not profile or not profile.embedding:
                return {
                    "matched": False,
                    "employee": employee,
                    "similarity": 0.0,
                    "message": f"No active face profile enrolled for {employee}.",
                    "threshold": MATCH_THRESHOLD,
                }

            candidate_vec = np.asarray(json.loads(profile.embedding), dtype=np.float32)
            score = _cosine_similarity(probe_embedding, candidate_vec)
            matched = bool(score >= MATCH_THRESHOLD)
            employee_doc = frappe.get_doc("Employee", employee)
            employee_name = employee_doc.employee_name or employee
            auto_action = get_auto_log_type(employee)
            return {
                "matched": matched,
                "employee": employee,
                "employee_name": employee_name,
                "department": employee_doc.department or "",
                "designation": employee_doc.designation or "",
                "similarity": round(float(score), 4),
                "threshold": MATCH_THRESHOLD,
                "auto_action": auto_action,
                "probe_embedding": probe_embedding.tolist(),
            }

        match = _find_best_match(probe_embedding)
        if not match:
            return {
                "matched": False,
                "message": "No enrolled employee matched above threshold.",
                "threshold": MATCH_THRESHOLD,
            }

        matched_employee = match["employee"]
        employee_doc = frappe.get_doc("Employee", matched_employee)
        employee_name = employee_doc.employee_name or matched_employee
        auto_action = get_auto_log_type(matched_employee)
        return {
            "matched": True,
            "employee": matched_employee,
            "employee_name": employee_name,
            "department": employee_doc.department or "",
            "designation": employee_doc.designation or "",
            "similarity": round(float(match["similarity"]), 4),
            "threshold": MATCH_THRESHOLD,
            "auto_action": auto_action,
            "probe_embedding": probe_embedding.tolist(),
        }
    except frappe.ValidationError as e:
        return {
            "matched": False,
            "message": _get_clean_error_message(e),
            "threshold": MATCH_THRESHOLD,
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Face Detection: mobile_detect_and_verify failed")
        return {
            "matched": False,
            "message": "Face detection failed. Please try again.",
            "threshold": MATCH_THRESHOLD,
        }


@frappe.whitelist(allow_guest=True)
def mobile_enroll_face(employee, image_data):
    try:
        if not employee or not frappe.db.exists("Employee", employee):
            frappe.throw("A valid Employee ID is required.")

        if frappe.session.user != "Guest":
            has_enroll_role = bool(ALLOWED_ENROLLMENT_ROLES.intersection(set(frappe.get_roles(frappe.session.user))))
            linked_employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
            is_self = bool(linked_employee and linked_employee == employee)

            if not has_enroll_role and not is_self:
                frappe.throw("Only HR Manager, System Manager, or the employee can enroll face profiles.", frappe.PermissionError)

        employee_doc = frappe.get_doc("Employee", employee)
        if employee_doc.status and employee_doc.status != "Active":
            frappe.throw("Only active employees can be enrolled.")

        embedding = extract_embedding_from_file_or_data(image_data)
        profile_name = frappe.db.get_value("Employee Face Profile", {"employee": employee}, "name")

        values = {
            "employee": employee,
            "employee_name": employee_doc.employee_name or employee,
            "active": 1,
            "is_enrolled": 1,
            "embedding": json.dumps(embedding.tolist(), separators=(",", ":")),
            "enrolled_by": frappe.session.user if frappe.session.user != "Guest" else "Mobile Enrollment",
            "enrolled_on": now_datetime(),
        }

        if profile_name:
            profile = frappe.get_doc("Employee Face Profile", profile_name)
            profile.update(values)
            profile.save(ignore_permissions=True)
        else:
            profile = frappe.get_doc({"doctype": "Employee Face Profile", **values})
            profile.insert(ignore_permissions=True)

        frappe.db.commit()
        return {
            "status": "success",
            "ok": True,
            "employee": employee,
            "employee_name": employee_doc.employee_name or employee,
            "message": "Face profile enrolled successfully."
        }
    except frappe.ValidationError:
        raise
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Face Detection: mobile_enroll_face failed")
        raise


@frappe.whitelist()
def get_today_attendance(employee=None):
    try:
        _require_login()
        if not employee and frappe.session.user != "Administrator":
            employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")

        today_start = today() + " 00:00:00"
        filters = {"time": [">=", today_start]}
        if employee:
            filters["employee"] = employee

        logs = frappe.get_all(
            "Face Detection Log",
            filters=filters,
            fields=["name", "employee", "employee_name", "log_type", "time", "similarity_score"],
            order_by="time asc",
            limit_page_length=50,
        )

        next_action = "IN"
        if logs and logs[-1].log_type == "IN":
            next_action = "OUT"

        return {
            "employee": employee,
            "logs": logs,
            "next_action": next_action,
            "count": len(logs)
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Face Detection: get_today_attendance failed")
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
            "Employee Face Profile",
            {"employee": employee},
            ["name", "employee", "employee_name", "active", "is_enrolled", "enrolled_on"],
            as_dict=True,
        )

        if not profile:
            return {"enrolled": False, "employee": employee}

        return {
            "enrolled": bool(profile.is_enrolled and profile.active),
            "employee": profile.employee,
            "employee_name": profile.employee_name,
            "enrolled_on": profile.enrolled_on,
        }
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Face Detection: get_face_profile_status failed")
        raise


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


@frappe.whitelist(allow_guest=True)
def login(usr, pwd):
    try:
        from frappe.auth import LoginManager
        frappe.local.form_dict.usr = usr
        frappe.local.form_dict.pwd = pwd
        login_manager = LoginManager()
        login_manager.authenticate(usr, pwd)
        login_manager.post_login()
        sid = frappe.session.sid
        frappe.db.commit()

        user = frappe.get_doc("User", frappe.session.user)

        return {
            "status": "success",
            "message": "Authentication Success",
            "sid": sid,
            "username": user.username or user.name,
            "email": user.email or user.name,
            "full_name": user.full_name or user.name,
        }
    except Exception as e:
        error_msg = _get_clean_error_message(e)
        frappe.log_error(title="API Login Error", message=error_msg)
        return {
            "status": "error",
            "message": error_msg or "Invalid login credentials.",
        }


@frappe.whitelist(allow_guest=True)
def face_login(image_data, device_id=None, employee=None, latitude=None, longitude=None):
    try:
        if not image_data:
            frappe.throw("Image data is required.")

        verification = mobile_detect_and_verify(image_data=image_data, employee=employee)
        if not verification.get("matched"):
            return {
                "status": "error",
                "message": verification.get("message") or "Face not recognized. Please adjust lighting or try manual login.",
            }

        matched_employee = verification["employee"]
        employee_doc = frappe.get_doc("Employee", matched_employee)
        if employee_doc.status and employee_doc.status != "Active":
            return {
                "status": "error",
                "message": f"Employee {matched_employee} is not active.",
            }

        user_id = employee_doc.user_id or "Administrator"

        from frappe.auth import LoginManager
        login_manager = LoginManager()
        login_manager.login_as(user_id)
        sid = frappe.session.sid

        probe_vec = verification.get("probe_embedding")
        checkin_result = mobile_face_checkin(
            image_data=None,
            employee=matched_employee,
            device_id=device_id or "Mobile Face Login",
            latitude=latitude,
            longitude=longitude,
            probe_embedding=probe_vec,
            similarity_score=verification.get("similarity"),
        )

        frappe.db.commit()

        user_doc = frappe.get_doc("User", user_id)
        full_name = user_doc.full_name or employee_doc.employee_name or user_id

        return {
            "status": "success",
            "message": checkin_result.get("message") or f"Welcome, {full_name}!",
            "sid": sid,
            "username": user_doc.username or user_id,
            "email": user_doc.email or user_id,
            "full_name": full_name,
            "user_id": user_id,
            "employee": matched_employee,
            "employee_name": employee_doc.employee_name or matched_employee,
            "log_type": checkin_result.get("log_type", "IN"),
            "time": checkin_result.get("time"),
            "similarity": checkin_result.get("similarity", verification.get("similarity")),
            "log_name": checkin_result.get("log_name"),
        }
    except Exception as e:
        error_msg = _get_clean_error_message(e)
        frappe.log_error(title="API Face Login Error", message=error_msg)
        return {
            "status": "error",
            "message": error_msg or "Face recognition login failed.",
        }

