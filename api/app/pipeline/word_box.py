"""Shared by app/pipeline/extract.py (born-digital) and app/pipeline/ocr.py (scanned) -
split into its own module so neither has to import the other just for this type."""

from dataclasses import dataclass


@dataclass
class WordBox:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
