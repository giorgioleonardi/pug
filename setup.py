import re
from pathlib import Path

from setuptools import find_packages, setup

HERE = Path(__file__).parent
VERSION = re.search(r'^__version__ = "([^"]+)"', (HERE / "core" / "version.py").read_text(encoding="utf-8"), re.M).group(1)

setup(
    name="pug-cli",
    version=VERSION,
    description="Scrapes one docs URL, asks Claude for a command map, and generates a thin local Go Cobra CLI wrapper plus agent notes.",
    long_description=(HERE / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="Giorgio Leonardi",
    url="https://github.com/giorgioleonardi/pug",
    project_urls={
        "Source": "https://github.com/giorgioleonardi/pug",
        "Issues": "https://github.com/giorgioleonardi/pug/issues",
    },
    license="MIT",
    license_files=["LICENSE"],
    python_requires=">=3.10",
    packages=find_packages(exclude=["tests", "tests.*"]),
    py_modules=["main"],
    install_requires=[
        "anthropic>=0.39.0",
        "playwright>=1.40.0",
        "html2text>=2024.2.26",
        "rich>=13.0.0",
        "requests>=2.28.0",
    ],
    entry_points={
        "console_scripts": [
            "pug=main:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Code Generators",
    ],
)
