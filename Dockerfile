# The clock catalogue is derived from biolearn, which pulls torch and the rest
# of the scientific stack - roughly 3 GB. None of that is needed to serve an
# audit: only the list of CpG ids each clock requires. So it is extracted here,
# in a stage that is thrown away, and the runtime image carries a 1.5 MB file.

# ---------- stage 1: derive the catalogue ----------------------------------
FROM python:3.13-slim AS catalogue

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-build.txt .
RUN pip install --no-cache-dir -r requirements-build.txt
COPY scripts/extract_clocks.py scripts/
RUN mkdir -p app && python scripts/extract_clocks.py \
    && gzip -9 app/clocks.json \
    && ls -l app/clocks.json.gz

# ---------- stage 2: the same service, as a Lambda function ---------------
# Lambda does not run a web server - it invokes a handler - so this target uses
# the AWS runtime base image and app/lambda_handler.py. The application code is
# identical; only the entry point differs.
FROM public.ecr.aws/lambda/python:3.13 AS lambda

COPY requirements.txt requirements-lambda.txt ./
RUN pip install --no-cache-dir -r requirements-lambda.txt

COPY app/ ${LAMBDA_TASK_ROOT}/app/
COPY --from=catalogue /build/app/clocks.json.gz ${LAMBDA_TASK_ROOT}/app/clocks.json.gz

CMD ["app.lambda_handler.handler"]

# ---------- last stage: the image that actually runs ----------------------
# Deliberately last: `docker build .` with no --target builds the final stage,
# so the default must stay the ordinary service, not the Lambda variant.
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY --from=catalogue /build/app/clocks.json.gz app/clocks.json.gz

# Run unprivileged. Nothing here needs to write to disk.
RUN useradd --create-home --shell /usr/sbin/nologin audit \
    && chown -R audit:audit /srv
USER audit

EXPOSE 8080

# Checks the app, not just the process: a reply proves the catalogue loaded.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=4).status==200 else 1)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 2"]
