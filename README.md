# Schedule App

Веб-застосунок для автоматичної генерації та перегляду розкладу занять. Побудований на Flask із SQLite базою даних.

## Можливості

- Автоматична генерація розкладу за жадібним алгоритмом
- Фільтрація розкладу за групою, дисципліною або викладачем
- Адміністративна панель для керування ресурсами (групи, викладачі, аудиторії, дисципліни, навантаження)
- JSON-логування всіх HTTP-запитів

## Стек

- **Backend:** Python 3.11, Flask, Flask-SQLAlchemy
- **База даних:** SQLite
- **Логування:** python-json-logger → ELK stack
- **CI/CD:** GitHub Actions

## Структура проєкту

```
schedule_app/
├── .github/workflows/ci.yml   # GitHub Actions
├── logstash/pipeline/         # Конфіг Logstash
├── logs/                      # JSON логи Flask (не в git)
├── static/                    # CSS, JS, favicon
├── templates/                 # HTML шаблони
│   ├── admin/                 # Адмін панель
│   └── student/               # Перегляд розкладу
├── tests/                     # Автотести (pytest)
├── app.py                     # Основний файл застосунку
├── conftest.py                # Конфігурація pytest
├── docker-compose.yml         # ELK стек + Flask
├── Dockerfile                 # Docker образ Flask
└── requirements.txt
```

## Запуск локально

**1. Клонування та середовище:**

```bash
git clone https://github.com/<your-username>/schedule_app.git
cd schedule_app
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

**2. Змінні середовища:**

Скопіюй `.env.example` у `.env` і заповни значення:

```bash
cp .env.example .env
```

```
APP_SECRET_KEY=your_secret_key_here
ADMIN_PIN=your_pin_here
DATABASE_URL=sqlite:///schedule.db
```

**3. Запуск:**

```bash
python app.py
```

Застосунок доступний на `http://localhost:5000`

---

## CI/CD

Налаштовано через **GitHub Actions** (`.github/workflows/ci.yml`).

### Що відбувається при кожному push або pull request у `main`:

1. Розгортається Ubuntu середовище з Python 3.11
2. Встановлюються залежності з `requirements.txt`
3. Запускаються автотести через `pytest tests/ -v`

### Змінні середовища для CI

Задаються через **GitHub Secrets** (Settings → Secrets and variables → Actions):

| Secret | Опис |
|--------|------|
| `SECRET_KEY` | Секретний ключ Flask (мапиться на `APP_SECRET_KEY`) |
| `ADMIN_PIN` | PIN-код адміністратора |

`DATABASE_URL` для тестів задається прямо у `ci.yml` як `sqlite:///test.db` — не потребує секрету.

### Запуск тестів локально:

```bash
pytest tests/ -v
```

---

## ELK Stack (логування)

Для моніторингу логів використовується стек **Elasticsearch + Logstash + Kibana**.

### Архітектура

```
Flask → logs/app.log → Logstash → Elasticsearch → Kibana
```

Flask пише кожен HTTP-запит у `logs/app.log` у форматі JSON:

```json
{"asctime": "2026-05-17 17:00:00,000", "levelname": "INFO", "message": "request", "method": "GET", "path": "/schedule", "status": 200, "ip": "127.0.0.1"}
```

### Запуск ELK стеку

Потрібен встановлений [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
docker-compose up --build
```

| Сервіс | URL |
|--------|-----|
| Flask | http://localhost:5000 |
| Kibana | http://localhost:5601 |
| Elasticsearch | http://localhost:9200 |

### Перший запуск Kibana

1. Відкрий `http://localhost:5601`
2. Перейди в **Stack Management → Data Views → Create data view**
3. Index pattern: `schedule-app-logs-*`
4. Timestamp field: `@timestamp`
5. Збережи та перейди в **Discover** або **Dashboard**

### Зупинка

```bash
docker-compose down
```

Щоб також видалити збережені дані Elasticsearch:

```bash
docker-compose down -v
```
