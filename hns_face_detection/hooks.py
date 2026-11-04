app_name = "hns_face_detection"
app_title = "HNS Face Detection"
app_publisher = "HNS Face Detection"
app_description = "InsightFace identification with manually confirmed Employee Checkin"
app_email = "admin@example.com"
app_license = "MIT"

# Desk page and DocType are discovered through normal Frappe app module loading.

doc_events = {
    "Hns Employee Face Profile": {
        "on_update": "hns_face_detection.api._invalidate_profiles_cache",
        "on_trash": "hns_face_detection.api._invalidate_profiles_cache",
    }
}
