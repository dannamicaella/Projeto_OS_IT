# Inovatech OS

Order of Service management system with QR code generation.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` if needed (defaults use local SQLite).

## Run

```bash
python main.py
```

Open http://localhost:8000

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL or SQLite URL | `sqlite:///os.db` |
| `SECRET_KEY` | Session secret | `dev-only-insecure-key` |
| `FRONTEND_URL` | Base URL for QR code links | `http://localhost:8000` |
| `PORT` | Port (only used when running directly with `python main.py`) | `8000` |
