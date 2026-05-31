# SceduleApp — Система розкладу занять

Веб-застосунок для управління університетським розкладом. Адміністратори керують ресурсами та генерують розклад; студенти переглядають його з фільтрами.

## Стек

| Шар | Технологія |
|---|---|
| Backend | Python 3.11 + Flask |
| ORM | Flask-SQLAlchemy + Flask-Migrate |
| База даних | SQLite |
| Frontend | Jinja2 + Vanilla JS + CSS |
| AI | OR-Tools CP-SAT + scikit-learn Random Forest |
| Логування | python-json-logger → ELK (Docker) |
| Тести | pytest |
| CI/CD | GitHub Actions |
| Контейнеризація | Docker + Docker Compose |

## Структура проєкту

```
SceduleApp/
├── README.md
├── db/                          ← SQL-скрипти (довідник / міграції)
│   ├── create_tables.sql
│   └── insert_test_data.sql
└── schedule_app/                ← Flask-застосунок
    ├── app.py                   ← моделі, маршрути, бізнес-логіка
    ├── requirements.txt
    ├── conftest.py
    ├── seed_data.py             ← заповнення test.db тестовими даними
    ├── generate_dataset.py      ← генерація JSONL-датасету для ML
    ├── Dockerfile
    ├── docker-compose.yml       ← Flask + Elasticsearch + Logstash + Kibana
    ├── .env.example
    ├── ai/                      ← AI-модуль (детальніше: ai/README.md)
    │   ├── scoring.py
    │   ├── recommender.py
    │   ├── or_tools_generator.py
    │   ├── extract_features.py
    │   ├── train_rf.py
    │   └── models/              ← збережені .pkl файли моделей
    ├── static/
    │   ├── css/style.css
    │   └── js/script.js
    ├── templates/
    │   ├── base.html
    │   ├── admin/
    │   └── student/
    ├── tests/test_app.py
    ├── data/                    ← ML-датасет (не в git)
    │   ├── schedules.jsonl
    │   └── features.csv
    └── instance/
        └── schedule.db          ← робоча БД (не в git)
```

## Моделі БД

| Модель | Призначення |
|---|---|
| `Subject` | Дисципліна (назва, складність 1-3) |
| `Teacher` | Викладач |
| `Group` | Студентська група |
| `Classroom` | Аудиторія з місткістю |
| `CourseLoad` | Зв'язок: яка група, який предмет, який викладач, скільки пар |
| `Schedule` | Запис розкладу: день, час, аудиторія, група, предмет, викладач |

## Режими генерації розкладу

| Режим | Опис | Маршрут |
|---|---|---|
| Жадібний | Випадкове перемішування слотів, перший вільний | `POST /admin/generate` |
| Mode 2 — Ручне + AI | Адмін вибирає слот, AI підказує найкращі | `GET /admin/schedule/place` |
| Mode 3 — OR-Tools | CP-SAT constraint programming, оптимізує за 5-60 с | `GET /admin/ai_generate` |

## Швидкий старт

### Локально (Windows)

```powershell
cd schedule_app
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# Налаштування середовища
copy .env.example .env
# Відредагуй .env: вкажи SECRET_KEY та ADMIN_PIN

# Запуск
python app.py
# → http://localhost:5000
```

### Docker (з ELK)

```powershell
cd schedule_app
docker-compose up --build
# Flask: http://localhost:5000
# Kibana: http://localhost:5601
```

## Адміністрування

1. Перейти на `/admin` → ввести PIN (з `.env`)
2. Додати предмети, викладачів, групи, аудиторії
3. Налаштувати навантаження (CourseLoad)
4. Обрати спосіб генерації:
   - **Жадібний** — миттєво
   - **AI Генерація (OR-Tools)** — оптимально, 5-60 с
   - **Ручне розміщення** — вручну з AI-підказками

## Тести

```powershell
cd schedule_app
pytest tests/ -v
```

## Змінні середовища

| Змінна | Опис |
|---|---|
| `SECRET_KEY` | Flask session key |
| `ADMIN_PIN` | PIN для входу адміністратора |
| `DATABASE_URL` | URL бази даних (за замовчуванням SQLite) |

## AI-модуль

Детальна документація: [schedule_app/ai/README.md](schedule_app/ai/README.md)

Коротко:
- **Оцінювання** — `scoring.py` рахує якість розкладу (0-100) за 4 HARD + 3 SOFT критеріями
- **OR-Tools** — CP-SAT знаходить оптимальний розклад (Score ~92/100 vs ~27 у жадібного)
- **Random Forest** — навчається на датасеті з 1000 запусків, підказує найкращі слоти в Mode 2
