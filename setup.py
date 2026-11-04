from setuptools import setup, find_packages

setup(
    name="hns_face_detection",
    version="0.0.1",
    description="Face identification and manually confirmed ERPNext attendance",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "numpy",
        "opencv-python-headless",
        "insightface",
        "onnxruntime",
        "Pillow",
        "scikit-image",
        "scipy",
        "tqdm",
        "requests",
        "onnx",
    ],
)
