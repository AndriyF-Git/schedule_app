"""
Unit tests for the AI module (schedule_app/ai/).

Tests are isolated — no Flask app context required.
Covers:
  - scoring.py  : score_schedule(), criteria H1-H4, S5
  - recommender : recommend_slots(), recommend_slots_ml() fallback
  - or_tools_generator: generate_schedule_or_tools() with minimal data
  - train_rf    : train() with a temp CSV
"""
import pytest
from ai.scoring import score_schedule
from ai.recommender import recommend_slots, recommend_slots_ml, _has_conflict
from ai.or_tools_generator import generate_schedule_or_tools

# ---------------------------------------------------------------------------
# Helpers — minimal schedule entries
# ---------------------------------------------------------------------------

DAYS  = ['Понеділок', 'Вівторок', 'Середа', 'Четвер', "П'ятниця"]
TIMES = ['9:00 - 10:30', '10:45 - 12:15', '12:30 - 14:00', '14:15 - 15:45', '16:00 - 17:30']

LOAD_1 = {'group_name': 'G1', 'teacher_id': 1, 'subject_id': 1, 'required_sessions': 2}


def _entry(day, time, group='G1', teacher=1, subject=1):
    return {'day': day, 'time': time,
            'group_name': group, 'teacher_id': teacher, 'subject_id': subject}


# ---------------------------------------------------------------------------
# score_schedule — basic structure
# ---------------------------------------------------------------------------

def test_score_returns_required_keys():
    result = score_schedule([], course_loads=[], subjects={})
    assert 'adjusted_score' in result
    assert 'raw_score'       in result
    assert 'max_achievable'  in result
    assert 'breakdown'       in result


def test_score_empty_schedule_no_violations():
    result = score_schedule([], course_loads=[LOAD_1], subjects={1: 2})
    for key in ('H1_group_overflow', 'H2_teacher_overflow',
                'H3_single_pair_day', 'H4_group_windows'):
        assert result['breakdown'][key]['violations'] == 0


def test_score_range():
    entries = [
        _entry('Понеділок', '9:00 - 10:30'),
        _entry('Понеділок', '10:45 - 12:15'),
    ]
    result = score_schedule(entries, course_loads=[LOAD_1], subjects={1: 2})
    assert 0 <= result['adjusted_score'] <= 100


# ---------------------------------------------------------------------------
# H1 — group exceeds 4 pairs per day
# ---------------------------------------------------------------------------

def test_h1_detected_group_over_4_pairs():
    # 5 entries for same group on same day → 1 violation (5 - 4 = 1)
    loads = [{'group_name': 'G1', 'teacher_id': i + 1, 'subject_id': 1,
              'required_sessions': 1} for i in range(5)]
    entries = [_entry('Понеділок', TIMES[i], group='G1', teacher=i + 1)
               for i in range(5)]
    result = score_schedule(entries, course_loads=loads, subjects={1: 2})
    assert result['breakdown']['H1_group_overflow']['violations'] > 0


def test_h1_no_violation_within_daily_limit():
    entries = [
        _entry('Понеділок', '9:00 - 10:30',  group='G1', teacher=1),
        _entry('Понеділок', '10:45 - 12:15', group='G1', teacher=1),
    ]
    result = score_schedule(entries, course_loads=[LOAD_1], subjects={1: 2})
    assert result['breakdown']['H1_group_overflow']['violations'] == 0


# ---------------------------------------------------------------------------
# H2 — teacher exceeds 4 pairs per day
# ---------------------------------------------------------------------------

def test_h2_detected_teacher_over_4_pairs():
    # Same teacher, 5 groups on same day → 1 violation
    loads = [{'group_name': f'G{i}', 'teacher_id': 1, 'subject_id': 1,
              'required_sessions': 1} for i in range(5)]
    entries = [_entry('Середа', TIMES[i], group=f'G{i}', teacher=1)
               for i in range(5)]
    result = score_schedule(entries, course_loads=loads, subjects={1: 2})
    assert result['breakdown']['H2_teacher_overflow']['violations'] > 0


def test_h2_no_violation_within_daily_limit():
    entries = [
        _entry('Вівторок', '9:00 - 10:30',  group='G1', teacher=1),
        _entry('Вівторок', '10:45 - 12:15', group='G2', teacher=1),
    ]
    loads = [LOAD_1, {'group_name': 'G2', 'teacher_id': 1,
                      'subject_id': 1, 'required_sessions': 1}]
    result = score_schedule(entries, course_loads=loads, subjects={1: 2})
    assert result['breakdown']['H2_teacher_overflow']['violations'] == 0


# ---------------------------------------------------------------------------
# H3 — single pair per day for a group
# ---------------------------------------------------------------------------

