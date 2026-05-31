# TAG v1.0: Schedule scoring module
# Scores a generated schedule 0-100 based on Ukrainian MoH standards and university practice.
# See docs/decisions/ADR-001-ai-module.md for full criteria specification.

from collections import defaultdict

DAYS = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', "П'ятниця"]
TIMES = ['9:00 - 10:30', '10:45 - 12:15', '12:30 - 14:00', '14:15 - 15:45', '16:00 - 17:30']

TIME_INDEX = {t: i for i, t in enumerate(TIMES)}
OPTIMAL_TIMES = {'10:45 - 12:15', '12:30 - 14:00'}  # пари 2 і 3 — оптимальні для важких предметів
MAX_PAIRS_PER_DAY = 4

# Penalty weights — calibrated for realistic schedules with ~50-60 pairs across 5 groups.
# Original ×10 for all HARD constraints caused all raw_scores = 0 in practice
# (H4 alone: 8-20 windows × 10 = 80-200 pts per run).
HARD_PENALTY = 10   # H1, H2: true overflow — must never happen
H3_PENALTY = 5      # single-pair day: bad but more common than H1/H2
H4_PENALTY = 2      # group windows: undesirable but frequent in greedy output
S1_WEIGHT = 1       # teacher windows: was ×2, reduced — accumulates quickly with many teachers
S5_WEIGHT = 0.5     # hard-subject placement: was ×1, reduced — ~30 hard sessions per dataset


