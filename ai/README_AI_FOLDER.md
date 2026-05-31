# AI-модуль — SceduleApp

Модуль реалізує три AI-компоненти для покращення якості розкладу.

## Структура

```
ai/
├── scoring.py            ← оцінювання якості розкладу (0-100)
├── recommender.py        ← рекомендатор слотів (Mode 2): look-ahead + RF
├── or_tools_generator.py ← CP-SAT генератор оптимального розкладу (Mode 3)
├── extract_features.py   ← JSONL → CSV для навчання ML
├── train_rf.py           ← навчання Random Forest
└── models/
    └── recommender.pkl   ← збережена RF модель (з'являється після навчання)
```

---

## 1. Оцінювання розкладу — `scoring.py`

Функція `score_schedule(entries, ...)` повертає оцінку 0-100.

### Критерії

| Код | Тип | Опис | Вага |
|---|---|---|---|
| H1 | HARD | Група має дві пари одночасно | ×10 |
| H2 | HARD | Викладач має дві пари одночасно | ×10 |
| H3 | HARD | Група має лише 1 пару на день | ×5 |
| H4 | HARD | Вікно (вільна пара між заняттями) для групи | ×2 |
| S1 | SOFT | Більше 4 пар на день | ×1 |
| S3 | SOFT | Пари в середині тижня (вт/ср) | +бонус |
| S5 | SOFT | Важкі предмети (difficulty=3) на 2-3 пару | +бонус |

### Нормалізація

```
adjusted_score = raw_score / max_achievable × 100
```

`max_achievable` — аналітично розраховується для поточного навантаження (H1/H2/H3) або апроксимується одним запуском жадібного алгоритму (H4).

### Використання

```python
from ai.scoring import score_schedule

entries = [
    {'day': 'Понеділок', 'time': '9:00 - 10:30',
     'group_name': 'ІПЗ-41', 'teacher_id': 1, 'subject_id': 2},
    ...
]
result = score_schedule(entries, course_loads=loads, subjects={2: 3})
print(result['adjusted_score'])   # 72.5
print(result['breakdown'])        # {H1: {...}, H2: {...}, ...}
```

---

## 2. Рекомендатор слотів — `recommender.py`

Використовується в **Mode 2** (ручне розміщення): адмін вибирає навантаження, AI підсвічує 5 найкращих слотів у сітці 5×5.

### Два режими

#### Look-ahead (без моделі)

Для кожного з 25 слотів симулює розміщення пари та рахує `score_schedule()`. Ранжує за результатом. Не потребує навчання.

```
O(25 × score_schedule) ≈ кілька мілісекунд
```

#### Random Forest (після навчання)

Обчислює 9 ознак для кожного кандидата-слота та повертає `P(high_quality)` з моделі.

```
O(25 × feature_extraction) ≈ < 1 мс
```

Автоматично активується після того, як з'являється `ai/models/recommender.pkl`. Fallback на look-ahead якщо файлу немає.

### Ознаки для інференсу

| Ознака | Опис |
|---|---|
| `day_idx` | День тижня (0=Пн, 4=Пт) |
| `time_idx` | Номер пари (0-4) |
| `is_optimal_time` | 1 якщо пара 2 або 3 (10:45-14:00) |
| `subject_difficulty` | Складність предмету (1-3) |
| `group_pairs_today` | Кількість пар групи цього дня після розміщення |
| `teacher_pairs_today` | Кількість пар викладача цього дня |
| `group_window` | 1 якщо буде вікно у групи |
| `teacher_window` | 1 якщо буде вікно у викладача |
| `is_single_pair_day` | 1 якщо у групи буде лише 1 пара цього дня |

---

## 3. OR-Tools CP-SAT генератор — `or_tools_generator.py`

Реалізує **Mode 3**: повна автогенерація розкладу через constraint programming.

### Модель

**Змінні:** `x[session, day, time]` ∈ {0, 1}

**HARD обмеження:**
- Кожна сесія розміщена рівно в одному слоті (`AddExactlyOne`)
- Одна група не може мати дві пари одночасно (`AddAtMostOne`)
- Один викладач не може вести дві пари одночасно (`AddAtMostOne`)
- Максимум 4 пари на день для групи/викладача

**SOFT цільова функція (максимізувати):**

```
Σ  +10 × x[i,d,t]  якщо предмет важкий і t ∈ {1,2}   (S5)
  - 5 × is_single[g,d]                                  (H3)
  + 1 × x[i,d,t]   якщо d ∈ {Вт, Ср}                  (S3)
```

### Результати на production БД

| Метрика | Жадібний | OR-Tools |
|---|---|---|
| Оцінка | ~27/100 | ~92/100 |
| Час | < 1 с | 0.3-15 с |
| H3 порушень | ~8 | 0 |
| S5 бонусів | ~3 | макс можливе |

### Використання

```python
from ai.or_tools_generator import generate_schedule_or_tools

entries, status_msg, elapsed = generate_schedule_or_tools(
    course_loads=[{'group_name': 'ІПЗ-41', 'teacher_id': 1,
                   'subject_id': 2, 'required_sessions': 3}],
    classrooms=[{'id': 1, 'name': 'А-101', 'capacity': 30}],
    subjects_map={2: 3},   # subject_id → difficulty
    timeout=15,
)
# entries = [{'day': ..., 'time': ..., 'group_name': ..., ...}, ...]
```

---

## 4. Пайплайн ML-навчання

```
generate_dataset.py → data/schedules.jsonl
        ↓
extract_features.py → data/features.csv
        ↓
train_rf.py         → ai/models/recommender.pkl
```

### Крок 1 — Генерація датасету

```powershell
cd schedule_app
python generate_dataset.py          # 1000 запусків (за замовчуванням)
python generate_dataset.py --runs 5000   # більше даних
```

Генерує `data/schedules.jsonl`. Кожен рядок — один повний розклад з оцінкою та списком пар.

### Крок 2 — Витяг ознак

```powershell
python ai/extract_features.py
```

Перетворює JSONL → CSV. Кожна пара розкладу стає одним рядком (~59 рядків на запуск → ~59,000 рядків на 1000 запусків).

Мітка `label_high_quality = 1` якщо `run_score ≥ 40`.

### Крок 3 — Навчання

```powershell
python ai/train_rf.py
```

Або через веб-інтерфейс: **Адмін Панель → "🎓 Навчити RF модель"**.

Виводить:
```
Trained on 59,000 rows
  Accuracy : 0.891
  F1 score : 0.878
  Top feat : is_single_pair_day
Saved -> ai/models/recommender.pkl
```

Після цього Mode 2 автоматично використовує RF (badge "RF модель" в UI).

### Перенавчання

Перегенеруй датасет і натисни кнопку знову. Модель в пам'яті оновлюється автоматично (кеш перевіряє mtime файлу).

---

## Зв'язки між компонентами

```
app.py (Mode 2)
  └─ recommender.py
       ├─ [без моделі] → scoring.py   (look-ahead)
       └─ [є модель]   → recommender.pkl (RF predict_proba)

app.py (Mode 3)
  └─ or_tools_generator.py → [повертає entries]
       └─ scoring.py        (оцінка результату для flash)

generate_dataset.py
  └─ scoring.py             (оцінює кожен згенерований розклад)

train_rf.py
  └─ extract_features.py   (витягує ознаки)
  └─ scikit-learn RF        (навчання)
```
