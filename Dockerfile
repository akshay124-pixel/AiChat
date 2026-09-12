# ─────────────────────────────────────────────────────────────────────────────
# AI Chat — FastAPI backend
# Multi-stage build: builder installs deps, runtime runs the app as non-root.
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency installation ─────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --upgrade pip --no-cache-dir

COPY requirements.txt .

# Try pre-built wheels first (fastest, no Rust/C compiler needed).
# Fall back to full build if a wheel isn't available for this platform.
RUN pip install --only-binary :all: --prefix=/install -r requirements.txt \
    || pip install --prefix=/install -r requirements.txt

# ── Stage 2: minimal runtime image ───────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Create non-root user
RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup --no-create-home appuser

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy only the application source — no .env, no tests, no secrets
COPY app/ ./app/

# Drop to non-root for runtime
USER appuser

EXPOSE 8000

# Exec form ensures SIGTERM is delivered directly to uvicorn (not via shell).
# Single worker per container — scale by running more containers.
# uvloop/httptools are pulled in by uvicorn[standard]; if unavailable on this
# platform they're skipped gracefully via the requirements.txt conditional.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--loop", "uvloop", \
     "--http", "httptools", \
     "--no-access-log", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
