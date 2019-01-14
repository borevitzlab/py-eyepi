FROM resin/rpi-raspbian:stretch

# we need to install PIL and numpy from the repos because otherwise
# they will not compile and its too hard to bother installing the deps
# to compile them

RUN \
    echo "**** install packages ****" && \
    apt-get update && \
    apt-get install -y \
    python3-numpy \
    python3-pil \
    python3-pip \
    python3-requests \
    python3-pyudev \
    python3-toml \
    python3-setuptools \
    gphoto2 \
    && pip3 install pytelegraf[http] \
    && apt-get clean autoclean \
  && apt-get autoremove --yes \
  && rm -rf /var/lib/{apt,dpkg,cache,log}/

COPY . /py-eyepi-install

RUN \
    cd /py-eyepi-install && \
    python3 setup.py install


# this is totally required for picamera to work.
# DO NOT REMOVE THIS LINE!
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/vc/lib

# ports and volumes
VOLUME /var/lib/eyepi /etc/eyepi

CMD ["/usr/bin/py-eyepi"]


#ENVIRONMENT VARIABLES
ENV PICAM_FILENAMEPREFIX py-eyepi
ENV PICAM_INTERVAL 10m
#more environment variables
# ENV GPHOTO_CAM01_GPHOTOSERIALNUMBER "asdfadgasdgf"
# ENV GPHOTO_CAM01_INTERVAL "10m"
# ENV GPHOTO_CAM01_FILENAMEPREFIX "CAM01"


