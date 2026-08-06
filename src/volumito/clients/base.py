"""Base class of the Volumio clients.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import logging


class VolumioBaseClient:
    """Base class of the Volumio clients, holding their logger.

    The derived clients log through the ``_log_*`` helpers, so every record goes to
    the logger the caller passed, or to the one named after the module of the client
    itself, a child of the ``volumito`` logger.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        """Initialize the base client.

        Args:
            logger: The logger the client writes to; without one, the client logs
                under the name of its own module in the ``volumito`` hierarchy
        """
        self.logger = (
            logger if logger is not None else logging.getLogger(type(self).__module__)
        )

    def _log_critical(self, message: str) -> None:
        """Log a critical message.

        Args:
            message: The message to log
        """
        self.logger.critical(message)

    def _log_debug(self, message: str) -> None:
        """Log a debug message.

        Args:
            message: The message to log
        """
        self.logger.debug(message)

    def _log_error(self, message: str) -> None:
        """Log an error message.

        Args:
            message: The message to log
        """
        self.logger.error(message)

    def _log_exception(self, message: str) -> None:
        """Log an error message with the exception being handled attached.

        To be called from an ``except`` block, whose exception joins the record as
        its traceback.

        Args:
            message: The message to log
        """
        self.logger.exception(message)

    def _log_info(self, message: str) -> None:
        """Log an informational message.

        Args:
            message: The message to log
        """
        self.logger.info(message)

    def _log_warning(self, message: str) -> None:
        """Log a warning message.

        Args:
            message: The message to log
        """
        self.logger.warning(message)
