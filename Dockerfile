FROM balenalib/raspberry-pi-debian-python:latest-buster

# we need to install PIL and numpy from the repos because otherwise
# they will not compile and its too hard to bother installing the deps
# to compile them

RUN \
    echo "**** install packages ****" && apt-get update &&  apt-get install -y  \
    python3-pip \
    python3-numpy \
    python3-pil \
    python3-requests \
    python3-pyudev \
    python3-toml \
    python3-setuptools \
    python3-dateutil \
    fonts-inconsolata \
    gphoto2 \
    && apt-get clean autoclean \
  && apt-get autoremove --yes \
  && rm -rf /var/lib/{apt,dpkg,cache,log}/

RUN \
    echo "**** install pip packages ****" && pip3 install \
    pytelegraf picamera

COPY . /py-eyepi-install

COPY logging.ini /etc/eyepi/logging.ini

RUN \
    cd /py-eyepi-install && \
    python3 setup.py install


# this is totally required for picamera to work.
# DO NOT REMOVE THIS LINE!
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/vc/lib

# ports and volumess
VOLUME /var/lib/eyepi /etc/eyepi

CMD ["py-eyepi"]

ENV DOCKER true
# environment variables for a picam
#ENV PICAM_FILENAMEPREFIX py-eyepi
#ENV PICAM_INTERVAL 10m
#more environment variables
# ENV GPHOTO2_GPHOTOSERIALNUMBER "asdfadgasdgf"
# ENV GPHOTO2_FILENAMEPREFIX "CAM01"
# ENV GPHOTO2_INTERVAL "10m"


