# Moto: an emulator of the AWS APIs (S3, IAM, STS...) for local use.
# Small image: Python plus Moto, pinned with hashes.
FROM python:3.12.15-slim

# Never run as root inside the container
RUN useradd --create-home --uid 1000 moto

# requirements.txt is exported from uv.lock with hashes (regenerate it when
# the "moto" group changes):
#   uv export --only-group moto --no-emit-project --format requirements-txt \
#     --no-header -o docker/moto/requirements.txt
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt

USER moto
EXPOSE 5000
CMD ["moto_server", "-H", "0.0.0.0", "-p", "5000"]
