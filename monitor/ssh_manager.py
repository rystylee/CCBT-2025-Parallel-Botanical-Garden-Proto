"""SSH connection manager for remote device access and command broadcast."""

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import paramiko
from loguru import logger


@dataclass
class SSHSession:
    """Represents an active SSH session to a device."""

    device_id: int
    host: str
    client: paramiko.SSHClient
    channel: paramiko.Channel
    active: bool = True


@dataclass
class CommandResult:
    """Result of a command executed on a device."""

    device_id: int
    host: str
    exit_code: int
    stdout: str
    stderr: str
    success: bool
    elapsed: float = 0.0


class SSHManager:
    """Manages SSH connections to BI devices."""

    DEFAULT_USERNAME = "m5stack"
    DEFAULT_PORT = 22
    CONNECT_TIMEOUT = 10
    EXEC_TIMEOUT = 30

    def __init__(
        self,
        username: str = DEFAULT_USERNAME,
        password: Optional[str] = None,
        key_path: Optional[str] = None,
        port: int = DEFAULT_PORT,
    ):
        self.username = username
        self.password = password
        self.key_path = key_path
        self.port = port
        self.sessions: Dict[str, SSHSession] = {}  # sid -> SSHSession
        self._lock = threading.Lock()

    def _create_client(self, host: str) -> paramiko.SSHClient:
        """Create and configure an SSH client."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": host,
            "port": self.port,
            "username": self.username,
            "timeout": self.CONNECT_TIMEOUT,
        }

        if self.key_path:
            connect_kwargs["key_filename"] = self.key_path
        elif self.password:
            connect_kwargs["password"] = self.password

        client.connect(**connect_kwargs)
        return client

    def open_interactive(
        self, sid: str, device_id: int, host: str
    ) -> Optional[SSHSession]:
        """
        Open an interactive SSH shell session for use with a web terminal.

        Args:
            sid: Socket.IO session ID (unique key for the session)
            device_id: Device ID number
            host: IP address of the device

        Returns:
            SSHSession if successful, None otherwise
        """
        try:
            client = self._create_client(host)
            channel = client.invoke_shell(term="xterm-256color", width=120, height=40)
            channel.settimeout(0.1)

            session = SSHSession(
                device_id=device_id,
                host=host,
                client=client,
                channel=channel,
            )

            with self._lock:
                # Close existing session for this sid if any
                self.close_interactive(sid)
                self.sessions[sid] = session

            logger.info(f"Interactive SSH session opened: device={device_id} host={host} sid={sid}")
            return session

        except Exception as e:
            logger.error(f"Failed to open SSH to {host} (device {device_id}): {e}")
            return None

    def close_interactive(self, sid: str) -> None:
        """Close an interactive SSH session."""
        with self._lock:
            session = self.sessions.pop(sid, None)

        if session:
            try:
                session.active = False
                session.channel.close()
                session.client.close()
                logger.info(f"SSH session closed: device={session.device_id} sid={sid}")
            except Exception as e:
                logger.warning(f"Error closing SSH session {sid}: {e}")

    def get_session(self, sid: str) -> Optional[SSHSession]:
        """Get an active session by socket ID."""
        with self._lock:
            return self.sessions.get(sid)

    def write_to_session(self, sid: str, data: str) -> bool:
        """Send data (keystrokes) to an interactive session."""
        session = self.get_session(sid)
        if session and session.active:
            try:
                session.channel.send(data)
                return True
            except Exception as e:
                logger.error(f"Write error for session {sid}: {e}")
                self.close_interactive(sid)
        return False

    def read_from_session(self, sid: str) -> Optional[str]:
        """Read available data from an interactive session."""
        session = self.get_session(sid)
        if session and session.active:
            try:
                if session.channel.recv_ready():
                    data = session.channel.recv(4096)
                    return data.decode("utf-8", errors="replace")
            except Exception:
                pass
        return None

    def resize_session(self, sid: str, cols: int, rows: int) -> None:
        """Resize the terminal for a session."""
        session = self.get_session(sid)
        if session and session.active:
            try:
                session.channel.resize_pty(width=cols, height=rows)
            except Exception as e:
                logger.warning(f"Resize error for session {sid}: {e}")

    def exec_command(self, host: str, device_id: int, command: str) -> CommandResult:
        """
        Execute a single command on a device (non-interactive).

        Used by the broadcast feature.
        """
        start = time.time()
        try:
            client = self._create_client(host)
            stdin, stdout, stderr = client.exec_command(
                command, timeout=self.EXEC_TIMEOUT
            )
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            client.close()

            elapsed = time.time() - start
            return CommandResult(
                device_id=device_id,
                host=host,
                exit_code=exit_code,
                stdout=out,
                stderr=err,
                success=(exit_code == 0),
                elapsed=elapsed,
            )
        except Exception as e:
            elapsed = time.time() - start
            return CommandResult(
                device_id=device_id,
                host=host,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                success=False,
                elapsed=elapsed,
            )

    def broadcast_command(
        self,
        targets: List[Dict],
        command: str,
        on_result: Optional[Callable[[CommandResult], None]] = None,
        parallel: bool = True,
    ) -> List[CommandResult]:
        """
        Execute a command on multiple devices.

        Args:
            targets: List of dicts with 'device_id' and 'host' keys
            command: Shell command to execute
            on_result: Optional callback for each result (for streaming updates)
            parallel: If True, execute on all targets concurrently

        Returns:
            List of CommandResult
        """
        results: List[CommandResult] = []
        lock = threading.Lock()

        def _run_one(target):
            result = self.exec_command(target["host"], target["device_id"], command)
            with lock:
                results.append(result)
            if on_result:
                on_result(result)

        if parallel:
            threads = []
            for t in targets:
                th = threading.Thread(target=_run_one, args=(t,))
                th.start()
                threads.append(th)
            for th in threads:
                th.join(timeout=self.EXEC_TIMEOUT + 5)
        else:
            for t in targets:
                _run_one(t)

        return results

    def cleanup_all(self) -> None:
        """Close all open sessions."""
        with self._lock:
            sids = list(self.sessions.keys())

        for sid in sids:
            self.close_interactive(sid)

        logger.info("All SSH sessions cleaned up")
