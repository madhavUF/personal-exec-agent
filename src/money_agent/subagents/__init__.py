"""
Sub-agents for the money-earning orchestrator.

Each sub-agent is invoked by the orchestrator with a task + context.
Returns structured results (list of jobs, draft text, etc.).
"""

from .job_search import run_job_search
from .freelance import run_freelance_agent
from .base import SubAgentResult

__all__ = ["run_job_search", "run_freelance_agent", "SubAgentResult"]
