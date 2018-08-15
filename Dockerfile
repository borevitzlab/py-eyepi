FROM resin/raspberry-pi-alpine-python

RUN \
    echo "**** install packages ****" && \
    apk add --update \
    py3-numpy \
    py3-pillow \
    gphoto2 \
  && pip3 install py-eyepi \
  && rm -rf /var/cache/apk/*

# ports and volumes
VOLUME /var/lib/eyepi /etc/eyepi

CMD ["/usr/bin/py-eyepi"]
