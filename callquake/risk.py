"""Risk scoring: call-graph breadth (0-50) + git-history heat (0-50).

Formula (deterministic, integer arithmetic only):

    breadth_points = min(50, 5 * n_callsites)
    churn_points   = min(30, 3 * n_commits_180d)
    fix_points     = round_half_up(20 * fix_ratio)      # ratio in [0, 1]
    total          = min(100, breadth + churn + fix)

Totals <= ``LOW_RISK_THRESHOLD`` are considered safe to change; anything above
triggers the "add tests first" advice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

BREADTH_POINTS_PER_CALLSITE = 5
BREADTH_CAP = 50
CHURN_POINTS_PER_COMMIT = 3
CHURN_CAP = 30
FIX_RATIO_POINTS = 20  # points awarded at fix_ratio == 1.0
TOTAL_CAP = 100

#: Totals at or below this are announced as low risk.
LOW_RISK_THRESHOLD = 29


@dataclass(frozen=True)
class RiskScore:
    """Score breakdown for one function name."""

    total: int
    breadth_points: int
    churn_points: int
    fix_points: int
    callsites: int
    commits_180d: int
    fix_commits_180d: int
    fix_ratio_pct: int

    @property
    def history_points(self) -> int:
        """The combined history-heat component (churn + fix), capped at 50."""
        return min(50, self.churn_points + self.fix_points)

    @property
    def advice(self) -> str:
        if self.total <= LOW_RISK_THRESHOLD:
            return "低风险，放心改"
        return (
            f"有 {self.callsites} 个调用方 + {self.fix_commits_180d} 次 fix 历史，"
            f"建议补测试再动"
        )


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def score_function(callsites: int, commits_180d: int, fix_commits_180d: int) -> RiskScore:
    """Compute the deterministic 0-100 risk score from raw counters."""
    callsites = max(0, callsites)
    commits = max(0, commits_180d)
    fixes = min(max(0, fix_commits_180d), commits)
    ratio = fixes / commits if commits else 0.0

    breadth = min(BREADTH_CAP, BREADTH_POINTS_PER_CALLSITE * callsites)
    churn = min(CHURN_CAP, CHURN_POINTS_PER_COMMIT * commits)
    fix_pts = _round_half_up(FIX_RATIO_POINTS * ratio)
    total = min(TOTAL_CAP, breadth + churn + fix_pts)
    return RiskScore(
        total=total,
        breadth_points=breadth,
        churn_points=churn,
        fix_points=fix_pts,
        callsites=callsites,
        commits_180d=commits,
        fix_commits_180d=fixes,
        fix_ratio_pct=_round_half_up(ratio * 100),
    )
