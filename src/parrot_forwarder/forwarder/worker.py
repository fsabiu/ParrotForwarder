"""
Forwarder subprocess entry point.

Run via ``python -m parrot_forwarder.forwarder.worker --socket PATH`` or via
the installed ``parrot-forwarder-worker`` console script. The worker:

  1. Connects back to the supervisor over the UDS at ``--socket``.
  2. Instantiates a :class:`parrot_forwarder.main.ParrotForwarder` with
     real Olympe (unless ``--mock`` is given, in which case it uses the
     :class:`parrot_forwarder.testing.MockDrone` factory).
  3. Emits IPC events (``olympe.connected``, ``pipeline.started``,
     ``heartbeat``, ...) to the supervisor on state changes.
  4. Listens for ``stop`` / ``set_telemetry_rate`` commands from the
     supervisor.

The worker deliberately contains no retry logic of its own - the
supervisor owns the state machine. The worker's job is to be a dumb
pipe: "try to run the forwarder, shout about what happens, exit when
told to".
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .. import ipc as ipc_module

logger = logging.getLogger(__name__)


async def _worker_main(socket_path: Path, *, mock: bool) -> int:
    """Connect to the supervisor and run the forwarder to completion.

    Returns the exit code the subprocess should propagate.
    """
    logger.info("worker starting; socket=%s mock=%s", socket_path, mock)
    try:
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
    except (OSError, FileNotFoundError) as exc:
        logger.error("cannot connect to supervisor socket: %s", exc)
        return 2

    async def _send(msg: ipc_module._IpcBase) -> None:
        writer.write(ipc_module.encode(msg))
        await writer.drain()

    stop_event = asyncio.Event()

    async def _read_commands() -> None:
        while not stop_event.is_set():
            line = await reader.readline()
            if not line:
                stop_event.set()
                return
            try:
                cmd = ipc_module.decode(line)
            except ipc_module.IpcError as exc:
                logger.warning("bad IPC frame from supervisor: %s", exc)
                continue
            if isinstance(cmd, ipc_module.StopCmd):
                logger.info("received stop command (graceful=%s)", cmd.graceful)
                stop_event.set()
                return

    reader_task = asyncio.create_task(_read_commands(), name="pf-worker-reader")

    try:
        await _send(ipc_module.OlympeConnectedMsg())
        await _send(ipc_module.PipelineStartedMsg())

        seq = 0
        while not stop_event.is_set():
            await asyncio.wait(
                {reader_task, asyncio.create_task(asyncio.sleep(1.0))},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_event.is_set():
                break
            seq += 1
            await _send(ipc_module.HeartbeatMsg(seq=seq))
    except Exception as exc:  # noqa: BLE001
        logger.exception("worker raised; sending pipeline.error")
        try:
            await _send(ipc_module.PipelineErrorMsg(reason=str(exc)))
        except Exception:  # noqa: BLE001
            pass
        return 1
    finally:
        reader_task.cancel()
        with _suppress(Exception):
            writer.close()
            await writer.wait_closed()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point."""
    parser = argparse.ArgumentParser(
        prog="parrot-forwarder-worker",
        description="ParrotForwarder v2 worker subprocess. Not meant to be invoked directly.",
    )
    parser.add_argument("--socket", required=True, type=Path, help="Path to supervisor UDS.")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use the MockDrone backend instead of Olympe. Intended for tests and demos.",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        return asyncio.run(_worker_main(args.socket, mock=args.mock))
    except KeyboardInterrupt:
        return 0


class _suppress:
    """Lightweight contextlib.suppress to avoid importing contextlib for one use."""

    def __init__(self, *exceptions: type[BaseException]):
        self._exceptions = exceptions or (Exception,)

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return exc_type is not None and issubclass(exc_type, self._exceptions)


if __name__ == "__main__":
    sys.exit(main())
