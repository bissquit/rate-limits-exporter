FROM python:3.7-slim
LABEL description="Docker Hub rate limits exporter for Prometheus" \
      source="https://github.com/bissquit/rate-limits-exporter"

COPY src/rate_limits_exporter.py requirements.txt /opt/

WORKDIR /opt
# Use non root user for install and run rate_limits_exporter
RUN groupadd --gid 1024 rate_limits_exporter \
    && useradd \
        --uid 1024 \
        --gid 1024 \
        --create-home \
        --shell /bin/bash \
        rate_limits_exporter \
    && mkdir /opt/secrets \
    && chown 1024:1024 /opt/secrets \
    && pip install --upgrade pip \
    && pip install --no-cache-dir --upgrade -r requirements.txt

USER 1024
CMD ["python", "-u", "/opt/rate_limits_exporter.py"]
