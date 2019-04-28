import time
import logging.config
from .Camera import Camera
from PIL import Image

from dateutil import zoneinfo

timezone = zoneinfo.get_zonefile_instance().get("Australia/Canberra")

try:
    logging.config.fileConfig("/etc/eyepi/logging.ini")
except:
    pass


try:
    import cv2
except Exception as e:
    logging.error("Couldnt import opencv module, no opencv support: {}".format(str(e)))
    pass


class USBCamera(Camera):
    """
    USB Camera Class
    """

    @classmethod
    def stream_thread(cls):
        """
        usb camera stream thread.
        TODO: Needs to be aware of multiple cameras.
        """
        print("ThreadStartup ...")
        cam = cv2.VideoCapture()

        # camera setup
        # let camera warm up
        time.sleep(2)
        cam.set(3, 30000)
        cam.set(4, 30000)

        print("Started up!")
        # for foo in camera.capture_continuous(stream, 'jpeg',
        #                                      use_video_port=True):
        while True:
            ret, frame = cam.read()
            frame = cv2.imencode(".jpg", frame)
            cls._frame = frame[1].tostring()
            # store frame

            # if there hasn't been any clients asking for frames in
            # the last 10 seconds stop the thread
            if time.time() - cls._last_access > 10:
                print("ThreadShutdown")
                break
        cls._thread = None

    def __init__(self, identifier: str, sys_number: int, **kwargs):
        """
        USB camera init. must have a sys_number (the 0 from /dev/video0) to capture from

        :param identifier: identifier for the webcamera
        :param sys_number: system device number of device to use
        :param kwargs:
        """
        self.logger = logging.getLogger(identifier)

        try:
            import cv2
        except ImportError as e:
            self.logger.fatal(e)
            self.logger("no webcam support through cv2")
        # only webcams have a v4l sys_number.
        self.sys_number = int(sys_number)
        self.video_capture = None
        try:
            self.video_capture = cv2.VideoCapture()
        except Exception as e:
            self.logger.fatal("couldnt open video capture device on {}".format(self.sys_number))

        self._assert_capture_device()
        try:
            if not self.video_capture.open(self.sys_number):
                self.logger.fatal("Couldnt open a video capture device on {}".format(self.sys_number))
        except Exception as e:
            self.logger.fatal("Couldnt open a video capture device")
        # 3 -> width 4->height 5->fps just max them out to get the highest resolution.
        self.video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 100000)
        self.video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, 100000)
        self.logger.info("Capturing at {w}x{h}".format(w=self.video_capture.get(cv2.CAP_PROP_FRAME_WIDTH),
                                                       h=self.video_capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))

        super(USBCamera, self).__init__(identifier, **kwargs)

    def stop(self):
        """
        releases the video device and stops the camera thread
        """
        try:
            self.video_capture.release()
        except Exception as e:
            self.logger.error("Couldnt release cv2 device {}".format(str(e)))
        self.stopper.set()

    def _assert_capture_device(self):
        """
        ensures the capture device is open and valid.

        :param self:
        """
        try:
            if not self.video_capture:
                self.video_capture = cv2.VideoCapture()

            if not self.video_capture.isOpened():
                if not self.video_capture.open(self.sys_number):
                    raise IOError("VideoCapture().open({}) failed.".format(self.sys_number))
        except Exception as e:
            self.logger.error("Capture device could not be opened {}".format(str(e)))

    def capture_image(self, filename=None):
        """
        captures an image from the usb webcam.
        Writes some limited exif data to the image if it can.

        :param filename: filename to output without excension
        :return: list of image filenames if filename was specified, otherwise a numpy array.
        :rtype: numpy.array or list
        """

        st = time.time()
        for _ in range(50):
            try:
                ret, im = self.video_capture.read()
                if ret:
                    self._image = Image.fromarray(im)
                    break
                time.sleep(0.1)
            except Exception as e:
                self.logger.error("Error webcam capture did not read {}".format(str(e)))
        else:
            self.logger.error("webcam failed capture 50 times.")
            return None

        if filename:
            try:
                filenames = self.encode_write_image(self._image, filename)
                self.logger.debug("Took {0:.2f}s to capture".format(time.time() - st))
                return filenames
            except Exception as e:
                self.logger.error("Could not write image {}".format(str(e)))
        else:
            self.logger.debug("Took {0:.2f}s to capture".format(time.time() - st))
            return self._image
        return None

