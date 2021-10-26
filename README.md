# Docker Hub rate limits exporter for Prometheus

We should track how many pulls left because Docker Hub limits the number of Docker image downloads. It depends on the account type and publisher programs. Read more at [Download rate limit](https://docs.docker.com/docker-hub/download-rate-limit/) article

Rate-limits-exporter expose metrics for certain Docker Hub account(s) you've provided or for Anonymous user (by default without any credentials). The checks are being executed in the background. Calling `/metrics` path returns cached metrics.

## Usage

Multiple installation scenarios are provided.

### Docker

Don't forget to pass valid folder into container (read more at Help below):

```shell script
docker run -it --rm \
  -v /app/rate-limits:/opt/secrets \
  -e APP_SECRETS_DIR=/opt/secrets \
  -e APP_PORT=8080 \
  -e APP_LOOP_TIME=60 \
  -e LOG_LEVEL=DEBUG \
  bissquit/rate-limits-exporter:latest
```

### Docker-compose

For testing purposes or for quick review you may use Docker Compose:

```shell script
docker-compose up -d --build
```

### k8s

Deployment example provided in `k8s/` folder. Run it with command:

```shell script
kubectl -n namespace_name apply -f k8s/deployment.yaml
```

## Help

Exporter looks for the files in *directory* and expects each file is a separate Docker Hub account where filename is a username of Docker Hub; file content is a password (trailing new line will be removed)

You may pass options both via command line arguments or environment variables:

|Command line argument|Environment variable|Description|
| ----------- | ----------- | ----------- |
|-h, --help|-|show help message|
|-d, --directory|`APP_SECRETS_DIR`|Directory with files. The name of file - username of DockerHub, file content - password. (default: /opt/secrets)|
|-p, --port|`APP_PORT`|Port to be listened (default: 8080)|
|-t, --time|`APP_CHECK_INTERVAL`|Default time range in seconds to perform rate limits check (default: 60)|
|-|`LOG_LEVEL`|Log level based on Python [logging](https://docs.python.org/3/library/logging.html) module. expected values: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)|

Metrics example:

```text
# HELP dockerhub_ratelimit_current Current max limit for DockerHub account (or for ip address if anonymous access)
# TYPE dockerhub_ratelimit_current gauge
dockerhub_ratelimit_current{dockerhub_user="Anonymous"} 100
# HELP dockerhub_ratelimit_remaining Remaining limit for DockerHub account (or for ip address if anonymous access)
# TYPE dockerhub_ratelimit_remaining gauge
dockerhub_ratelimit_remaining{dockerhub_user="Anonymous"} 100
dockerhub_ratelimit_scrape_error{dockerhub_user="Anonymous"} 0
```
