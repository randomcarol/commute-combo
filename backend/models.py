from dataclasses import dataclass, field


@dataclass(slots=True)
class RouteSegment:
    mode: str
    duration_min: int
    from_name: str = ""
    to_name: str = ""


@dataclass(slots=True)
class CommutePlan:
    provider: str
    template: str
    segments: list[RouteSegment]
    meta: dict = field(default_factory=dict)

