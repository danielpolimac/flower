# Copyright 2026 Flower Labs GmbH. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for Flower command line interface `stop` command."""


from unittest.mock import MagicMock

import click
import pytest

from flwr.common.constant import Status
from flwr.proto.control_pb2 import ListRunsResponse  # pylint: disable=E0611
from flwr.proto.run_pb2 import Run, RunStatus  # pylint: disable=E0611

from .stop import _resolve_run_ids


def _run(run_id: int, status: str, pending_at: str) -> Run:
    return Run(
        run_id=run_id,
        status=RunStatus(status=status),
        pending_at=pending_at,
    )


def test_resolve_run_ids_returns_numeric_id_without_listing_runs() -> None:
    """A numeric run ID should not require a ListRuns request."""
    stub = MagicMock()

    assert _resolve_run_ids(stub, "123") == [123]
    stub.ListRuns.assert_not_called()


def test_resolve_run_ids_returns_latest_active_run() -> None:
    """The latest selector should skip newer finished runs."""
    stub = MagicMock()
    stub.ListRuns.return_value = ListRunsResponse(
        run_dict={
            1: _run(1, Status.RUNNING, "2026-08-20T10:00:00+00:00"),
            2: _run(2, Status.FINISHED, "2026-08-20T12:00:00+00:00"),
            3: _run(3, Status.PENDING, "2026-08-20T11:00:00+00:00"),
        }
    )

    assert _resolve_run_ids(stub, "latest") == [3]


def test_resolve_run_ids_returns_all_active_runs_newest_first() -> None:
    """The all selector should return active runs ordered by creation time."""
    stub = MagicMock()
    stub.ListRuns.return_value = ListRunsResponse(
        run_dict={
            1: _run(1, Status.RUNNING, "2026-08-20T10:00:00+00:00"),
            2: _run(2, Status.FINISHED, "2026-08-20T12:00:00+00:00"),
            3: _run(3, Status.STARTING, "2026-08-20T11:00:00+00:00"),
        }
    )

    assert _resolve_run_ids(stub, "all") == [3, 1]


@pytest.mark.parametrize("run_id", ["newest", "-1"])
def test_resolve_run_ids_rejects_invalid_run_id(run_id: str) -> None:
    """Unknown selectors and negative run IDs should be rejected clearly."""
    with pytest.raises(click.ClickException):
        _resolve_run_ids(MagicMock(), run_id)


def test_resolve_run_ids_rejects_selector_without_active_runs() -> None:
    """Selectors should fail clearly if all runs have finished."""
    stub = MagicMock()
    stub.ListRuns.return_value = ListRunsResponse(
        run_dict={
            1: _run(1, Status.FINISHED, "2026-08-20T10:00:00+00:00"),
        }
    )

    with pytest.raises(click.ClickException, match="No active runs found"):
        _resolve_run_ids(stub, "all")
