from .Camera import Camera
import aravis
import cv2
# import numpy
# import cv2
class GigECamera(Camera):
    """
    Picamera extension to the Camera abstract class.
    """


    def set_camera_settings(self, camera):
        """
        Sets the camera resolution to the max resolution

        if the config provides camera/height or camera/width attempts to set the resolution to that.
        if the config provides camera/isoattempts to set the iso to that.
        if the config provides camera/shutter_speed to set the shutterspeed to that.

        :param picamera.PiCamera camera: picamera camera instance to modify
        """
        try:
            camera.resolution = camera.MAX_RESOLUTION
            if type(self.config) is dict:
                if hasattr(self, "width") and hasattr(self, "height"):
                    camera.resolution = (int(self.width),
                                         int(self.height))
                if "width" in self.config and "height" in self.config:
                    camera.resolution = (int(self.config['width']),
                                         int(self.config['height']))

                camera.shutter_speed = getattr(self, "shutter_speed", camera.shutter_speed)
                camera.iso = getattr(self, "iso", camera.iso)
            else:
                if self.config.has_option("camera", "width") and self.config.has_option("camera", "height"):
                    camera.resolution = (self.config.getint("camera", "width"),
                                         self.config.getint("camera", "height"))
                if self.config.has_option("camera", "shutter_speed"):
                    camera.shutter_speed = self.config.getfloat("camera", "shutter_speed")
                if self.config.has_option("camera", "iso"):
                    camera.iso = self.config.getint("camera", "iso")
        except Exception as e:
            self.logger.error("error setting picamera settings: {}".format(str(e)))

    def capture_image(self, filename: str = None):
        """
        Captures image using the Raspberry Pi Camera Module, at either max resolution, or resolution
        specified in the config file.

        Writes images disk using :func:`encode_write_image`, so it should write out to all supported image formats
        automatically.

        :param filename: image filename without extension
        :return: :func:`numpy.array` if filename not specified, otherwise list of files.
        :rtype: numpy.array
        """
        st = time.time()
        try:
            with picamera.PiCamera() as camera:
                with picamera.array.PiRGBArray(camera) as output:
                    time.sleep(2)  # Camera warm-up time
                    self.set_camera_settings(camera)
                    time.sleep(0.2)
                    # self._image = numpy.empty((camera.resolution[1], camera.resolution[0], 3), dtype=numpy.uint8)
                    camera.capture(output, 'rgb')
                    # self._image = output.array
                    self._image = Image.fromarray(output.array)
                    # self._image = cv2.cvtColor(self._image, cv2.COLOR_BGR2RGB)
            if filename:
                filenames = self.encode_write_image(self._image, filename)
                self.logger.debug("Took {0:.2f}s to capture".format(time.time() - st))
                return filenames
            else:
                self.logger.debug("Took {0:.2f}s to capture".format(time.time() - st))
        except Exception as e:
            self.logger.critical("EPIC FAIL, trying other method. {}".format(str(e)))
            return None
        return None
