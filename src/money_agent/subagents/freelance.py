"""
Freelance / Gig sub-agent — Upwork, Fiverr, local gigs.

Placeholder: wire web scrape or APIs when ready.
"""

from .base import SubAgentResult


def run_freelance_agent(task: str, context: dict) -> SubAgentResult:
    """
    Run the freelance sub-agent.

    Args:
        task: e.g. "check Upwork invites", "find gigs", "draft proposal"
        context: instructions, constraints

    Returns:
        SubAgentResult with invites, gigs, or draft
    """
    instructions = context.get("instructions", {})
    channels = instructions.get("channels", {})

    if not channels.get("freelancing", True):
        return SubAgentResult(
            success=False,
            summary="Freelancing channel disabled in instructions.",
            actions_suggested=[]
        )

    return SubAgentResult(
        success=True,
        summary="Freelance agent placeholder. Wire Upwork/Fiverr API or web scrape when ready.",
        data={"invites": [], "gigs": []},
        actions_suggested=[
            "Add Upwork API or scrape for invites",
            "Add Fiverr/gig board monitoring",
            "Draft proposal template from instructions"
        ]
    )
