# Copyright 2025 Flower Labs GmbH. All Rights Reserved.
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
"""Flower command line interface `stop` command."""


from typing import Annotated, Literal

import click
import typer

from flwr.cli.config_migration import migrate, warn_if_federation_config_overrides
from flwr.cli.constant import FEDERATION_CONFIG_HELP_MESSAGE
from flwr.cli.flower_config import read_superlink_connection
from flwr.common.constant import CliOutputFormat, Status
from flwr.proto.control_pb2 import (  # pylint: disable=E0611
    ListRunsRequest,
    ListRunsResponse,
    StopRunRequest,
    StopRunResponse,
)
from flwr.proto.control_pb2_grpc import ControlStub

from .utils import (
    cli_output_handler,
    flwr_cli_grpc_exc_handler,
    init_channel_from_connection,
    print_json_to_stdout,
)


def stop(  # pylint: disable=R0914
    ctx: typer.Context,
    run_id: Annotated[  # pylint: disable=unused-argument
        str,
        typer.Argument(help="The Flower run ID to stop, or 'latest' or 'all'"),
    ],
    superlink: Annotated[
        str | None,
        typer.Argument(help="Name of the SuperLink connection."),
    ] = None,
    federation_config_overrides: Annotated[
        list[str] | None,
        typer.Option(
            "--federation-config",
            help=FEDERATION_CONFIG_HELP_MESSAGE,
            hidden=True,
        ),
    ] = None,
    output_format: Annotated[
        Literal["default", "json"],
        typer.Option(
            "--format",
            case_sensitive=False,
            help="Format output using 'default' view or 'json'",
        ),
    ] = CliOutputFormat.DEFAULT,
) -> None:
    """Stop a Flower run.

    This command stops a running Flower App execution by sending a stop request to the
    SuperLink via the Control API.
    """
    with cli_output_handler(output_format=output_format) as is_json:
        # Warn `--federation-config` is ignored
        warn_if_federation_config_overrides(federation_config_overrides)

        migrate(superlink, args=ctx.args)

        # Read superlink connection configuration
        superlink_connection = read_superlink_connection(superlink)
        channel = None

        try:
            channel = init_channel_from_connection(superlink_connection)
            stub = ControlStub(channel)  # pylint: disable=unused-variable # noqa: F841

            run_ids = _resolve_run_ids(stub, run_id)
            stop_all = run_id.lower() == "all"
            _stop_runs(stub, run_ids, is_json, stop_all)

        finally:
            if channel:
                channel.close()


def _resolve_run_ids(stub: ControlStub, run_id: str) -> list[int]:
    """Resolve a numeric run ID or a selector to active run IDs."""
    selector = run_id.lower()
    if selector not in ("latest", "all"):
        try:
            resolved_run_id = int(run_id)
        except ValueError:
            raise click.ClickException(
                "RUN_ID must be an integer, 'latest', or 'all'."
            ) from None
        if resolved_run_id < 0:
            raise click.ClickException("RUN_ID must be a non-negative integer.")
        return [resolved_run_id]

    with flwr_cli_grpc_exc_handler():
        response: ListRunsResponse = stub.ListRuns(ListRunsRequest())
    active_runs = sorted(
        (
            run
            for run in response.run_dict.values()
            if run.status.status != Status.FINISHED
        ),
        key=lambda run: run.pending_at,
        reverse=True,
    )
    if not active_runs:
        raise click.ClickException("No active runs found.")

    if selector == "latest":
        return [active_runs[0].run_id]
    return [run.run_id for run in active_runs]


def _stop_runs(
    stub: ControlStub, run_ids: list[int], is_json: bool, stop_all: bool
) -> None:
    """Stop resolved run IDs and display the result."""
    failures = []
    for run_id in run_ids:
        typer.secho(f"✋ Stopping run ID {run_id}...", fg=typer.colors.GREEN)
        try:
            _stop_run(stub=stub, run_id=run_id, is_json=is_json and not stop_all)
        except click.ClickException as err:
            if not stop_all:
                raise
            failures.append(f"Run {run_id}: {err.format_message()}")

    if failures:
        raise click.ClickException("Failed to stop all runs:\n" + "\n".join(failures))

    if is_json and stop_all:
        print_json_to_stdout(
            {
                "success": True,
                "run-ids": [str(run_id) for run_id in run_ids],
            }
        )


def _stop_run(stub: ControlStub, run_id: int, is_json: bool) -> None:
    """Stop a run and display the result.

    Parameters
    ----------
    stub : ControlStub
        The gRPC stub for Control API communication.
    run_id : int
        The unique identifier of the run to stop.
    is_json : bool
        Whether JSON output format is requested.
    """
    with flwr_cli_grpc_exc_handler():
        response: StopRunResponse = stub.StopRun(request=StopRunRequest(run_id=run_id))
    if response.success:
        typer.secho(f"✅ Run {run_id} successfully stopped.", fg=typer.colors.GREEN)
        if is_json:
            print_json_to_stdout(
                {
                    "success": True,
                    "run-id": f"{run_id}",
                }
            )
    else:
        raise click.ClickException(f"Run {run_id} couldn't be stopped.")
