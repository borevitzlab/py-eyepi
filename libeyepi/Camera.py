import datetime
import logging.config

import os
import shutil
import time
import tempfile
import traceback
from dateutil import zoneinfo, parser
from io import BytesIO
import threading
from threading import Thread, Event
# import cv2
from PIL import Image, ImageDraw, ImageFont
import re

timezone = zoneinfo.get_zonefile_instance().get("Australia/Canberra")

try:
    logging.config.fileConfig("/etc/eyepi/logging.ini")
except:
    pass

try:
    import telegraf
except Exception as e:
    logging.error("Couldnt import pytelegraf module, no telemetry: {}".format(str(e)))

regex = re.compile(r'((?P<hours>\d+?)hr)?((?P<minutes>\d+?)m)?((?P<seconds>\d+?)s)?')


def parse_duration(time_str):
    parts = regex.match(time_str)
    if not parts:
        return
    parts = parts.groupdict()
    time_params = {}
    for name, param in parts.items():
        if param:
            time_params[name] = int(param)
    return datetime.timedelta(**time_params)


class TwentyFourHourTimeParserInfo(parser.parserinfo):
    def validate(self, res):
        if res.year is not None:
            time = str(res.year)
            res.year = None
            res.hour = int(time[:2])
            res.minute = int(time[2:])
        if res.tzoffset == 0 and not res.tzname or res.tzname == 'Z':
            res.tzname = "UTC"
            res.tzoffset = 0
        elif res.tzoffset != 0 and res.tzname and self.utczone(res.tzname):
            res.tzoffset = 0
        return True


USBDEVFS_RESET = 21780


def nested_lookup(key, document):
    """
    nested document lookup,
    works on dicts and lists

    :param key: string of key to lookup
    :param document: dict or list to lookup
    :return: yields item
    """
    if isinstance(document, list):
        for d in document:
            for result in nested_lookup(key, d):
                yield result

    if isinstance(document, dict):
        for k, v in document.items():
            if k == key:
                yield v
            elif isinstance(v, dict):
                for result in nested_lookup(key, v):
                    yield result
            elif isinstance(v, list):
                for d in v:
                    for result in nested_lookup(key, d):
                        yield result


