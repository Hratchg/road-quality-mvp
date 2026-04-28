# backend/Dockerfile — production image for road-quality-backend.
# Build context is `backend/` (matches docker-compose.yml's `build: ./backend`
# and deploy/backend/fly.toml's positional arg). When deploying via flyctl,
# the CI workflow pins flyctl to 0.4.40 in .github/workflows/deploy.yml —
# 0.4.41 changed [build].dockerfile path resolution and produced
# "dockerfile not found" errors against the doubled-name GH-Actions
# checkout root. Re-verify all 3 deploy/*.toml dockerfile paths before
# bumping the pin.

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
