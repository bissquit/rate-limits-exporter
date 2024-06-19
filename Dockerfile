FROM python:3.9-slim

LABEL description="Docker Hub rate limits exporter for Prometheus" \
      source="https://github.com/bissquit/rate-limits-exporter"

# nobody user in base image
ARG UID=65534

COPY --chown=$UID:$UID rate_limits_exporter.py \
                       requirements.txt \
                       /opt/

WORKDIR /opt

RUN pip install --upgrade pip && \
    pip install --no-cache-dir --upgrade -r requirements.txt && \
    mkdir /opt/secrets \
    chown $UID:$UID /opt/secrets

EXPOSE 8080

USER $UID

CMD ["python3", "/opt/rate_limits_exporter.py"]
