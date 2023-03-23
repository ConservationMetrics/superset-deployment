# This builds the Docker image to be deployed in production.
#
# This image's only purpose is to inject environment variables into config.py
# when running Superset.
#
# If you need to run locally, see the apache/superset Git repo instead.
#
FROM apache/superset:2.1.0rc3

COPY --chown=superset ./docker/docker-bootstrap.sh /app/docker/
COPY --chown=superset ./docker/docker-init.sh /app/docker/
# COPY --chown=superset ./docker/docker-ci.sh /app/docker/

# This script is what sets config values from environment variables.
COPY --chown=superset ./docker/pythonpath/superset_config.py /app/pythonpath/
ENV PYTHONPATH "${PYTHONPATH}:/app/pythonpath/"

ENV FLASK_ENV production
ENV SUPERSET_ENV production

RUN chmod a+x /app/docker/*.sh
