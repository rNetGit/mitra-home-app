# Mitra Home for Linux servers and NAS boxes. Phones and walls only (HTTPS on the Wi-Fi, PIN required).
# The PC browser UI trusts loopback, so it is NOT offered from a container: setup is a terminal step (see docs/DOCKER.md).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MITRAHOME_VENV=/opt/venv \
    MITRAHOME_CONTAINER=1 \
    PATH=/opt/venv/bin:$PATH

RUN useradd --create-home --uid 1000 mitra && mkdir /data /Mitra-Home-Backup && chown mitra /data /Mitra-Home-Backup
WORKDIR /app
COPY --chown=mitra:mitra . /app
# household folder lives in the /data volume: the marker in the app folder points there
RUN echo /data > /app/mitrahome_home.txt && chown mitra /app/mitrahome_home.txt \
    && chmod +x /app/docker/entrypoint.sh && cp /app/docker/crontab /usr/local/bin/crontab && chmod +x /usr/local/bin/crontab \
    && python launch.py --prepare \
    && chown -R mitra /opt/venv /app

USER mitra
VOLUME ["/data", "/Mitra-Home-Backup"]
# phones: HTTPS on the app port + 100 (the plain-http port stays inside the container)
EXPOSE 8701
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["serve"]
