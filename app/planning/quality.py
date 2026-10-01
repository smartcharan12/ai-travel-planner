"""Cheap, always-on quality signals for every itinerary (the 'smoke alarm').

Offline DeepEval evaluation (Stage 4) is the full inspection; these numbers
are computed on every request at zero cost and returned to the client.
"""

from __future__ import annotations

from app.schemas import BudgetBreakdown, CostBasis, Itinerary, QualityReport, ValidationIssue


def build_quality_report(
    itinerary: Itinerary,
    budget: BudgetBreakdown,
    issues: list[ValidationIssue],
    repair_attempts: int,
    optimization_notes: list[str],
) -> QualityReport:
    activities = [a for d in itinerary.days for a in d.activities]
    grounded = sum(1 for a in activities if a.place_id is not None)
    sourced_amount = sum(i.amount for i in budget.items if i.basis == CostBasis.SOURCE)
    return QualityReport(
        grounded_activity_ratio=round(grounded / len(activities), 3) if activities else 0.0,
        sourced_cost_ratio=round(sourced_amount / budget.total, 3) if budget.total > 0 else 0.0,
        repair_attempts=repair_attempts,
        issues=issues,
        optimization_notes=optimization_notes,
    )
