# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: GPL-3.0-only
"""A fake Panda Breath on localhost: the stock firmware's WebSocket server at /ws.

It records every settings object a client sends, pushes frames the way the device does, and can
reboot (drop every connection) or lose power (stop listening).
"""

import base64
import functools
import hashlib
import json
import socket
import struct
import threading

WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
ACCEPT_POLL_SECONDS = 0.1
CLOSE_OPCODE = 0x8
TEXT_FRAME_HEADER = 0x81
EXTENDED_LENGTH_MARKER = 126
LENGTH_BITS = 0x7F
OPCODE_BITS = 0x0F
DEFAULT_WAIT_SECONDS = 5.


def handshake_reply(request_headers):
    """The 101 reply to a client's upgrade request, with its Sec-WebSocket-Accept."""
    key_line = next(
        line for line in request_headers.split("\r\n")
        if line.lower().startswith("sec-websocket-key:"))
    client_key = key_line.split(":", 1)[1].strip()
    accept_digest = hashlib.sha1((client_key + WEBSOCKET_GUID).encode()).digest()
    accept_key = base64.b64encode(accept_digest).decode()
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key}\r\n"
        "\r\n"
    ).encode()


def receive_exact(client_socket, byte_count):
    received = bytearray()
    while len(received) < byte_count:
        chunk = client_socket.recv(byte_count - len(received))
        if not chunk:
            raise ConnectionError("client closed the connection")
        received.extend(chunk)
    return bytes(received)


def receive_request_headers(client_socket):
    request = b""
    while b"\r\n\r\n" not in request:
        chunk = client_socket.recv(1024)
        if not chunk:
            raise ConnectionError("client closed during the handshake")
        request += chunk
    return request.decode()


def receive_client_frame(client_socket):
    """Read one masked client frame; return its opcode and unmasked payload."""
    frame_header = receive_exact(client_socket, 2)
    opcode = frame_header[0] & OPCODE_BITS
    payload_length = frame_header[1] & LENGTH_BITS
    if payload_length == EXTENDED_LENGTH_MARKER:
        payload_length = struct.unpack("!H", receive_exact(client_socket, 2))[0]
    mask_key = receive_exact(client_socket, 4)
    masked_payload = receive_exact(client_socket, payload_length)
    payload = bytes(
        payload_byte ^ mask_key[index % 4] for index, payload_byte in enumerate(masked_payload))
    return opcode, payload


def server_text_frame(settings):
    """A device frame: unmasked text, {"settings": settings}."""
    payload = json.dumps({"settings": settings}).encode()
    if len(payload) < EXTENDED_LENGTH_MARKER:
        return struct.pack("!BB", TEXT_FRAME_HEADER, len(payload)) + payload
    return struct.pack("!BBH", TEXT_FRAME_HEADER, EXTENDED_LENGTH_MARKER, len(payload)) + payload


class FakePandaBreath:
    def __init__(self):
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.listener.settimeout(ACCEPT_POLL_SECONDS)
        self.port = self.listener.getsockname()[1]
        self.condition = threading.Condition()
        self.received_settings = []
        self.open_connections = []
        self.connections_opened = 0
        self.listening = True
        self.accept_thread = threading.Thread(
            target=self._accept_loop, name="fake_panda_breath", daemon=True)
        self.accept_thread.start()

    def _accept_loop(self):
        while self.listening:
            self._accept_one()

    def _accept_one(self):
        try:
            client_socket, _client_address = self.listener.accept()
        except OSError:
            # The accept timeout lets the loop see a power off; a closed listener ends it the
            # same way.
            return
        threading.Thread(
            target=self._serve, args=(client_socket,), name="fake_panda_breath_client",
            daemon=True).start()

    def _serve(self, client_socket):
        try:
            client_socket.sendall(handshake_reply(receive_request_headers(client_socket)))
            self._open(client_socket)
            self._record_frames(client_socket)
        except OSError:
            # A reboot, a power off or the client hanging up ends a connection this way.
            return
        finally:
            self._close(client_socket)

    def _open(self, client_socket):
        with self.condition:
            self.open_connections.append(client_socket)
            self.connections_opened += 1
            self.condition.notify_all()

    def _close(self, client_socket):
        with self.condition:
            if client_socket in self.open_connections:
                self.open_connections.remove(client_socket)
            self.condition.notify_all()
        client_socket.close()

    def _record_frames(self, client_socket):
        opcode, payload = receive_client_frame(client_socket)
        while opcode != CLOSE_OPCODE:
            self._record(json.loads(payload)["settings"])
            opcode, payload = receive_client_frame(client_socket)

    def _record(self, settings):
        with self.condition:
            self.received_settings.append(settings)
            self.condition.notify_all()

    def push(self, settings):
        """Send a frame to every connected client, as the device reports its state."""
        with self.condition:
            connections = list(self.open_connections)
        for client_socket in connections:
            send_ignoring_closed(client_socket, server_text_frame(settings))

    def wait_until(self, condition_holds, timeout=DEFAULT_WAIT_SECONDS):
        """Wait until condition_holds(self) is true; return whether it became true in time."""
        with self.condition:
            return self.condition.wait_for(functools.partial(condition_holds, self), timeout)

    def mark(self):
        with self.condition:
            return len(self.received_settings)

    def received_since(self, mark):
        with self.condition:
            return self.received_settings[mark:]

    def reboot(self):
        """Drop every connection, as the device does when it restarts."""
        with self.condition:
            connections = list(self.open_connections)
        for client_socket in connections:
            shutdown_ignoring_closed(client_socket)

    def power_off(self):
        """Stop answering at all: no listener and no connections."""
        self.listening = False
        self.listener.close()
        self.accept_thread.join()
        self.reboot()

    def stop(self):
        if self.listening:
            self.power_off()


def send_ignoring_closed(client_socket, frame):
    try:
        client_socket.sendall(frame)
    except OSError:
        # The client dropped the connection between the copy of the list and this send; the device
        # loses that frame the same way.
        return


def shutdown_ignoring_closed(client_socket):
    try:
        client_socket.shutdown(socket.SHUT_RDWR)
    except OSError:
        # Already closed by the client: there is nothing left to drop.
        return