class Camera(Thread):
    """
    Base Camera class.
    """

    accuracy = 3
    default_width, default_height = 1080, 720
    file_types = ["CR2", "RAW", "NEF", "JPG", "JPEG", "PPM", "TIF", "TIFF"]
    output_types = ["tif", 'jpg']

    _frame = None
    _thread = None
    _last_access = None

    def init_stream(self):
        """
        Initialises a video stream class thread.
        """
        if self.__class__._thread is None:
            # start background frame thread
            self.__class__._thread = threading.Thread(target=self.stream_thread)
            self.__class__._thread.start()
            # wait until frames start to be available
            while self.__class__._frame is None:
                time.sleep(0.01)

    def get_frame(self) -> bytes:
        """
        Gets a frame from the a running :func:`stream_thread`.

        :return: encoded image data as bytes.
        """
        self.__class__._last_access = time.time()
        self.init_stream()
        return self.__class__._frame

    @classmethod
    def stream_thread(cls):
        """
        Boilerplate stream thread.
        Override this with the correct method of opening the camera, grabbing image data and closing the camera.
        """
        print("Unimplemented classmethod call: stream_thread")
        print("You should not create a Camera object directly")

        def get_camera():
            pass

        with get_camera() as camera:
            # let camera warm up
            while True:
                # example, you actually need to get the data from somewhere.
                cls._frame = camera.get_frame().read()
                # if there hasn't been any clients asking for frames in
                # the last 10 seconds stop the thread
                if time.time() - cls._last_access > 10:
                    break
        cls._thread = None

    def __init__(self, config, **kwargs):
        """
        Initialiser for cameras...

        :param identifier: unique identified for this camera, MANDATORY
        :param config: Configuration section for this camera.
        :param queue: deque to push info into
        :param noconf: dont create a config, or watch anything. Used for temporarily streaming from a camera
        :param kwargs:
        """
        identifier = config['filenameprefix']
        self.logger = logging.getLogger(identifier)

        super().__init__(name=identifier)
        print("Thread started {}: {}".format(self.__class__, identifier))

        self.logger.info("init...")

        self.stopper = Event()
        self.identifier = identifier
        self.name = identifier
        self._exif = dict()
        self._frame = None
        self._image = Image.new('RGB', (1,1))
        # self._image = numpy.empty((Camera.default_width, Camera.default_height, 3), numpy.uint8)
        self.config = config.copy()
        self.name = self.config.get("filenameprefix", identifier)

        self.interval = parse_duration(self.config.get("interval", "10m"))
        self.output_directory = "/var/lib/eyepi/{}".format(str(self.identifier))

        # self.begin_capture = datetime.time(0, 0)
        # self.end_capture = datetime.time(23, 59)
        #
        # try:
        #     self.begin_capture = parser.parse(str(self.config["starttime"]),
        #                                       parserinfo=TwentyFourHourTimeParserInfo()).time()
        # except Exception as e:
        #     self.logger.error("Time conversion error starttime - {}".format(str(e)))
        # try:
        #     # cut string to max of 4.
        #     self.end_capture = parser.parse(str(self.config["stoptime"]),
        #                                     parserinfo=TwentyFourHourTimeParserInfo()).time()
        # except Exception as e:
        #     self.logger.error("Time conversion error stoptime - {}".format(str(e)))

        try:
            if not os.path.exists(self.output_directory):
                self.logger.info("Creating local output dir {}".format(self.output_directory))
                os.makedirs(self.output_directory)
        except Exception as e:
            self.logger.error("Creating directories {}".format(str(e)))

        self._exif = self.get_exif_fields()

        # self.logger.info("Capturing from {} to {}".format(self.begin_capture.strftime("%H:%M"),
        #                                                   self.end_capture.strftime("%H:%M")))
        self.logger.info("Interval: {}".format(self.interval))

        self.current_capture_time = datetime.datetime.now()

    def capture_image(self, filename: str = None):
        """
        Camera capture method.
        override this method when creating a new type of camera.

        Behavior:
            - if filename is a string, write images to disk as filename.ext, and return the names of the images written sucessfully.
            - if filename is None, it will set the instance attribute `_image` to a numpy array of the image and return that.

        :param filename: image filename without extension
        :return: :func:`numpy.array` if filename not specified, otherwise list of files.
        :rtype: numpy.array or list(str)
        """
        return self._image

    def capture(self, filename: str = None):
        """
        capture method, only extends functionality of :func:`Camera.capture` so that testing with  can happen

        Camera.capture = Camera.capture_monkey
        For extending the Camera class override the Camera.capture_image method, not this one.

        :param filename: image filename without extension
        :return: :func:`numpy.array` if filename not specified, otherwise list of files.
        :rtype: numpy.array
        """

        if filename:
            dirname = os.path.dirname(filename)
            os.makedirs(dirname, exist_ok=True)
        return self.capture_image(filename=filename)

    @property
    def exif(self) -> dict:
        """
        Gets the current exif data, sets the exif datetime field to now.

        :return: dictionary of exif fields and their values.
        :rtype: dict
        """
        self._exif["Exif.Photo.DateTimeOriginal"] = datetime.datetime.now()
        return self._exif

    @property
    def image(self):
        """
        Gets the current image (last image taken and stored) as a numpy.array.

        :return: numpy array of the currently stored image.
        :rtype: numpy.array
        """
        return self._image

    @staticmethod
    def timestamp(tn: datetime.datetime) -> str:
        """
        Creates a properly formatted timestamp from a datetime object.

        :param tn: datetime to format to timestream timestamp string
        :return: formatted timestamp.
        """
        return tn.strftime('%Y_%m_%d_%H_%M_%S')

    @staticmethod
    def directory_timestamp(tn: datetime.datetime) -> str:
        """
        Creates a properly formatted directory timestamp from a datetime object.

        :param tn: datetime to format to timestream timestamp string
        :return: formatted timestamp.
        """
        return tn.strftime('%Y/%Y_%m/%Y_%m_%d/%Y_%m_%d_%H')

    @staticmethod
    def time2seconds(t: datetime.datetime) -> int:
        """
        Converts a datetime to an integer of seconds since epoch

        :return: integer of seconds since 1970-01-01
        :rtype: int
        """
        try:
            return int(t.timestamp())
        except:
            # the 'timestamp()' method is only implemented in python3.3`
            # this is an old compatibility thing
            return int(t.hour * 60 * 60 + t.minute * 60 + t.second)

    @property
    def timestamped_imagename(self) -> str:
        """
        Builds a timestamped image basename without extension from :func:`Camera.current_capture_time`

        :return: image basename
        :rtype: str
        """
        return '{camera_name}_{timestamp}'.format(camera_name=self.name,
                                                  timestamp=Camera.timestamp(self.current_capture_time))

    @property
    def time_to_capture(self) -> bool:
        """
        Filters out times for capture.

        returns True by default.

        returns False if the conditions where the camera should capture are NOT met.

        :return: whether or not it is time to capture
        :rtype: bool
        """
        current_naive_time = self.current_capture_time.time()

        # if self.begin_capture < self.end_capture:
        #     # where the start capture time is less than the end capture time
        #     if not self.begin_capture <= current_naive_time <= self.end_capture:
        #         return False
        # else:
        #     # where the start capture time is greater than the end capture time
        #     # i.e. capturing across midnight.
        #     if self.end_capture <= current_naive_time <= self.begin_capture:
        #         return False

        # capture interval
        if not (self.time2seconds(self.current_capture_time) % self.interval.total_seconds() < Camera.accuracy):
            return False
        return True

    def get_exif_fields(self) -> dict:
        """
        Get default fields for exif dict, this should be overriden and super-ed if you want to add custom exif tags.

        :return: exif fields
        :rtype: dict
        """
        exif = dict()
        exif['Exif.Image.Make'] = "Make"
        exif['Exif.Image.Model'] = "Model"
        exif['Exif.Image.CameraSerialNumber'] = self.identifier
        return exif

    def encode_write_image(self, img: Image, fn: str) -> list:
        """
        takes an image from PIL and writes it to disk as a tif and jpg
        converts from rgb to bgr for cv2 so that the images save correctly
        also tries to add exif data to the images

        :param PIL.Image img: 3 dimensional image array, x,y,rgb
        :param str fn: filename
        :return: files successfully written.
        :rtype: list(str)
        """
        # output types must be valid!
        fnp = os.path.splitext(fn)[0]
        successes = list()
        for ext in Camera.output_types:
            fn = "{}.{}".format(fnp, ext)
            s = False
            try:
                if ext == "tiff" or ext == "tif":
                    # format="TIFF" and compression='tiff_lzw' are required
                    # without these 2 params it will save a tiff without
                    img.save(fn, format="TIFF", compression='tiff_lzw')
                else:
                    img.save(fn)
                s = True
            except Exception as e:
                self.logger.error("Couldnt write image")
                self.logger.error(e)

            # im = Image.fromarray(np.uint8(img))
            # s = cv2.imwrite(fn, img)

            if s:
                successes.append(fn)
                try:
                    # set exif data
                    import pyexiv2
                    meta = pyexiv2.ImageMetadata(fn)
                    meta.read()
                    for k, v in self.exif.items():
                        try:
                            meta[k] = v
                        except:
                            pass
                    meta.write()
                except Exception as e:
                    self.logger.debug("Couldnt write the appropriate metadata: {}".format(str(e)))
        return successes

    @staticmethod
    def _write_raw_bytes(image_bytesio: BytesIO, fn: str) -> str:
        """
        Writes a BytesIO object to disk.

        :param image_bytesio: bytesio of an image.
        :param fn:
        :return: file name
        """
        with open(fn, 'wb') as f:
            f.write(image_bytesio.read())
            # no exif data when writing the purest bytes :-P
        return fn

    def stop(self):
        """
        Stops the capture thread, if self is an instance of :class:`threading.Thread`.
        """
        self.stopper.set()

    def focus(self):
        """
        AutoFocus trigger method.
        Unimplemented.
        """
        pass

    def run(self):
        """
        Main method. continuously captures and stores images.
        """
        while True and not self.stopper.is_set():
            self.current_capture_time = datetime.datetime.now()
            # checking if enabled and other stuff
            if self.__class__._thread is not None:
                self.logger.critical("Camera live view thread is not closed, camera lock cannot be acquired.")
                continue
            if self.time_to_capture:
                telemetry = dict()
                try:
                    with tempfile.TemporaryDirectory(prefix=self.name) as spool:
                        start_capture_time = time.time()
                        raw_image = self.timestamped_imagename
                        files = []
                        if self.config.get("enable", True):
                            self.logger.info("{} capture...".format(self.identifier))
                            files = self.capture(filename=os.path.join(spool, raw_image))
                            # capture. if capture didnt happen dont continue with the rest.

                            telemetry["timing_capture_s"] = float(time.time() - start_capture_time)

                            st = time.time()

                            img = self._image.resize((Camera.default_width,
                                                      Camera.default_height),
                                resample = Image.NEAREST)

                            d = ImageDraw.Draw(img)
                            fontpaths = ["/usr/share/fonts/TTF/Inconsolata-Bold.ttf", "/usr/share/fonts/truetype/Inconsolata-Bold.ttf"]
                            for fontpath in fontpaths:
                                if os.path.exists(fontpath):
                                    d.text((20, img.size[1] - 100), self.timestamped_imagename, fill=(0, 0, 255),
                                           font=ImageFont.truetype(fontpath, 50))
                                    break
                            else:
                                d.text((20, img.size[1] - 40), self.timestamped_imagename, fill=(0,0,255))

                            img.save(os.path.join("/dev/shm", self.identifier + ".jpg"))

                            # cv2.imwrite(os.path.join("/dev/shm", self.identifier + ".jpg"), self._image)
                            shutil.copy(os.path.join("/dev/shm", self.identifier + ".jpg"),
                                        os.path.join(self.output_directory, "last_image.jpg"))

                            resize_t = time.time() - st

                            telemetry["timing_resize_s"] = float(resize_t)
                            self.logger.info("Resize {0:.3f}s, total: {0:.3f}s".format(resize_t, time.time() - st))

                            # munge into list if list of lists


                            oldfiles = files[:]
                            files = []

                            for fn in oldfiles:
                                if type(fn) is list:
                                    files.extend(fn)
                                else:
                                    files.append(fn)
                        try:
                            telemetry["num_files_created"] = len(files)
                        except:
                            pass
                        for fn in files:
                            # move files to the upload directory
                            try:
                                out_dir = os.path.join(self.output_directory, Camera.directory_timestamp(self.current_capture_time))
                                os.makedirs(out_dir, exist_ok=True)
                                shutil.move(fn, out_dir)
                                self.logger.info("Captured & stored for upload - {}".format(os.path.basename(fn)))
                            except Exception as e:
                                self.logger.error("Couldn't move for timestamped: {}".format(str(e)))

                            # remove the spooled files that remain
                            try:
                                if os.path.isfile(fn):
                                    self.logger.info("File remaining in spool directory, removing: {}".format(fn))
                                    os.remove(fn)
                            except Exception as e:
                                self.logger.error("Couldn't remove spooled when it still exists: {}".format(str(e)))
                        # log total capture time
                        total_capture_time = time.time() - start_capture_time
                        self.logger.info("Total capture time: {0:.2f}s".format(total_capture_time))
                        telemetry["timing_total_s"] = float(total_capture_time)
                        # communicate our success with the updater
                        try:
                            # use UDP for telegraf, http is overhead and dodgy
                            telegraf_client = telegraf.TelegrafClient(host="localhost", port=8092)
                            telegraf_client.metric("camera", telemetry, tags={"camera_name": self.name})
                            self.logger.debug("Communicated telemetry to telegraf")
                        except Exception as exc:
                            self.logger.error("Couldnt communicate with telegraf client. {}".format(str(exc)))

                        last_captured_b = bytes(self.current_capture_time.replace(tzinfo=timezone).isoformat(), 'utf-8')
                        # self.communicate_with_updater()
                        # sleep for a little bit so we dont try and capture again so soon.
                        time.sleep(Camera.accuracy * 2)
                except Exception as e:
                    self.logger.critical("Image Capture error - {}".format(str(e)))
                    self.logger.critical(traceback.format_exc())
            time.sleep(1)

