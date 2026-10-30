# Face Detection for ERPNext / Frappe v15

AI-powered facial recognition attendance system for ERPNext and Mobile Applications using InsightFace and OpenCV.

## Purpose

1. **Face Profile Enrollment**: Enroll employee face vectors either via web camera capture, mobile camera photo, or direct photo attachment in `Employee Face Profile`.
2. **Desk Face Detection**: Dedicated Workspace (`/app/face-detection`) and live camera kiosk page (`/app/face-detection-kiosk`) for real-time employee identification and IN/OUT check-in.
3. **Mobile App Integration**: Dedicated REST APIs allowing mobile applications to capture face photos, perform 1:1 or 1:N face detection, and automatically record attendance check-in and check-out logs.
4. **Attendance Storage**:
   - Stores full history in `Face Detection Log` (includes Employee, Time, Log Type, Similarity Score).
   - If ERPNext `Employee Checkin` exists (e.g. from HRMS), also writes to `Employee Checkin` for auto-attendance and shift processing.

---

## Resolution: "Face Embedding is required" Validation Error

### Cause
Previously, `EmployeeFaceProfile.validate()` threw an unhandled validation error (`Face Embedding is required. Please capture a photo using the camera.`) whenever an Employee Face Profile was saved without an existing face embedding or employee image. This prevented users from creating or saving Employee Face Profile records from Desk.

### Solution Applied
1. Allowed saving `Employee Face Profile` without an embedding: if no embedding is present, the profile is saved with `is_enrolled = 0` and a non-blocking alert is displayed.
2. When an embedding is present or captured, `is_enrolled = 1` is automatically marked.
3. In `EmployeeFaceProfile.validate()`:
   - Safely checks for `Employee.image` to auto-extract the face embedding with error handling if face extraction fails.
   - Sets `is_enrolled = 0` if not yet captured, without throwing an error, so the document can always be saved.
4. Added **Capture Face** button directly on the form header for easy enrollment via live camera or direct photo upload fallback.

---

## Mobile App API Endpoints

All endpoints are whitelisted under `face_detection.api.*`.

### 1. Mobile Face Check-in / Check-out
Single-step facial recognition and check-in / check-out log storage.

- **Endpoint**: `/api/method/face_detection.api.mobile_face_checkin`
- **Method**: `POST`
- **Headers**:
  - `Content-Type: application/json`
  - `Authorization: token <api_key>:<api_secret>` (or active session cookie)
- **Parameters**:
  | Field | Type | Description |
  |---|---|---|
  | `image_data` | String (Required) | Base64 encoded string or Data URL (`data:image/jpeg;base64,...`) |
  | `log_type` | String (Optional) | `"IN"`, `"OUT"`, or `"AUTO"` / omit. When omitted or `"AUTO"`, toggles automatically based on today's last log |
  | `employee` | String (Optional) | Specific Employee ID for 1:1 verification. If omitted, performs 1:N identification across all active profiles |
  | `latitude` | Float (Optional) | GPS Latitude from mobile device |
  | `longitude` | Float (Optional) | GPS Longitude from mobile device |
  | `device_id` | String (Optional) | Device identifier (e.g. `"Samsung S23"`, `"Mobile-App"`) |

- **Example Request**:
```json
{
  "image_data": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD...",
  "log_type": "AUTO",
  "employee": "HR-EMP-00001",
  "latitude": 12.9716,
  "longitude": 77.5946,
  "device_id": "Flutter-Mobile-App"
}
```

- **Example Response**:
```json
{
  "message": {
    "status": "success",
    "ok": true,
    "message": "Successfully marked IN for Hiren Savaliya",
    "employee": "HR-EMP-00001",
    "employee_name": "Hiren Savaliya",
    "log_type": "IN",
    "time": "2026-10-28 10:25:30.123456",
    "similarity": 0.8842,
    "log_name": "FAL-2026-00001"
  }
}
```

---

### 2. Mobile Face Verification / Detection Preview
Detects face and verifies identity without writing an attendance log.

- **Endpoint**: `/api/method/face_detection.api.mobile_detect_and_verify`
- **Method**: `POST`
- **Parameters**:
  - `image_data`: Base64 string / Data URL
  - `employee`: Optional Employee ID for 1:1 match
- **Example Response**:
```json
{
  "message": {
    "matched": true,
    "employee": "HR-EMP-00001",
    "employee_name": "Hiren Savaliya",
    "similarity": 0.8842,
    "threshold": 0.45
  }
}
```

---

### 3. Mobile Face Profile Enrollment
Enrolls or replaces an employee's face vector directly from mobile camera.

- **Endpoint**: `/api/method/face_detection.api.mobile_enroll_face`
- **Method**: `POST`
- **Parameters**:
  - `employee`: Employee ID
  - `image_data`: Base64 string / Data URL
- **Example Response**:
```json
{
  "message": {
    "status": "success",
    "ok": true,
    "employee": "HR-EMP-00001",
    "employee_name": "Hiren Savaliya",
    "message": "Face profile enrolled successfully."
  }
}
```

---

### 4. Today's Attendance & Next Action
Fetches the employee's check-in / check-out history for today and the next expected action.

- **Endpoint**: `/api/method/face_detection.api.get_today_attendance`
- **Method**: `POST`
- **Parameters**:
  - `employee`: Optional Employee ID (defaults to session user's employee)
- **Example Response**:
```json
{
  "message": {
    "employee": "HR-EMP-00001",
    "logs": [
      {
        "name": "FAL-2026-00001",
        "employee": "HR-EMP-00001",
        "employee_name": "Hiren Savaliya",
        "log_type": "IN",
        "time": "2026-10-28 10:21:48.230735",
        "similarity_score": 0.88
      }
    ],
    "next_action": "OUT",
    "count": 1
  }
}
```

---

### 5. Profile Status Check
Checks if an employee has an active enrolled face embedding.

- **Endpoint**: `/api/method/face_detection.api.get_face_profile_status`
- **Method**: `POST`
- **Parameters**:
  - `employee`: Employee ID
- **Example Response**:
```json
{
  "message": {
    "enrolled": true,
    "employee": "HR-EMP-00001",
    "employee_name": "Hiren Savaliya",
    "enrolled_on": "2026-10-28 10:20:00"
  }
}
```

---

## Flutter Mobile Application (`face_detection_mobile`)

A cross-platform Flutter mobile application is located in `face_detection_mobile/`.

### Features
1. **Live Camera Face Scanner**: Biometric oval viewfinder with front/rear camera toggle and auto-scan mode.
2. **Real-time Checkin**: Captures face frame, converts to base64, and calls `/api/method/face_detection.api.mobile_face_checkin`.
3. **Smart Response Handling**:
   - **Success**: Displays employee name, badge (IN/OUT), and similarity percentage.
   - **Already Completed**: Informs user if both IN and OUT entries are already logged today.
   - **Error Feedback**: Provides specific failure reasons (no face detected, unverified face, or connection timeout).
4. **Settings & History**: Configurable ERPNext base URL and API credentials with connection tester, plus today's attendance log viewer.

### Running the Mobile App
```bash
cd face_detection_mobile
flutter run
```
