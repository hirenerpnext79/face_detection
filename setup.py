from setuptools import setup, find_packages

setup(
    name="face_attendance",
    version="0.0.1",
    description="Face identification and manually confirmed ERPNext attendance",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
)
