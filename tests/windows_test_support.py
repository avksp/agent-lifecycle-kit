"""Shared portable test fixtures; none of these qualify a native host.

Windows permissions are inspected through real ACLs and Python text fixtures
use explicit process injection. POSIX assertions keep their actual mode bits.
"""

from tests.adapter_sessions.test_windows_pipe import (
    assert_private_path,
    install_windows_fixture_process,
    process_is_running,
)
from tests.contracts.test_private_storage import unsafe_private_access

__all__ = [
    "assert_private_path",
    "install_windows_fixture_process",
    "process_is_running",
    "unsafe_private_access",
]
