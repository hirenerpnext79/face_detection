__version__ = "31.10.26"

try:
    import cv2
except ImportError as _cv2_err:
    if "libGL" in str(_cv2_err) or "cannot open shared object file" in str(_cv2_err):
        import subprocess
        import sys
        try:
            subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "opencv-python"], check=False)
            subprocess.run([sys.executable, "-m", "pip", "install", "opencv-python-headless"], check=False)
        except Exception:
            pass

