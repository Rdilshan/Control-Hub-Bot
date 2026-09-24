# Control Hub Platform — Backend

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%2B-red.svg)](https://www.sqlalchemy.org/)
[![Redis](https://img.shields.io/badge/Redis-7%2B-dc382d.svg)](https://redis.io/)

A scalable, multi-bot Telegram management platform backend built with FastAPI, PostgreSQL, Redis, and SQLAlchemy.

---

## 1. Project Overview

Control Hub provides a dual-bot platform:
- **Control Hub Bot**: Main management bot for the Platform Owner and Clients to register and manage connected bots.
- **Client Bots**: Standalone Telegram bots connected by clients to serve videos, sponsors, unlock links, and broadcast content to viewers.

---

## 2. Technology Stack

- **Runtime & Framework**: Python 3.11+, FastAPI, Uvicorn
- **Database**: PostgreSQL 16 (Async via `asyncpg` + `SQLAlchemy 2.0`)
- **Migrations**: Alembic
- **Caching & State**: Redis 7 (`redis-py` async)
- **Settings & Validation**: Pydantic Settings v2
- **HTTP Client**: HTTPX (async Telegram Bot API integration)
- **Testing**: Pytest, Pytest-Asyncio, Pytest-Mock

---

## 3. Directory Structure

```text
control-hub-bot/
├── app/
│   ├── main.py               # FastAPI application entrypoint & middleware
│   ├── config.py             # Typed Pydantic configuration & env validation
│   ├── lifecycle.py          # Application startup & shutdown lifespan management
│   ├── logging_config.py     # Structured logging & secret redaction
│   ├── exceptions.py         # Standard domain exception hierarchy
│   │
│   ├── api/                  # API routers
│   │   ├── router.py         # Main router registry
│   │   └── routes/
│   │       └── health.py     # Liveness (/health) & Readiness (/health/ready)
│   │
│   ├── core/                 # Shared utilities, constants, enums, security
│   │   ├── constants.py
│   │   ├── enums.py
│   │   ├── security.py
│   │   └── utils.py
│   │
│   ├── db/                   # Database session, base model & migrations
│   │   ├── base.py
│   │   ├── session.py
│   │   └── models/
│   │
│   ├── redis/                # Redis client manager & health checks
│   │   └── client.py
│   │
│   ├── telegram/             # Reusable Telegram client & error translation
│   │   ├── client.py
│   │   ├── errors.py
│   │   └── types.py
│   │
│   ├── services/             # Business service layer (Stage 03+)
│   ├── repositories/         # Database access layer (Stage 02+)
│   └── workers/              # Background worker layer
│
├── migrations/               # Alembic database migrations
├── tests/                    # Unit and integration test suite
│   ├── unit/
│   └── integration/
│
├── .env.example
├── alembic.ini
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
└── run.py
```

---

## 4. Local Development Setup

### 4.1 Prerequisites
- Python 3.11+
- Docker & Docker Compose (for local PostgreSQL and Redis)

### 4.2 Installation

1. **Activate Virtual Environment:**
   ```powershell
   # Windows PowerShell
   venv\Scripts\Activate.ps1
   ```

2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment:**
   ```bash
   copy .env.example .env
   ```

4. **Start PostgreSQL & Redis:**
   ```bash
   docker compose up -d
   ```

5. **Run Database Migrations:**
   ```bash
   alembic upgrade head
   ```

6. **Start the Application:**
   ```bash
   python run.py
   # or
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

---

## 5. Health Check Endpoints

- **Liveness Probe**: `GET /health`  
  Returns `{"status": "ok"}` indicating the process is alive.

- **Readiness Probe**: `GET /health/ready`  
  Returns `200 OK` when both PostgreSQL and Redis connections succeed:
  ```json
  {
    "status": "ready",
    "services": {
      "database": "ok",
      "redis": "ok"
    }
  }
  ```
  Returns `503 Service Unavailable` if any dependency is unreachable.

---

## 6. Error Response Schema

All API error responses follow a standardized schema:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid bot token parameter",
    "details": { "field": "token" }
  },
  "request_id": "7c91d84e-333e-4b47-b86a-73d9178ad3a6"
}
```

---

## 7. Running Tests

```bash
pytest -v
```
