"""Programmatic execution flows selected by the single AfterSalesAgent."""

from .consultation import ConsultationWorkflow
from .formal_review import FormalReviewWorkflow

__all__ = ["ConsultationWorkflow", "FormalReviewWorkflow"]

