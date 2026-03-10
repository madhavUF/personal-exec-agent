"""
Job Search sub-agent — role mapping, outreach, pipeline.

Uses job-search-accelerator skill logic when reference docs exist.
Falls back to web search + structured output for MVP.
"""

from .base import SubAgentResult

# Lazy imports to avoid loading heavy deps when not needed
def run_job_search(task: str, context: dict) -> SubAgentResult:
    """
    Run the job search sub-agent.

    Args:
        task: e.g. "find PM roles", "draft application for job X", "build role map"
        context: instructions, constraints, pipeline state

    Returns:
        SubAgentResult with jobs, drafts, or suggestions
    """
    task_lower = task.lower()
    instructions = context.get("instructions", {})
    objectives = instructions.get("objectives", [])
    constraints = instructions.get("constraints", {})

    # MVP: Use web search for job discovery
    if "find" in task_lower or "search" in task_lower or "scan" in task_lower:
        return _find_jobs(objectives, constraints)
    if "draft" in task_lower or "application" in task_lower:
        return _draft_application(task, context)
    if "role map" in task_lower or "rolemap" in task_lower:
        return _build_role_map(objectives, constraints)

    return SubAgentResult(
        success=False,
        summary="Unknown task. Use: find jobs, draft application, build role map.",
        actions_suggested=["Try: 'find PM roles matching my criteria'"]
    )


def _find_jobs(objectives: list, constraints: dict) -> SubAgentResult:
    """Search for jobs via web. Returns placeholder for now — wire web_search in orchestrator."""
    # Orchestrator will call web_search; this sub-agent returns structure
    industries_avoid = constraints.get("industries_avoid", [])
    work_style = constraints.get("work_style", "remote")
    min_comp = constraints.get("min_comp")

    return SubAgentResult(
        success=True,
        summary="Job search ready. Orchestrator should call web_search with query built from objectives + constraints.",
        data={
            "query_hint": f"remote product manager jobs {work_style}",
            "filters": {"avoid": industries_avoid, "min_comp": min_comp},
            "jobs": []  # Filled by orchestrator after web_search
        },
        actions_suggested=["Run web_search for job listings", "Add results to pipeline"]
    )


def _draft_application(task: str, context: dict) -> SubAgentResult:
    """Draft application — needs RAG (resume) + job details. Placeholder."""
    return SubAgentResult(
        success=True,
        summary="Draft application: orchestrator should use RAG (resume) + job details to generate tailored draft.",
        data={"draft": None},
        actions_suggested=["Search documents for resume", "Call LLM with job + resume to generate draft"]
    )


def _build_role_map(objectives: list, constraints: dict) -> SubAgentResult:
    """Build role map — expand beyond default title. Placeholder for job-search-accelerator workflow."""
    return SubAgentResult(
        success=True,
        summary="Role map: use job-search-accelerator references/role-mapping.md when available.",
        data={
            "roles": ["Product Manager", "Senior PM", "Technical PM", "Product Lead"],
            "rationale": "Expand from PM to adjacent roles per job-search-accelerator"
        },
        actions_suggested=["Save role map to documents", "Use for job search queries"]
    )
