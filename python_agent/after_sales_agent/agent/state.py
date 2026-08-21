from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class AgentTaskType(str, Enum):
    CONSULTATION = "consultation"
    FORMAL_REVIEW = "formal_review"


@dataclass(frozen=True)
class AgentState:
    task_type: AgentTaskType
    payload: dict[str, Any]

