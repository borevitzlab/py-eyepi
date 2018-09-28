# py-eyepi
tool to capture images from dslrs and raspberry pi cameras


## installation
make sure you have Pillow and Numpy installed for python3 and gphoto2 if you want dslr support.

Also make sure that you have the raspberry pi libs

arch:

\# pacman -S raspberrypi-firmware python python-numpy python-pillow gphoto2

raspbian:

\# apt update && apt install python3-numpy python3-pil gphoto2

alpine:

\# apk add --update raspberrypi-libs py3-numpy py3-pillow gphoto2


### Config

config is available through /etc/eyepi/eyepi.conf with logging configuration done through /etc/eyepi/logging.ini

configuration is as follows 

```
[rpicamera]
enable = true # whether to enable this camera, you can also omit the entire section
filenameprefix = "MyCamera" # the prefix for the output images, if omitted, uses "*hostname*-Picam"
interval = 5m # default interval is 10m, but you can specify others, like 5m or 30s

[gphoto.camera1] # the suffix here can also be used instead of "filenameprefix"
enable = true
gphotoserialnumber = "b4e63ebd8704d48a864101496b8fce31" # this is very important, see Gphoto2 Serial Numbers 


```

images are dropped into /var/lib/eyepi/*filenameprefix*/*filenameprefix*_YYYY_mm_DD_HH_MM_SS_00.jpg


### Gphoto2 Serial Numbers
Gphoto2 serial numbers are unique identifiers for DSLR cameras.

they can be acquired by using `gphoto2 --auto-detect` to get the current port of the camera (usually something like "usb:003,002") and then running `gphoto2 --get-config serialnumber --port usb:003,002`


### Docker
A docker image is available but it is not functional yet due to som errors trying to get the raspberry pi camera working. I recommend using [ResinOS](https://resinos.io/docs/raspberrypi3/gettingstarted/) for this