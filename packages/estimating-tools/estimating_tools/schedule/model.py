"""CanonicalSchedule moved to bimforge (issue #335): bimforge owns 4D in both
directions — `schedule4d.embed_schedule` writes it into an IFC and
`schedule_read.read_schedule` reads it back. This module re-exports the model
so existing `estimating_tools.schedule.model` imports keep working.
"""
from bimforge.bim.schedule_model import (  # noqa: F401
    DEP_TYPES, Calendar, CanonicalSchedule, Dependency, MapReport,
    ScheduleTask, _d, parse_month_day, resolve_bid_item_codes,
)
