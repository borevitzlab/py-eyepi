FROM resin/raspberry-pi-alpine-python:3.6.1-slim

RUN \
    echo "**** install packages ****" && \
    apk add --update \
    py-numpy \
    py-pillow \
    gphoto2 \
  && pip3 install py-eyepi \
  && rm -rf /var/cache/apk/*

COPY . .

# ports and volumes
VOLUME /var/lib/eyepi /etc/eyepi

CMD ["/usr/bin/py-eyepi"]
