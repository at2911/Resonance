"""Composes the Slack incident-update message.

Deliberately deterministic, not LLM-generated: this text goes straight
into a real, permanent Slack channel the moment a human approves it, so it
is built directly from confirmed IncidentState the same way the clarity
score and final summary are — no risk of the wording drifting from what's
actually established. It is still shown to a human for explicit approval
before anything is posted (see app/api/slack.py), consistent with every
other external action in this system.
"""

from __future__ import annotations

from app.models.enums import ClaimStatus, ClaimType, GapImportance, GapStatus
from app.models.incident import Incident

RECENT_FACTS_LIMIT = 2


class SlackMessageComposer:
    @staticmethod
    def compose(incident: Incident) -> str:
        lines = [
            SlackMessageComposer._facts_line(incident),
            SlackMessageComposer._root_cause_line(incident),
            SlackMessageComposer._investigation_line(incident),
        ]
        gaps_line = SlackMessageComposer._critical_gaps_line(incident)
        if gaps_line:
            lines.append(gaps_line)
        return "\n".join(line for line in lines if line)

    @staticmethod
    def _facts_line(incident: Incident) -> str:
        confirmed = [
            c
            for c in incident.claims.values()
            if c.type == ClaimType.FACT and c.status == ClaimStatus.CONFIRMED
        ]
        confirmed.sort(key=lambda c: c.timestamp)
        if not confirmed:
            return f"Incident: {incident.title}. No facts have been confirmed yet."
        recent = confirmed[-RECENT_FACTS_LIMIT:]
        return " ".join(_sentence(c.normalized_claim) for c in recent)

    @staticmethod
    def _root_cause_line(incident: Incident) -> str:
        if incident.root_cause_confirmed():
            confirmed_root_cause = next(
                (
                    c
                    for c in incident.claims.values()
                    if c.type == ClaimType.FACT
                    and c.status == ClaimStatus.CONFIRMED
                    and "root cause" in c.normalized_claim.lower()
                ),
                None,
            )
            if confirmed_root_cause:
                return _sentence(confirmed_root_cause.normalized_claim)
            return "Root cause has been confirmed."

        open_hypotheses = [
            c
            for c in incident.claims.values()
            if c.type == ClaimType.HYPOTHESIS
            and c.status in (ClaimStatus.UNCONFIRMED, ClaimStatus.PROBABLE, ClaimStatus.DISPUTED)
        ]
        if open_hypotheses:
            open_hypotheses.sort(key=lambda c: c.timestamp)
            leading = open_hypotheses[-1]
            return f"{_sentence(leading.normalized_claim)} remains unconfirmed."
        return "Root cause remains unconfirmed."

    @staticmethod
    def _investigation_line(incident: Incident) -> str:
        open_actions = [a for a in incident.actions.values() if a.status.value in ("OPEN", "IN_PROGRESS", "BLOCKED")]
        if open_actions:
            return f"Investigation is ongoing ({len(open_actions)} open action(s))."
        return "No investigation actions are currently open."

    @staticmethod
    def _critical_gaps_line(incident: Incident) -> str:
        critical_gaps = [
            g.description
            for g in incident.information_gaps.values()
            if g.status == GapStatus.OPEN and g.importance == GapImportance.CRITICAL
        ]
        if not critical_gaps:
            return ""
        return "Open critical gaps: " + "; ".join(critical_gaps) + "."


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if not text.endswith((".", "!", "?")):
        text += "."
    return text
