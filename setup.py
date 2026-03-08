from setuptools import setup, find_packages

setup(
    name="pug",
    version="1.0",
    packages=find_packages(),
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
)
