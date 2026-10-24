FROM python:3.14-slim-trixie

ARG BUILD_VERSION
ARG BUILD_ARCH=aarch64

LABEL \
    io.hass.name="Tellerplan" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.source="https://github.com/SpurZylinder/tellerplan-ha"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TELLERPLAN_OPTIONS=/data/options.json

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
