import logging
from colorlog import ColoredFormatter


class Logger:
    LOG_LEVEL = {
        "critical": (logging.CRITICAL, "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"),
        "error": (logging.ERROR, "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"),
        "warning": (logging.WARNING, "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"),
        "info": (logging.INFO, "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"),
        "debug": (logging.DEBUG, f"%(pathname)s:%(lineno)d:\n%(asctime)s %(levelname)-8s [%(name)s] %(message)s"),
        "notset": (logging.NOTSET, "%(asctime)s %(levelname)-8s [%(name)s] %(message)s")
    }

    def __init__(self, log_level):
        self._date_fmt = "%d-%m-%Y:%H:%M:%S"
        self.log_level = self._get_log_level(log_level)
        self.log_format = self._get_log_format(log_level)
        self._config()

    def _get_log_level(self, log_level):
        return self.LOG_LEVEL[log_level][0]

    def _get_log_format(self, log_level):
        return self.LOG_LEVEL[log_level][1]

    def _config(self):
        """
        Configures logging using a colored formatter.
        """
        # Get the root logger
        root_logger = logging.getLogger()

        # Remove existing handlers, if any
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Create a console handler
        stream_handler = logging.StreamHandler()

        # Define the color scheme for different logging levels
        formatter = ColoredFormatter(
            "%(log_color)s" + self.log_format,
            datefmt=self._date_fmt,
            log_colors={
                'DEBUG': 'blue',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        )
        stream_handler.setFormatter(formatter)

        # Configure the root logger
        root_logger.setLevel(self.log_level)
        root_logger.addHandler(stream_handler)
