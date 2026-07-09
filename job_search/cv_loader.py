"""Loads CV text files from the cv/ directory. Supports .md and .txt.
PDF/docx are intentionally out of scope for the MVP (CVs will be
provided as plain text/Markdown)."""
import glob
import os
from typing import Dict

SUPPORTED_EXTENSIONS = (".md", ".markdown", ".txt")


def load_cvs(cv_dir: str) -> Dict[str, str]:
    """Returns {cv_name: raw_text} for every supported file in cv_dir."""
    cvs = {}
    if not os.path.isdir(cv_dir):
        return cvs
    for ext in SUPPORTED_EXTENSIONS:
        for path in sorted(glob.glob(os.path.join(cv_dir, f"*{ext}"))):
            name = os.path.splitext(os.path.basename(path))[0]
            if name.lower() == "readme":
                continue
            with open(path, "r", encoding="utf-8") as f:
                cvs[name] = f.read()
    return cvs
