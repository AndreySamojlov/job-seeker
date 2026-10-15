"""Validated selection and consistent repository snapshot."""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import re

MOSCOW = timezone(timedelta(hours=3))
SORT_KEYS = ('title', 'company', 'board_token', 'location', 'work_mode', 'discovered_at', 'availability', 'availability_checked_at', 'fit_score', 'fit_band', 'fit_score_version')


@dataclass(frozen=True)
class BoardFilters:
    candidate_id: str | None
    date_from: date
    date_to: date
    board: str | None = None
    availability: str | None = None

    def __post_init__(self):
        if self.candidate_id is not None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', self.candidate_id):
            raise ValueError('Invalid candidate')
        if self.date_from > self.date_to or self.date_to > datetime.now(MOSCOW).date():
            raise ValueError('Invalid discovery period')
        if self.availability not in (None, 'unknown'):
            raise ValueError('Unsupported availability')
        if self.board is not None and (not self.board or len(self.board) > 200):
            raise ValueError('Invalid board')


@dataclass(frozen=True)
class TablePage:
    page: int = 0
    sort_key: str = 'discovered_at'
    sort_direction: str = 'desc'

    def __post_init__(self):
        if type(self.page) is not int or not 0 <= self.page <= 21474836:
            raise ValueError('Invalid page')
        if self.sort_key not in SORT_KEYS or self.sort_direction not in ('asc', 'desc'):
            raise ValueError('Invalid sort')


@dataclass
class GreenhouseSnapshot:
    candidate_id: str | None = None
    candidates: list = field(default_factory=list)
    board_options: list = field(default_factory=list)
    total_rows: int = 0
    unknown_board: int = 0
    unscored: int = 0
    daily: list = field(default_factory=list)
    bands: list = field(default_factory=list)
    boards: list = field(default_factory=list)
    points: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
