"""Tests for the base class of the Volumio clients.

:copyright: Copyright (C) 2025-2026 Alberto Pettarin
:license: GNU General Public License v3.0 (see the LICENSE file for details)
"""

import logging
from unittest.mock import Mock

from volumito.clients import VolumioBaseClient


class TestVolumioBaseClient:
    """Test cases for the VolumioBaseClient class."""

    def test_init_default_logger(self):
        """Without a logger, the client logs under the name of its own module."""
        client = VolumioBaseClient()

        assert client.logger.name == "volumito.clients.base"

    def test_init_custom_logger(self):
        """A passed logger is stored as given."""
        logger = logging.getLogger("test.base.custom")

        client = VolumioBaseClient(logger=logger)

        assert client.logger is logger

    def test_the_log_helpers_forward_to_their_levels(self):
        """Each helper logs its message at the matching level."""
        logger = Mock()
        client = VolumioBaseClient(logger=logger)

        client._log_critical("c")
        client._log_debug("d")
        client._log_error("e")
        client._log_exception("x")
        client._log_info("i")
        client._log_warning("w")

        logger.critical.assert_called_once_with("c")
        logger.debug.assert_called_once_with("d")
        logger.error.assert_called_once_with("e")
        logger.exception.assert_called_once_with("x")
        logger.info.assert_called_once_with("i")
        logger.warning.assert_called_once_with("w")
