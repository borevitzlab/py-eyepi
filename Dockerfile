FROM resin/rpi-raspbian:latest

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
    gphoto2 \
  && pip3 install py-eyepi \
  && apt-get clean autoclean \
  && apt-get autoremove --yes \
  && rm -rf /var/lib/{apt,dpkg,cache,log}/

# this is totally required for picamera to work.
# DO NOT REMOVE THIS LINE!
ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/vc/lib

# ports and volumes
VOLUME /var/lib/eyepi /etc/eyepi

CMD ["/usr/bin/py-eyepi"]


#ENVIRONMENT VARIABLES
# PICAM_FILENAMEPREFIX
# PICAM_INTERVAL