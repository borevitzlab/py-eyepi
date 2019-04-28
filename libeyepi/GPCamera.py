import glob, subprocess, re, traceback, os
import logging.config
from .Camera import Camera
from threading import Lock
from PIL import Image

from dateutil import zoneinfo

timezone = zoneinfo.get_zonefile_instance().get("Australia/Canberra")

try:
    logging.config.fileConfig("/etc/eyepi/logging.ini")
except:
    pass


class GPCamera(Camera):
    """
    Camera class
    other cameras inherit from this class.
    identifier and usb_address are NOT OPTIONAL
    """

    def __init__(self, config, lock=Lock(), **kwargs):
        """
        Providing a usb address and no identifier or an identifier but no usb address will cause

        :param identifier:
        :param lock:
        :param usb_address:
        :param kwargs:
        """

        self.lock = lock
        self.usb_address = [None, None]
        self._serialnumber = config['gphotoserialnumber']
        self.identifier = config["filenameprefix"]

        self.usb_address = self.usb_address_detect()

        super().__init__(config, **kwargs)
        print("Thread started {}: {}".format(self.__class__, self.identifier))

        self.logger.info("Camera detected at usb port {}:{}".format(*self.usb_address))
        try:
            self.exposure_length = self.config.getint("camera", "exposure")
        except:
            pass

    def usb_address_detect(self) -> tuple:
        detect_ret = subprocess.check_output(["/usr/bin/gphoto2",
                                              "--auto-detect"],
                                             universal_newlines=True)
        detected_usb_ports = re.findall(r'usb:(\d+),(\d+)', detect_ret)
        for bus, addr in detected_usb_ports:
            try:
                # findall returns strings...
                bus, addr = int(bus), int(addr)
                # this is the format that gphoto2 expects the port to be in.
                port = "usb:{},{}".format(bus, addr)

                # gphoto2 command to get the serial number for the DSLR
                # WARNING: when the port here needs to be correct, because otherwise gphoto2 will return values from
                # an arbitrary camera
                sn_detect_ret = subprocess.check_output(['/usr/bin/gphoto2',
                                                         '--port={}'.format(port),
                                                         '--get-config=serialnumber'],
                                                        universal_newlines=True)

                # Match the serial number.
                # this regex can also be used to parse the values from --get-config as all results are returned like this:
                # Label: Serial Number
                # Type: TEXT
                # Current: 4fffa81fed8f40d286a63fce62598ef0
                sn_match = re.search(r'Current: (\w+)', sn_detect_ret)

                if not sn_match:
                    # we didnt match any output from the command
                    self.logger.error("Couldnt match serial number from gphoto2 output. {}".format(port))
                    continue
                sn = sn_match.group(1)

                if sn.lower() == 'none':
                    # there is a bug in a specific version of gphoto2 that causes it to return 'None' for the camera serial
                    # number. If we cant get a unique serial number, we are screwed for multicamera
                    # todo: allow this if there is only one camera.
                    self.logger.error("serial number matched with value of 'none' {}".format(port))
                    continue

                # pad the serialnumber to 32
                if self._serialnumber == sn:
                    return (bus, addr)

            except:
                traceback.print_exc()
                self.logger.error("Exception detecting gphoto2 camera")
                self.logger.error(traceback.format_exc())
        else:
            self.logger.error(
                "No identifier from detected cameras ({}) matched desired: {}".format(len(detected_usb_ports),
                                                                                      self.identifier))

    def capture_image(self, filename=None):
        """
        Gapture method for DSLRs.
        Some contention exists around this method, as its definitely not the easiest thing to have operate robustly.
        :func:`GPCamera._cffi_capture` is how it _should_ be done, however that method is unreliable and causes many
        crashes when in real world timelapse situations.
        This method calls gphoto2 directly, which makes us dependent on gphoto2 (not just libgphoto2 and gphoto2-cffi),
        and there is probably some issue with calling gphoto2 at the same time like 5 times, maybe dont push it.

        :param filename: filename without extension to capture to.
        :return: list of filenames (of captured images) if filename was specified, otherwise a numpy array of the image.
        :rtype: numpy.array or list
        """

        # the %C filename parameter given to gphoto2 will automatically expand the number of image types that the
        # camera is set to capture to.

        # this one shouldnt really be used.
        fn = "{}-temp.%C".format(self.name)
        if filename:
            # if target file path exists
            fn = os.path.join(self.output_directory, "{}.%C".format(filename))

        cmd = [
            "gphoto2",
            "--port=usb:{bus:03d},{dev:03d}".format(bus=self.usb_address[0], dev=self.usb_address[1]),
            "--set-config=capturetarget=0",  # capture to sdram
            "--force-overwrite",  # if the target image exists. If this isnt present gphoto2 will lock up asking
            "--capture-image-and-download",  # must capture & download in the same call to use sdram target.
            '--filename={}'.format(fn)
        ]
        self.logger.debug("Capture start: {}".format(fn))
        for tries in range(6):
            self.logger.debug("CMD: {}".format(" ".join(cmd)))
            try:
                output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True)

                if "error" in output.lower():
                    raise subprocess.CalledProcessError("non-zero exit status", cmd=cmd, output=output)
                else:
                    # log success of capture
                    self.logger.info("GPCamera capture success: {}".format(fn))
                    for line in output.splitlines():
                        self.logger.debug("GPHOTO2: {}".format(line))
                    # glob up captured images
                    filenames = glob.glob(fn.replace("%C", "*"))
                    # if there are no captured images, log the error
                    if not len(filenames):
                        self.logger.error("capture resulted in no files.")
                    else:
                        # try and load an image for the last_image.jpg resized doodadery
                        try:
                            jpeg = next(iter(filter(lambda e: '.jpeg' in e.lower() or ".jpg" in e.lower(), filenames)), None)
                            self._image = Image.open(jpeg)
                        except Exception as e:
                            self.logger.error("Failed to set current image: {}".format(str(e)))

                        if filename:
                            # return the filenames of the spooled images if files were requestsed.
                            return filenames
                        else:
                            # otherwise remove the temporary files that we created in order to fill self._image
                            for fp in filenames:
                                os.remove(fp)
                            # and return self._image
                            return self._image

            except subprocess.CalledProcessError as e:
                self.logger.error("failed {} times".format(tries))
                for line in e.output.splitlines():
                    if not line.strip() == "" and "***" not in line:
                        self.logger.error(line.strip())
        else:
            self.logger.critical("Really bad stuff happened. too many tries capturing.")
            if filename:
                return []
        return None

    @property
    def serial_number(self) -> str:
        """
        returns the current serialnumber for the camera.
        """
        return self._serialnumber

    def focus(self):
        """
        this is meant to trigger the autofocus. currently not in use because it causes some distortion in the images.
        """
        pass
