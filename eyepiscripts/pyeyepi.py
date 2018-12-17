#!/usr/bin/env python3

import logging.config
import os
import subprocess
import sys
import pyudev
from libeyepi import Camera
from threading import Lock
import re
import traceback
import socket
import toml
import time


__author__ = "Gareth Dunstone"
__copyright__ = "Copyright 2018, Borevitz Lab"
__credits__ = ["Gareth Dunstone", "Tim Brown", "Justin Borevitz", "Kevin Murray", "Jack Adamson"]
__license__ = "GPL"
__version__ = "0.1"
__maintainer__ = "Gareth Dunstone"
__email__ = "gareth.dunstone@anu.edu.au"
__status__ = "alpha"


default_config = """
[rpicamera]
enable = true
"""

if not os.path.isfile("/etc/eyepi/eyepi.conf"):
    with open("/etc/eyepi/eyepi.conf", 'w') as f:
        f.write(default_config)

default_logging_config = """
[loggers]
keys = root

[handlers]
keys = logfileHandler,syslogHandler

[formatters]
keys = simpleformatter,logfileformatter

[logger_root]
level = DEBUG
handlers = logfileHandler,syslogHandler

[handler_logfileHandler]
class = handlers.TimedRotatingFileHandler
level = DEBUG
args = ('spc-eyepi.log','midnight')
formatter = logfileformatter

[handler_syslogHandler]
class = handlers.SysLogHandler
args=('/dev/log',)
level = DEBUG
formatter = simpleformatter

;[handler_kmsgHandler]
;class = logging.FileHandler
;level = INFO
;args = ('/dev/kmsg','w',)
;formatter = simpleformatter

;[handler_consoleHandler]
;class = StreamHandler
;level = DEBUG
;formatter = simpleformatter
;args = (sys.stdout,)

[formatter_logfileformatter]
format = %(asctime)s    %(levelname)s   [%(name)s.%(funcName)s:%(lineno)d]    %(message)s

[formatter_simpleformatter]
format = %(name)s - %(levelname)s:   %(message)s
"""


if not os.path.isfile("/etc/eyepi/logging.ini"):
    with open("/etc/eyepi/logging.ini", 'w') as f:
        f.write(default_logging_config)

# attempt to setup logging.
try:
    logging.config.fileConfig("/etc/eyepi/logging.ini")
except Exception as e:
    print("COULDNT SET UP LOGGING WTF")
    pass
logger = logging.getLogger("WORKER_DISPATCH")

global recent
recent = time.time()
global glock
glock = Lock()
global workers
workers = []

def detect_picam(conf) -> tuple:
    """
    Detects the existence of a picam
    on all SPC-OS devices this will return true if the picam is installed
    on other rpis it may return false if the raspberrypi-firmware-tools is not installed or the boot.cfg flag
    for the camera is not set.

    todo: this shoud return an empty tuple if an ivport is detected.
    todo: clean this up so that it doesnt require subprocess.

    :creates: :mod:`libs.Camera.PiCamera`, :mod:`libs.Uploader.Uploader`
    :param updater: instance that has a `communication_queue` member that implements an `append` method
    :type updater: Updater
    :return: tuple of raspberry pi camera thread and uploader.
    :rtype: tuple(PiCamera, Uploader)
    """
    logger.info("Detecting picamera")

    if not "filenameprefix" in conf:    
        conf['filenameprefix'] = "{}-Picam".format(socket.gethostname())

    environ_fnp = os.environ.get("PICAM_FILENAMEPREFIX")
    if environ_fnp is not None:
        conf['filenameprefix'] = environ_fnp

    environ_interval = os.environ.get("PICAM_INTERVAL")
    if environ_fnp is not None:
        conf['interval'] = environ_interval

    if not (os.path.exists("/opt/vc/bin/vcgencmd")):
        logger.error("vcgencmd not found, cannot detect picamera.")
        return tuple()
    try:
        cmdret = subprocess.check_output("/opt/vc/bin/vcgencmd get_camera", shell=True).decode()
        if "detected=1" in cmdret:
            camera = Camera.PiCamera(conf)
            return (camera,)
        else:
            return tuple()
    except subprocess.CalledProcessError as e:
        logger.error("Couldn't detect picamera. Error calling vcgencmd. {}".format(str(e)))
        pass
    except Exception as e:
        logger.error("General Exception in picamera detection. {}".format(str(e)))
    return tuple()


