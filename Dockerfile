FROM resin/raspberry-pi-alpine-python

RUN \
    echo "**** install packages ****" && \
    apk add --update \
    raspberrypi-libs \
    py3-numpy \
    py3-pillow \
    gphoto2 \
  && pip3 install py-eyepi \
  && rm -rf /var/cache/apk/*

# this is totally required for picamera to work. DO NOT REMOVE THIS LINE!
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/vc/lib

# ports and volumes
VOLUME /var/lib/eyepi
VOLUME /etc/eyepi

CMD ["/usr/bin/py-eyepi"]
