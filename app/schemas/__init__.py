"""Pydantic schemas: the typed contracts between every component.

Import from here (``from app.schemas import TravelRequest``) rather than from
the individual modules, so files can be reorganised without breaking callers.
"""

from app.schemas.common import CostBasis, Source
from app.schemas.itinerary import (
    AccommodationChoice,
    Activity,
    ActivityType,
    BudgetBreakdown,
    DailyPlan,
    Itinerary,
    TimeSlot,
)
from app.schemas.request import (
    AccommodationType,
    DietaryPreference,
    Pace,
    TransportMode,
    TravelPreferences,
    TravelRequest,
    TravelStyle,
)
from app.schemas.research import (
    Attraction,
    DestinationInfo,
    Hotel,
    ResearchCategory,
    ResearchResult,
    Restaurant,
    SearchHit,
    Transportation,
)
from app.schemas.response import (
    ErrorBody,
    ErrorResponse,
    HealthResponse,
    IssueSeverity,
    MetricsResponse,
    PlanMetadata,
    QualityReport,
    TravelResponse,
    ValidationIssue,
    VersionResponse,
)

__all__ = [
    "AccommodationChoice",
    "AccommodationType",
    "Activity",
    "ActivityType",
    "Attraction",
    "BudgetBreakdown",
    "CostBasis",
    "DailyPlan",
    "DestinationInfo",
    "DietaryPreference",
    "ErrorBody",
    "ErrorResponse",
    "HealthResponse",
    "Hotel",
    "IssueSeverity",
    "Itinerary",
    "MetricsResponse",
    "Pace",
    "PlanMetadata",
    "QualityReport",
    "ResearchCategory",
    "ResearchResult",
    "Restaurant",
    "SearchHit",
    "Source",
    "TimeSlot",
    "TransportMode",
    "Transportation",
    "TravelPreferences",
    "TravelRequest",
    "TravelResponse",
    "TravelStyle",
    "ValidationIssue",
    "VersionResponse",
]
