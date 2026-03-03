# This builds the Docker image to be deployed in production.
#
# This image's only purpose is to inject environment variables
# and python libraries into config.py when running Superset.
#
# If you need to run locally, see the apache/superset Git repo instead.
#
FROM apache/superset:6.0.0

COPY --chown=superset --chmod=0755 ./docker/docker-bootstrap.sh /app/docker/
COPY --chown=superset --chmod=0755 ./docker/docker-init.sh /app/docker/
# COPY --chown=superset ./docker/docker-ci.sh /app/docker/

# Specify your own python libraries in requirements-addons.txt
# Install into venv as root using uv (see docs):
# https://superset.apache.org/user-docs/6.0.0/installation/docker-builds/#building-your-own-production-docker-image 
COPY --chown=superset ./docker/requirements-addons.txt /app/docker/
USER root
RUN . /app/.venv/bin/activate \
 && uv pip install --no-cache-dir -r /app/docker/requirements-addons.txt
USER superset

# This script is what sets config values from environment variables.
COPY --chown=superset ./docker/pythonpath/superset_config.py /app/pythonpath/
ENV PYTHONPATH="${PYTHONPATH}:/app/pythonpath/"

ENV SCARF_ANALYTICS=false
ENV FLASK_ENV=production
ENV SUPERSET_ENV=production
