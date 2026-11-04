# Python web stacks (FastAPI+uvicorn, Django+gunicorn) — multi-arch without QEMU.
# Wheels for TARGETARCH are fetched on the build host (pip --platform), the final stage only
# COPYs, so buildx never has to execute a foreign-arch RUN.
ARG PY_VERSION=3.14.10
FROM --platform=$BUILDPLATFORM public.ecr.aws/docker/library/python:${PY_VERSION}-slim AS deps
ARG TARGETARCH
COPY requirements.txt /tmp/requirements.txt
RUN set -eux; \
    case "$TARGETARCH" in amd64) P=x86_64 ;; arm64) P=aarch64 ;; *) exit 1 ;; esac; \
    pip install --no-cache-dir --target /deps --only-binary=:all: \
      --implementation cp --python-version 3.14 \
      --platform "manylinux_2_28_${P}" --platform "manylinux_2_17_${P}" --platform "manylinux2014_${P}" \
      -r /tmp/requirements.txt

FROM public.ecr.aws/docker/library/python:${PY_VERSION}-slim
COPY --from=deps /deps /deps
COPY fastapi_app.py django_app.py /app/
ENV PYTHONPATH=/deps PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
EXPOSE 8080
# Server command is set per stack in benchmarks/web/*-server-remote.yaml
CMD ["python", "-m", "uvicorn", "fastapi_app:app", "--host", "0.0.0.0", "--port", "8080"]
