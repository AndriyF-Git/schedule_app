"""
AI schedule generator using Google OR-Tools CP-SAT.

Replaces the greedy random shuffle with constraint programming:
  - HARD constraints: no teacher/group overlap, max 4 pairs/day
  - SOFT objective: minimize H3 violations + maximize S5 placement
    (hard subjects at optimal times 10:45-14:00)

Returns the best schedule found within the timeout.
"""
import time
from collections import defaultdict
from ortools.sat.python import cp_model

DAYS  = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', "П'ятниця"]
TIMES = ['9:00 - 10:30', '10:45 - 12:15', '12:30 - 14:00', '14:15 - 15:45', '16:00 - 17:30']
OPTIMAL_TIME_IDX = {1, 2}   # 10:45-12:15 and 12:30-14:00 (pairs 2 and 3)
ND, NT = len(DAYS), len(TIMES)

# Objective weights — mirror scoring.py so OR-Tools optimizes for the same metric
W_S5 = 10   # reward hard subject at optimal time
W_H3 = 5    # penalty for single-pair day (must match H3_PENALTY in scoring.py)
W_S3 = 1    # reward sessions on Tue/Wed (mid-week preference)


def generate_schedule_or_tools(course_loads, classrooms, subjects_map, timeout=15):
    """
    Build and solve a CP-SAT model for the schedule.

    Args:
        course_loads: list of dicts with keys:
                      {group_name, teacher_id, subject_id, required_sessions}
        classrooms:   list of dicts with keys: {id, name, capacity}
        subjects_map: dict {subject_id: difficulty}
        timeout:      solver time limit in seconds

    Returns:
        (entries, status_msg, elapsed_seconds)
        entries — list of dicts {day, time, group_name, subject_id, teacher_id, classroom}
                  Empty list if no feasible solution was found.
    """
    t0 = time.time()
    model = cp_model.CpModel()

    # Normalise input — accept both dicts and ORM objects
    def _cl(obj):
        if isinstance(obj, dict):
            return obj
        return {
            'group_name':        obj.group.name,
            'teacher_id':        obj.teacher_id,
            'subject_id':        obj.subject_id,
            'required_sessions': obj.required_sessions,
        }

    def _room(obj):
        if isinstance(obj, dict):
            return obj
        return {'id': obj.id, 'name': obj.name, 'capacity': obj.capacity}

    loads     = [_cl(cl)   for cl in course_loads]
    room_list = [_room(r)  for r  in classrooms]

    # Flatten all required sessions into a flat list
    # e.g. load with required_sessions=3 → 3 entries in the list
    sessions = []
    for cl in loads:
        for _ in range(cl['required_sessions']):
            sessions.append(cl)
    N = len(sessions)

    if N == 0:
        return [], 'Немає навантаження для генерації', 0.0

    # -----------------------------------------------------------------------
    # Decision variables: x[session_idx, day, time] = 1 if placed there
    # -----------------------------------------------------------------------
    x = {}
    for i in range(N):
        for d in range(ND):
            for t in range(NT):
                x[i, d, t] = model.NewBoolVar(f'x_{i}_{d}_{t}')

    # -----------------------------------------------------------------------
    # HARD constraints
    # -----------------------------------------------------------------------

    # Each session must be assigned to exactly one slot
    for i in range(N):
        model.AddExactlyOne(x[i, d, t] for d in range(ND) for t in range(NT))

    # Build lookup: group_name → session indices, teacher_id → session indices
    by_group   = defaultdict(list)
    by_teacher = defaultdict(list)
    for i, cl in enumerate(sessions):
        by_group[cl['group_name']].append(i)
        by_teacher[cl['teacher_id']].append(i)

    # H1 equivalent: same group cannot have two sessions at the same (day, time)
    for sess_ids in by_group.values():
        for d in range(ND):
            for t in range(NT):
                model.AddAtMostOne(x[i, d, t] for i in sess_ids)

    # H2 equivalent: same teacher cannot have two sessions at the same (day, time)
    for sess_ids in by_teacher.values():
        for d in range(ND):
            for t in range(NT):
                model.AddAtMostOne(x[i, d, t] for i in sess_ids)

    # H1/H2 daily cap: max 4 sessions per (group, day) and (teacher, day)
    for sess_ids in by_group.values():
        for d in range(ND):
            model.Add(
                cp_model.LinearExpr.Sum([x[i, d, t] for i in sess_ids for t in range(NT)]) <= 4
            )
    for sess_ids in by_teacher.values():
        for d in range(ND):
            model.Add(
                cp_model.LinearExpr.Sum([x[i, d, t] for i in sess_ids for t in range(NT)]) <= 4
            )

    # -----------------------------------------------------------------------
    # SOFT objective
    # -----------------------------------------------------------------------
    obj = []

    # S5: reward hard subjects (difficulty ≥ 3) placed at optimal pairs (2–3)
    for i, cl in enumerate(sessions):
        if subjects_map.get(cl['subject_id'], 2) >= 3:
            for d in range(ND):
                for t in OPTIMAL_TIME_IDX:
                    obj.append(x[i, d, t] * W_S5)

    # H3: penalize single-pair days per group
    # is_single[g][d] = 1 iff exactly 1 session for group g on day d
    for gi, (gname, sess_ids) in enumerate(by_group.items()):
        for d in range(ND):
            day_count = model.NewIntVar(0, len(sess_ids), f'dc_{gi}_{d}')
            model.Add(
                day_count == cp_model.LinearExpr.Sum(
                    [x[i, d, t] for i in sess_ids for t in range(NT)]
                )
            )

            # at_least_two: day_count >= 2
            at_least_two = model.NewBoolVar(f'alt2_{gi}_{d}')
            model.Add(day_count >= 2).OnlyEnforceIf(at_least_two)
            model.Add(day_count <= 1).OnlyEnforceIf(at_least_two.Not())

            # is_active: day_count >= 1
            is_active = model.NewBoolVar(f'act_{gi}_{d}')
            model.Add(day_count >= 1).OnlyEnforceIf(is_active)
            model.Add(day_count == 0).OnlyEnforceIf(is_active.Not())

            # is_single = is_active AND NOT at_least_two (day_count == 1)
            is_single = model.NewBoolVar(f'h3_{gi}_{d}')
            model.AddBoolAnd([is_active, at_least_two.Not()]).OnlyEnforceIf(is_single)
            model.AddBoolOr([is_active.Not(), at_least_two]).OnlyEnforceIf(is_single.Not())

            obj.append(-W_H3 * is_single)

    # S3: small reward for sessions on Tue (1) and Wed (2)
    for i in range(N):
        for d in [1, 2]:
            for t in range(NT):
                obj.append(x[i, d, t] * W_S3)

    model.Maximize(cp_model.LinearExpr.Sum(obj))

    # -----------------------------------------------------------------------
    # Solve
    # -----------------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(timeout)
    solver.parameters.num_search_workers = 1   # 1 worker — надійно на будь-якій ОС
    status = solver.Solve(model)

    elapsed = round(time.time() - t0, 1)

    STATUS_MSG = {
        cp_model.OPTIMAL:    f'Оптимальний розклад ({elapsed}с)',
        cp_model.FEASIBLE:   f'Найкращий за {timeout}с ({elapsed}с)',
        cp_model.INFEASIBLE: 'Неможливо — перевірте навантаження та ресурси',
        cp_model.UNKNOWN:    'Час вичерпано, результат не знайдено',
    }

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [], STATUS_MSG.get(status, 'Помилка'), elapsed

    # -----------------------------------------------------------------------
    # Extract solution + assign classrooms greedily
    # -----------------------------------------------------------------------
    slot_used_rooms = defaultdict(list)   # (d, t) → [room_id, ...]

    entries = []
    for i, cl in enumerate(sessions):
        for d in range(ND):
            for t in range(NT):
                if solver.Value(x[i, d, t]):
                    used = slot_used_rooms[(d, t)]
                    room = next(
                        (r for r in room_list if r['id'] not in used),
                        room_list[0],
                    )
                    slot_used_rooms[(d, t)].append(room['id'])
                    entries.append({
                        'day':        DAYS[d],
                        'time':       TIMES[t],
                        'group_name': cl['group_name'],
                        'subject_id': cl['subject_id'],
                        'teacher_id': cl['teacher_id'],
                        'classroom':  room['name'],
                    })

    return entries, STATUS_MSG[status], elapsed
