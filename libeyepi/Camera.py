import datetime
import logging.config
import glob
import os
import shutil
import time
import tempfile
# import numpy
import traceback
import subprocess
from dateutil import zoneinfo, parser
from io import BytesIO
import threading
from threading import Thread, Event, Lock
# import cv2
from PIL import Image, ImageDraw
import re

timezone = zoneinfo.get_zonefile_instance().get("Australia/Canberra")

try:
    logging.config.fileConfig("/etc/eyepi/logging.ini")
except:
    pass

try:
    import picamera
    import picamera.array
except Exception as e:
    logging.error("Couldnt import picamera module, no picamera camera support: {}".format(str(e)))
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

        self.interval = parse_duration(self.config.get("interval", "5m"))
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
                if ext == "tiff":
                    img.save(fn, compression='tiff_deflate')
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
    def _write_raw_bytes(image_bytesio: BytesIO, fn: str) -> list:
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
            last_captured_b = b''
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

                            # self._image = cv2.resize(self._image, (Camera.default_width, Camera.default_height),
                            #                          interpolation=cv2.INTER_NEAREST)
                            img = self._image.resize((Camera.default_width,
                                                              Camera.default_height),
                                resample = Image.NEAREST)

                            # cv2.putText(self._image,
                            #             self.timestamped_imagename,
                            #             org=(20, self._image.shape[0] - 20),
                            #             fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                            #             fontScale=1,
                            #             color=(0, 0, 255),
                            #             thickness=2,
                            #             lineType=cv2.LINE_AA)
                            d = ImageDraw.Draw(img)
                            d.text((20, img.size[1] - 20), self.timestamped_imagename, fill=(0,0,255))

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
                                shutil.move(fn, self.output_directory)
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
                            telegraf_client = telegraf.HttpClient(host="localhost", port=8186)
                            telegraf_client.metric("camera", telemetry, tags={"camera_name": self.name})
                            self.logger.debug("Communicated sesor data to telegraf")
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
                            first = filenames[0] if filenames else None
                            self._image = Image.open(first)
                            # self._image = cv2.cvtColor(cv2.imread(first, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
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


class PiCamera(Camera):
    """
    Picamera extension to the Camera abstract class.
    """

    @classmethod
    def stream_thread(cls):
        """
        Streaming thread member.

        uses :func:`picamera.PiCamera.capture_continuous` to stream data from the rpi camera video port.

        :func:`time.sleep` added to rate limit a little bit.

        """
        import picamera
        print("start thread")
        try:
            with picamera.PiCamera() as camera:
                # camera setup
                camera.resolution = (640, 480)
                # camera.hflip = True
                # camera.vflip = True

                # let camera warm up
                camera.start_preview()
                time.sleep(2)

                stream = BytesIO()
                for foo in camera.capture_continuous(stream, 'jpeg',
                                                     use_video_port=True):
                    # store frame
                    stream.seek(0)
                    cls._frame = stream.read()

                    # reset stream for next frame
                    stream.seek(0)
                    stream.truncate()

                    # if there hasn't been any clients asking for frames in
                    # the last 10 seconds stop the thread
                    time.sleep(0.01)
                    if time.time() - cls._last_access > 1:
                        break
        except Exception as e:
            print("Couldnt acquire camera")
        print("Closing Thread")
        cls._thread = None

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
