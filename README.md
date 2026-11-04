# Face Detection for ERPNext / Frappe v15

AI-powered facial recognition attendance system for ERPNext and Mobile Applications using InsightFace and OpenCV.

## System Prerequisites (Debian / Ubuntu / WSL)

Before running or installing the app, install the required native C/OpenGL shared libraries:

```bash
sudo apt update
sudo apt install -y libgl1 libglib2.0-0 libsm6 libxext6 libxrender1
```

> **Why this is required**: InsightFace and OpenCV (`cv2`) require native Linux shared libraries (`libGL.so.1`, `libgthread-2.0.so.0`, `libSM.so.6`, `libXext.so.6`, `libXrender.so.1`). Without these OS libraries, importing cv2 raises `ImportError: libGL.so.1: cannot open shared object file: No such file or directory`.

---

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

## Anti-Spoofing & Liveness Detection (Real Face & Motion Verification)

To prevent proxy attendance using mobile screen photos, printed pictures, or paper masks:
1. **InsightFace Liveness Neural Network**: Backend API initializes `FaceAnalysis` with official `addons=["liveness"]`. During attendance verification (`identify_employee`), each detected face is scored for true human 3D liveness. Screen replays and 2D photo prints are automatically rejected with a clear message.
2. **Kiosk Live Motion Verification**: The kiosk scanner analyzes pixel movement between consecutive frames. Static photos or frozen cameras trigger a *"Live face movement required"* prompt and block attendance until natural motion is observed.
3. **Safe Photo Enrollment**: High-resolution file uploads and passport photos in `Employee.image` can still be enrolled by administrators without false rejection.

---

All endpoints are whitelisted under `hns_face_detection.api.*`.

### 1. Face Identification (1:N Match)
Identifies employee face from webcam or mobile frame, checks daily status, and issues a secure confirmation token.

- **Endpoint**: `/api/method/hns_face_detection.api.identify_employee`
- **Method**: `POST`
- **Parameters**:
  - `image_data`: Base64 string / Data URL (`data:image/jpeg;base64,...`)
- **Example Response**:
```json
{
  "message": {
    "ok": true,
    "matched": true,
    "employee": "HR-EMP-00001",
    "employee_name": "Hiren Savaliya",
    "similarity": 0.8842,
    "confirmation_token": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
    "auto_action": "IN",
    "already_completed": false
  }
}
```

---

### 2. Attendance Confirmation
Confirms attendance using the issued confirmation token.

- **Endpoint**: `/api/method/hns_face_detection.api.confirm_attendance`
- **Method**: `POST`
- **Parameters**:
  - `confirmation_token`: 32-character hexadecimal token
  - `log_type`: `"IN"` or `"OUT"`
- **Example Response**:
```json
{
  "message": {
    "ok": true,
    "status": "success",
    "employee": "HR-EMP-00001",
    "employee_name": "Hiren Savaliya",
    "log_type": "IN",
    "time": "2026-11-02 10:25:30.123456",
    "similarity": 0.8842,
    "name": "FAL-2026-00001",
    "message": "Successfully marked IN for Hiren Savaliya"
  }
}
```

---

### 3. Face Profile Enrollment
Enrolls or replaces an employee's face vector.

- **Endpoint**: `/api/method/hns_face_detection.api.enroll_face`
- **Method**: `POST`
- **Parameters**:
  - `employee`: Employee ID
  - `image_data`: Base64 string / Data URL
  - `re_enroll`: 0 or 1
- **Example Response**:
```json
{
  "message": {
    "ok": true,
    "status": "success",
    "employee": "HR-EMP-00001",
    "employee_name": "Hiren Savaliya",
    "message": "Face profile enrolled successfully for HR-EMP-00001."
  }
}
```

---

### 4. Today's Attendance & Next Action
Fetches the employee's check-in / check-out history for today and the next expected action.

- **Endpoint**: `/api/method/hns_face_detection.api.get_today_attendance`
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

- **Endpoint**: `/api/method/hns_face_detection.api.get_face_profile_status`
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
2. **Real-time Verification**: Captures face frame, converts to base64, identifies employee via `hns_face_detection.api.identify_employee`, and confirms punch via `hns_face_detection.api.confirm_attendance`.
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