def detect_gphoto_info():
    """
    detects cameras connected via gphoto2 command line.

    this can potentially cause long wait times if a camera is attempting to capture for the split second that it tries
    to gphoto2, however it is the preferred method because it is the most robust and comparmentalised.

    :param type:
    :return: a dict of port:serialnumber values corresponding to the currently connected gphoto2 cameras.
    """

    try:
        cams = {}
        # check output of the --auto-detect gphoto2 command.
        detect_ret = subprocess.check_output(["/usr/bin/gphoto2",
                                              "--auto-detect"],
                                             universal_newlines=True)
        # iterate over the results, should be in the format of [(bus, addr), (bus, addr) ...] for usb connected dslrs
        # this regex matches occurrences of "usb:" followed by 2 comma separated digits.
        for bus, addr in re.findall(r'usb:(\d+),(\d+)', detect_ret):
            try:
                # findall returns strings...
                bus, addr = int(bus), int(addr)
                # this is the format that gphoto2 expects the port to be in.
                port = "usb:{0:03d},{1:03d}".format(bus, addr)

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
                    logger.error("Couldnt match serial number from gphoto2 output. {}".format(port))
                    continue
                sn = sn_match.group(1)

                if sn.lower() == 'none':
                    # there is a bug in a specific version of gphoto2 that causes it to return 'None' for the camera serial
                    # number. If we cant get a unique serial number, we are screwed for multicamera
                    # todo: allow this if there is only one camera.
                    logger.error("serial number matched with value of 'none' {}".format(port))
                    continue

                # pad the serialnumber to 32
                cams[sn] = (bus, addr)
            except:
                traceback.print_exc()
                logger.error("Exception detecting gphoto2 camera")
                logger.error(traceback.format_exc())
        return cams
    except subprocess.CalledProcessError as e:
        traceback.print_exc()
        logger.error("Subprocess error detecting gphoto2 cameras")
        logger.error(traceback.format_exc())
    return dict()


def detect_gphoto(confs):
    """
    detects cameras connected via gphoto2 command line.

    this can potentially cause long wait times if a camera is attempting to capture for the split second that it tries
    to gphoto2, however it is the preferred method because it is the most robust and comparmentalised.

    :param type:
    :return: a dict of port:serialnumber values corresponding to the currently connected gphoto2 cameras.
    """
    # generate overriding configuration entries from environment variables:

    # filter os.environ vars coz we only care about the vars starting with GPHOTO
    for env_var_name, env_var_value in filter(lambda x: x[0].startswith("GPHOTO"), os.environ.items()):
        # split out GPHOTO,filenameprefix and key from the env var
        _, filenameprefix, key = env_var_name.split("_", 2)
        # create the config dict entry if it doesnt exist
        if confs.get(filenameprefix, None) is None:
            confs[filenameprefix] = {"filenameprefix": filenameprefix}
        # set te
        confs[filenameprefix][key] = env_var_value
        
    try:

        workers = []
        # check output of the --auto-detect gphoto2 command.
        cams = detect_gphoto_info()
        for filenameprefix, conf in confs.items():
            try:
                filenameprefix = conf.get("filenameprefix", filenameprefix)
                if conf['gphotoserialnumber'] not in cams.keys():
                    continue
                camera = Camera.GPCamera(conf)
                workers.append(camera)
                logger.debug("Sucessfully detected {} @ {}".format(camera.serial_number, camera.usb_address))
                print("Sucessfully detected {} @ {}".format(camera.serial_number, camera.usb_address))
            except Exception as e:
                logger.debug("Exception detecting cameras! {}".format(str(e)))
        return tuple(workers)
    except subprocess.CalledProcessError as e:
        traceback.print_exc()
        logger.error("Subprocess error detecting gphoto2 cameras")
        logger.error(traceback.format_exc())
    return tuple


