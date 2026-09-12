"""Multimodal Visual Grounding package for MIRAGE."""

from workers.visual.clip_filter import CLIPPreFilter
from workers.visual.worker import VisualGroundingVerdict, VisualGroundingWorker

__all__ = [
    "CLIPPreFilter",
    "VisualGroundingVerdict",
    "VisualGroundingWorker",
]