def test_h3_detected_one_pair_on_day():
    entries = [_entry('Четвер', '9:00 - 10:30')]
    result = score_schedule(entries, course_loads=[LOAD_1], subjects={1: 2})
    assert result['breakdown']['H3_single_pair_day']['violations'] > 0


def test_h3_no_violation_two_pairs_on_day():
    entries = [
        _entry('Четвер', '9:00 - 10:30'),
        _entry('Четвер', '10:45 - 12:15'),
    ]
    result = score_schedule(entries, course_loads=[LOAD_1], subjects={1: 2})
    assert result['breakdown']['H3_single_pair_day']['violations'] == 0


# ---------------------------------------------------------------------------
# S5 — hard subject at optimal / non-optimal time
# ---------------------------------------------------------------------------

def test_s5_no_violation_hard_subject_at_optimal_time():
    # '10:45 - 12:15' is optimal → no S5 penalty
    entries = [_entry('Середа', '10:45 - 12:15', subject=1)]
    result = score_schedule(entries, course_loads=[LOAD_1], subjects={1: 3})
    assert result['breakdown']['S5_difficulty_placement']['violations'] == 0


def test_s5_violation_hard_subject_at_bad_time():
    # '9:00 - 10:30' is NOT optimal → S5 penalty
    entries = [_entry('Понеділок', '9:00 - 10:30', subject=1)]
    result = score_schedule(entries, course_loads=[LOAD_1], subjects={1: 3})
    assert result['breakdown']['S5_difficulty_placement']['violations'] > 0


def test_s5_no_violation_easy_subject_any_time():
    # difficulty=1 → S5 never fires regardless of time slot
    entries = [_entry('Понеділок', '9:00 - 10:30', subject=1)]
    result = score_schedule(entries, course_loads=[LOAD_1], subjects={1: 1})
    assert result['breakdown']['S5_difficulty_placement']['violations'] == 0


# ---------------------------------------------------------------------------
# recommend_slots — look-ahead
# ---------------------------------------------------------------------------

def test_recommend_slots_returns_top_n():
    recs = recommend_slots('G1', 1, 1, [], course_loads=[LOAD_1], subjects={1: 2}, top_n=3)
    assert len(recs) == 3


def test_recommend_slots_has_required_keys():
    recs = recommend_slots('G1', 1, 1, [], course_loads=[LOAD_1], subjects={1: 2})
    for r in recs:
        assert 'day' in r and 'time' in r and 'score' in r and 'delta' in r


def test_recommend_slots_sorted_descending():
    recs = recommend_slots('G1', 1, 1, [], course_loads=[LOAD_1], subjects={1: 2}, top_n=25)
    scores = [r['score'] for r in recs]
    assert scores == sorted(scores, reverse=True)


def test_recommend_slots_excludes_conflicts():
    occupied = [_entry('Понеділок', '9:00 - 10:30', group='G1', teacher=1)]
    recs = recommend_slots('G1', 1, 1, occupied, course_loads=[LOAD_1], subjects={1: 2}, top_n=25)
    for r in recs:
        assert not (r['day'] == 'Понеділок' and r['time'] == '9:00 - 10:30')


def test_recommend_slots_excludes_classroom_conflict():
    occupied = [{'day': 'Середа', 'time': '12:30 - 14:00',
                 'group_name': 'G2', 'teacher_id': 2, 'subject_id': 1,
                 'classroom': 'А-101'}]
    recs = recommend_slots('G1', 1, 1, occupied,
                           course_loads=[LOAD_1], subjects={1: 2},
                           classroom='А-101', top_n=25)
    for r in recs:
        assert not (r['day'] == 'Середа' and r['time'] == '12:30 - 14:00')


# ---------------------------------------------------------------------------
# recommend_slots_ml — fallback when no model file
# ---------------------------------------------------------------------------

def test_recommend_slots_ml_fallback_no_model(monkeypatch, tmp_path):
    """Without recommender.pkl it should fall back to look-ahead."""
    import ai.recommender as rec_module
    monkeypatch.setattr(rec_module, 'MODEL_PATH', str(tmp_path / 'nonexistent.pkl'))
    monkeypatch.setattr(rec_module, '_model_cache', None)
    monkeypatch.setattr(rec_module, '_model_mtime', None)

    recs = recommend_slots_ml('G1', 1, 1, [], course_loads=[LOAD_1], subjects={1: 2}, top_n=3)
    assert len(recs) == 3
    assert all(r.get('mode') == 'lookahead' for r in recs)


# ---------------------------------------------------------------------------
# _has_conflict helper
# ---------------------------------------------------------------------------