# def detect_webcam() -> tuple:
#     """
#     Detects usb web camers using the video4linux pyudev subsystem.
#
#     i.e. if the camera shows up as a /dev/videoX device, it sould be detected here.
#
#     :creates: :mod:`libs.Camera.USBCamera`, :mod:`libs.Uploader.Uploader`
#     :param updater: instance that has a `communication_queue` member that implements an `append` method
#     :type updater: Updater
#     :return: tuple of camera thread objects and associated uploader thread objects.
#     :rtype: tuple(USBCamera, Uploader)
#     """
#     try:
#         logger.info("Detecting USB web cameras.")
#         workers = []
#         for device in pyudev.Context().list_devices(subsystem="video4linux"):
#             serial = device.get("ID_SERIAL_SHORT", None)
#             if not serial:
#                 serial = device.get("ID_SERIAL", None)
#                 if len(serial) > 6:
#                     serial = serial[:6]
#                 logger.info("Detected USB camera. Using default machine id serial {}".format(str(serial)))
#             else:
#                 logger.info("Detected USB camera {}".format(str(serial)))
#
#             identifier = "USB-{}".format(serial)
#             sys_number = device.sys_number
#
#             try:
#                 # logger.warning("adding {} on {}".format(identifier, sys_number))
#                 camera = Camera.USBCamera(identifier=identifier,
#                                    sys_number=sys_number,
#                                    queue=updater.communication_queue)
#                 updater.add_to_temp_identifiers(camera.identifier)
#                 workers.append(camera)
#                 workers.append(Uploader(identifier, queue=updater.communication_queue))
#             except Exception as e:
#                 logger.error("Unable to start usb webcamera {} on {}".format(identifier, sys_number))
#                 logger.error("{}".format(str(e)))
#         return start_workers(tuple(workers))
#     except Exception as e:
#         logger.error("couldnt detect the usb cameras {}".format(str(e)))
#     return tuple()

def run_from_toml():
    config = toml.load("/etc/eyepi/eyepi.conf")
    workers = []
    rpiconf = config.get("rpicamera", None)
    if rpiconf:
        rpi = detect_picam(rpiconf)
        workers.extend(rpi)
    gphoto2_conf = config.get("gphoto", None)
    if gphoto2_conf:
        gphoto2cameras = detect_gphoto(gphoto2_conf)
        workers.extend(gphoto2cameras)
    return start_workers(workers)


def enumerate_usb_devices() -> set:
    """
    Gets a set of the current usb devices from pyudev

    :return: set of pyudev usb device objects
    :rtype: set(pyudev.Device)
    """
    return set(pyudev.Context().list_devices(subsystem="usb"))


def start_workers(worker_objects: tuple or list) -> tuple:
    """
    Starts threaded workers

    :param worker_objects: tuple of worker objects (threads)
    :return: tuple of started worker objects
    :rtype: tuple(threading.Thread)
    """
    logger.debug("Starting {} worker threads".format(str(len(worker_objects))))
    for thread in worker_objects:
        try:
            thread.daemon = True
            thread.start()
        except Exception as e:
            logger.error(traceback.format_exc())
            raise e
    return worker_objects


def kill_workers(worker_objects: tuple):
    """
    stops all workers

    calls the stop method of the workers (they should all implement this as they are threads).

    :param worker_objects:
    :type worker_objects: tuple(threading.Thread)
    """
    logger.debug("Killing {} worker threads".format(str(len(worker_objects))))
    for thread in worker_objects:
        thread.stop()

def main():
    logger.info("Program startup...")
    # The main loop for capture

    # these should be all detected at some point.
    global workers
    workers = tuple()
    try:
        global recent
        # start the updater. this is the first thing that should happen.
        recent = time.time()
        try:
            workers = run_from_toml()
        except Exception as e:
            logger.fatal(e)
            traceback.print_exc()
        # enumerate the usb devices to compare them later on.
        global glock
        glock = Lock()

        def recreate(action, event):
            # thes all need to be "globalised"
            global glock
            global workers
            global recent
            try:
                # use manual global lock.
                # this callback is from the observer thread, so we need to lock shared resources.
                if "gpio" in event.sys_name:
                    return

                if time.time() - 10 > recent and action in ['config_change', "add", "remove"]:

                    with glock:

                        print(event.device_path)
                        print(event.sys_path)
                        print(event.sys_name)

                        logger.warning("Recreating workers, {}".format(action))
                        kill_workers(workers)
                        workers = run_from_toml()
                        recent = time.time()
            except Exception as e:
                logger.fatal(e)
                traceback.print_exc()

        context = pyudev.Context()
        monitor = pyudev.Monitor.from_netlink(context)
        observer = pyudev.MonitorObserver(monitor, recreate)
        observer.start()

        while True:
            try:
                time.sleep(60 * 60 * 12)
            except (KeyboardInterrupt, SystemExit) as e:
                kill_workers(workers)
                raise e
            except Exception as e:
                logger.fatal(traceback.format_exc())
                logger.fatal("EMERGENCY! Other exception encountered. {}".format(str(e)))

    except (KeyboardInterrupt, SystemExit):
        print("exiting...")
        kill_workers(workers)
        sys.exit()
    except Exception as e:
        traceback.print_exc()
        logger.fatal("EMERGENCY! An exception occurred during worker dispatch: {}".format(str(e)))

if __name__ == "__main__":
    main()