def score_schedule(entries, course_loads=None, greedy_window_count=None, subjects=None):
    """
    Score a schedule and return an adjusted score from 0 to 100.

    Args:
        entries: list of Schedule ORM objects or dicts with keys
                 {day, time, group_name, teacher_id, subject_id}
        subjects: dict {subject_id: difficulty} or None. Used for S5 criterion.
                  Build it as: {s.id: s.difficulty for s in Subject.query.all()}
        course_loads: list of CourseLoad ORM objects or None.
                      Used to calculate the theoretical best score (max_achievable).
        greedy_window_count: int or None. Number of group windows found in a single
                             greedy run — used as the H4 normalization baseline.

    Returns:
        dict with keys:
            adjusted_score  — normalized score 0-100 (primary metric)
            raw_score       — raw score before normalization
            max_achievable  — best possible raw score given the data
            breakdown       — per-criterion violation counts and penalties
    """
    rows = [_to_dict(e) for e in entries]
    penalties = 0
    breakdown = {}

    # --- Tier 1: HARD constraints (penalty x10 each) ---

    # H1: group has more than 4 pairs in a day
    h1 = _over_limit_violations(rows, 'group_name')
    penalties += h1 * HARD_PENALTY
    breakdown['H1_group_overflow'] = {'violations': h1, 'penalty': h1 * HARD_PENALTY}

    # H2: teacher has more than 4 pairs in a day
    h2 = _over_limit_violations(rows, 'teacher_id')
    penalties += h2 * HARD_PENALTY
    breakdown['H2_teacher_overflow'] = {'violations': h2, 'penalty': h2 * HARD_PENALTY}

    # H3: group has exactly 1 pair on a day (0 is fine = day off, 2+ is fine)
    h3 = _single_pair_day_violations(rows)
    penalties += h3 * H3_PENALTY
    breakdown['H3_single_pair_day'] = {'violations': h3, 'penalty': h3 * H3_PENALTY}

    # H4: gaps (windows) between pairs within a day for a group
    h4 = _window_violations(rows, 'group_name')
    penalties += h4 * H4_PENALTY
    breakdown['H4_group_windows'] = {'violations': h4, 'penalty': h4 * H4_PENALTY}

    # --- Tier 2: SOFT constraints ---

    # S1: gaps between pairs within a day for a teacher
    s1 = _window_violations(rows, 'teacher_id')
    penalties += s1 * S1_WEIGHT
    breakdown['S1_teacher_windows'] = {'violations': s1, 'penalty': s1 * S1_WEIGHT}

    # S3: weekly load distribution — Tue/Wed should carry more pairs than Mon/Fri (weight x1)
    s3 = _weekly_distribution_penalty(rows)
    penalties += s3
    breakdown['S3_weekly_distribution'] = {'penalty': s3}

    # S4: uneven daily load per group — penalise large spread between busiest and lightest day (weight x1)
    s4 = _uneven_load_penalty(rows)
    penalties += s4
    breakdown['S4_uneven_load'] = {'penalty': s4}

    # S5: hard subjects (difficulty=3) not placed at optimal pairs 2-3
    s5 = _difficulty_placement_penalty(rows, subjects)
    s5_penalty = round(s5 * S5_WEIGHT, 1)
    penalties += s5_penalty
    breakdown['S5_difficulty_placement'] = {'violations': s5, 'penalty': s5_penalty}

    raw_score = max(0, 100 - penalties)
    max_achievable = _max_achievable(course_loads, greedy_window_count)
    adjusted_score = min(100.0, round(raw_score / max_achievable * 100, 1))

    return {
        'adjusted_score': adjusted_score,
        'raw_score': raw_score,
        'max_achievable': max_achievable,
        'breakdown': breakdown,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_dict(entry):
    if isinstance(entry, dict):
        return entry
    return {
        'day': entry.day,
        'time': entry.time,
        'group_name': entry.group_name,
        'teacher_id': entry.teacher_id,
        'subject_id': entry.subject_id,
    }


def _over_limit_violations(rows, key):
    """Count pair-instances that exceed MAX_PAIRS_PER_DAY for a given grouping key."""
    counts = defaultdict(lambda: defaultdict(int))
    for r in rows:
        counts[r[key]][r['day']] += 1
    violations = 0
    for entity_days in counts.values():
        for count in entity_days.values():
            if count > MAX_PAIRS_PER_DAY:
                violations += count - MAX_PAIRS_PER_DAY
    return violations


def _single_pair_day_violations(rows):
    """Count days where a group has exactly 1 pair (worse than a day off)."""
    counts = defaultdict(lambda: defaultdict(int))
    for r in rows:
        counts[r['group_name']][r['day']] += 1
    violations = 0
    for group_days in counts.values():
        for count in group_days.values():
            if count == 1:
                violations += 1
    return violations


def _window_violations(rows, key):
    """
    Count missing time slots between scheduled pairs in a day (windows/gaps).
    A gap of 2 slots (e.g. pairs 1 and 3 missing pair 2) counts as 1 window.
    """
    slots = defaultdict(lambda: defaultdict(list))
    for r in rows:
        time_idx = TIME_INDEX.get(r['time'], 0)
        slots[r[key]][r['day']].append(time_idx)
    violations = 0
    for entity_days in slots.values():
        for day_slots in entity_days.values():
            sorted_slots = sorted(set(day_slots))
            for i in range(len(sorted_slots) - 1):
                if sorted_slots[i + 1] - sorted_slots[i] > 1:
                    violations += 1
    return violations


def _weekly_distribution_penalty(rows):
    """Penalise when Mon+Fri carry more total pairs than Tue+Wed."""
    day_counts = defaultdict(int)
    for r in rows:
        day_counts[r['day']] += 1
    mid_week = day_counts.get('Вівторок', 0) + day_counts.get('Середа', 0)
    edges = day_counts.get('Понеділок', 0) + day_counts.get("П'ятниця", 0)
    return max(0, edges - mid_week)


def _uneven_load_penalty(rows):
    """Penalise groups whose busiest day has 2+ more pairs than their lightest day."""
    counts = defaultdict(lambda: defaultdict(int))
    for r in rows:
        counts[r['group_name']][r['day']] += 1
    penalty = 0
    for group_days in counts.values():
        values = list(group_days.values())
        if len(values) > 1:
            spread = max(values) - min(values)
            if spread > 1:
                penalty += spread - 1
    return penalty


def _difficulty_placement_penalty(rows, subjects):
    """Penalise hard subjects (difficulty=3) not placed at optimal pairs 2-3."""
    if not subjects:
        return 0
    penalty = 0
    for r in rows:
        sid = r.get('subject_id')
        diff = subjects.get(sid) if sid else None
        if diff is not None and diff >= 3 and r['time'] not in OPTIMAL_TIMES:
            penalty += 1
    return penalty


def _max_achievable(course_loads, greedy_window_count):
    """
    Calculate the best raw_score achievable given the input data.

    H1, H2, H3 — computed analytically from course_loads.
    H4          — approximated by greedy_window_count (one greedy run).
    Soft criteria — assumed 0 forced penalties (always avoidable in theory).
    """
    if course_loads is None:
        return 100

    forced_penalties = 0
    group_totals = defaultdict(int)
    teacher_totals = defaultdict(int)

    for cl in course_loads:
        if isinstance(cl, dict):
            gname = cl['group_name']
            tid = cl['teacher_id']
            sessions = cl['required_sessions']
        else:
            gname = cl.group.name
            tid = cl.teacher_id
            sessions = cl.required_sessions

        group_totals[gname] += sessions
        teacher_totals[tid] += sessions

    for total in group_totals.values():
        # H1: pairs that physically cannot fit within 4/day × 5 days
        forced_penalties += max(0, total - MAX_PAIRS_PER_DAY * len(DAYS)) * HARD_PENALTY
        # H3: a single total pair can never be placed without a single-pair-day violation
        if total == 1:
            forced_penalties += H3_PENALTY

    for total in teacher_totals.values():
        # H2: same overflow logic for teachers
        forced_penalties += max(0, total - MAX_PAIRS_PER_DAY * len(DAYS)) * HARD_PENALTY

    # H4: windows that the greedy algorithm could not avoid
    if greedy_window_count is not None:
        forced_penalties += greedy_window_count * H4_PENALTY

    return max(1, 100 - forced_penalties)
