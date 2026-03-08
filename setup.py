import subprocess
import sys

from setuptools import setup, find_packages
from setuptools.command.install import install


class PostInstall(install):
    """Run playwright install after pip install so browsers are available."""

    def run(self):
        install.run(self)
        if not self.dry_run:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "playwright", "install"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass  # leave it to the user to run "playwright install" if needed


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
    cmdclass={"install": PostInstall},
)