def test_has_conflict_same_group():
    entries = [_entry('Понеділок', '9:00 - 10:30', group='G1', teacher=1)]
    assert _has_conflict('Понеділок', '9:00 - 10:30', 'G1', 99, None, entries)


def test_has_conflict_same_teacher():
    entries = [_entry('Понеділок', '9:00 - 10:30', group='G2', teacher=1)]
    assert _has_conflict('Понеділок', '9:00 - 10:30', 'G1', 1, None, entries)


def test_no_conflict_different_slot():
    entries = [_entry('Понеділок', '9:00 - 10:30', group='G1', teacher=1)]
    assert not _has_conflict('Вівторок', '9:00 - 10:30', 'G1', 1, None, entries)


# ---------------------------------------------------------------------------
# or_tools_generator — minimal solve
# ---------------------------------------------------------------------------

def test_ortools_places_single_session():
    loads = [{'group_name': 'G1', 'teacher_id': 1, 'subject_id': 1, 'required_sessions': 1}]
    rooms = [{'id': 1, 'name': 'А-101', 'capacity': 30}]
    entries, msg, elapsed = generate_schedule_or_tools(loads, rooms, {1: 2}, timeout=10)
    assert len(entries) == 1
    assert entries[0]['group_name'] == 'G1'


def test_ortools_no_group_teacher_overlap():
    loads = [
        {'group_name': 'G1', 'teacher_id': 1, 'subject_id': 1, 'required_sessions': 2},
        {'group_name': 'G2', 'teacher_id': 2, 'subject_id': 1, 'required_sessions': 2},
    ]
    rooms = [{'id': 1, 'name': 'А-101', 'capacity': 30}]
    entries, _, _ = generate_schedule_or_tools(loads, rooms, {1: 2}, timeout=10)

    # No two entries for same group or same teacher at same (day, time)
    slots_by_group   = {}
    slots_by_teacher = {}
    for e in entries:
        slot = (e['day'], e['time'])
        assert slot not in slots_by_group.get(e['group_name'], set()), \
            f"Group {e['group_name']} overlap at {slot}"
        assert slot not in slots_by_teacher.get(e['teacher_id'], set()), \
            f"Teacher {e['teacher_id']} overlap at {slot}"
        slots_by_group.setdefault(e['group_name'], set()).add(slot)
        slots_by_teacher.setdefault(e['teacher_id'], set()).add(slot)


def test_ortools_empty_loads_returns_empty():
    entries, msg, _ = generate_schedule_or_tools([], [], {}, timeout=5)
    assert entries == []


def test_ortools_returns_expected_keys():
    loads = [{'group_name': 'G1', 'teacher_id': 1, 'subject_id': 1, 'required_sessions': 1}]
    rooms = [{'id': 1, 'name': 'А-101', 'capacity': 30}]
    entries, _, _ = generate_schedule_or_tools(loads, rooms, {1: 2}, timeout=10)
    required = {'day', 'time', 'group_name', 'subject_id', 'teacher_id', 'classroom'}
    for e in entries:
        assert required.issubset(e.keys())


# ---------------------------------------------------------------------------
# train_rf — unit test (no real data needed)
# ---------------------------------------------------------------------------

def test_train_raises_on_missing_csv(tmp_path):
    from ai.train_rf import train
    with pytest.raises(FileNotFoundError):
        train(csv_path=tmp_path / 'nonexistent.csv',
              model_path=tmp_path / 'model.pkl')


def test_train_produces_pkl(tmp_path):
    """Build a minimal CSV, train, verify .pkl is written."""
    import csv, os
    import pandas as pd

    csv_path   = tmp_path / 'features.csv'
    model_path = tmp_path / 'model.pkl'

    cols = ['day_idx','time_idx','is_optimal_time','subject_difficulty',
            'group_pairs_today','teacher_pairs_today',
            'group_window','teacher_window','is_single_pair_day','label_high_quality']

    # 60 rows — two classes
    rows = []
    for i in range(60):
        rows.append({
            'day_idx': i % 5, 'time_idx': i % 5, 'is_optimal_time': i % 2,
            'subject_difficulty': (i % 3) + 1,
            'group_pairs_today': (i % 4) + 1, 'teacher_pairs_today': (i % 4) + 1,
            'group_window': i % 2, 'teacher_window': i % 2,
            'is_single_pair_day': i % 2,
            'label_high_quality': int(i >= 30),
        })

    pd.DataFrame(rows).to_csv(csv_path, index=False)

    from ai.train_rf import train
    metrics = train(csv_path=csv_path, model_path=model_path, n_estimators=10)

    assert model_path.exists()
    assert 0 <= metrics['accuracy'] <= 1
    assert 'top_feature' in metrics
