"""Desktop streaming with WebRTC and Neko binary protocol."""

from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.rtcconfiguration import RTCConfiguration
from aiortc.rtcicetransport import RTCIceCandidate

# Neko binary protocol opcodes (Big Endian, v3)
# Reference: https://github.com/demodesk/neko-client/blob/37f93eae6bd55b333c94bd009d7f2b079075a026/src/component/internal/webrtc.ts
NEKO_OP_MOVE = 0x01
NEKO_OP_SCROLL = 0x02
NEKO_OP_KEY_DOWN = 0x03
NEKO_OP_KEY_UP = 0x04
NEKO_OP_BTN_DOWN = 0x05
NEKO_OP_BTN_UP = 0x06

# X11 mouse button mapping
def _mouse_button_to_x11(button: str | None) -> int:
    """Convert mouse button name to X11 button number."""
    mapping = {
        "middle": 2,
        "right": 3,
    }
    return mapping.get(button, 1)


# X11 keysym mapping for special keys
KEYSYM_MAP: dict[str, int] = {
    "Backspace": 0xFF08,
    "Tab": 0xFF09,
    "Return": 0xFF0D,
    "Enter": 0xFF0D,
    "Escape": 0xFF1B,
    "Delete": 0xFFFF,
    "Home": 0xFF50,
    "Left": 0xFF51,
    "ArrowLeft": 0xFF51,
    "Up": 0xFF52,
    "ArrowUp": 0xFF52,
    "Right": 0xFF53,
    "ArrowRight": 0xFF53,
    "Down": 0xFF54,
    "ArrowDown": 0xFF54,
    "PageUp": 0xFF55,
    "PageDown": 0xFF56,
    "End": 0xFF57,
    "Insert": 0xFF63,
    "F1": 0xFFBE,
    "F2": 0xFFBF,
    "F3": 0xFFC0,
    "F4": 0xFFC1,
    "F5": 0xFFC2,
    "F6": 0xFFC3,
    "F7": 0xFFC4,
    "F8": 0xFFC5,
    "F9": 0xFFC6,
    "F10": 0xFFC7,
    "F11": 0xFFC8,
    "F12": 0xFFC9,
    "Shift": 0xFFE1,
    "ShiftLeft": 0xFFE1,
    "ShiftRight": 0xFFE2,
    "Control": 0xFFE3,
    "ControlLeft": 0xFFE3,
    "ControlRight": 0xFFE4,
    "Alt": 0xFFE9,
    "AltLeft": 0xFFE9,
    "AltRight": 0xFFEA,
    "Meta": 0xFFEB,
    "MetaLeft": 0xFFEB,
    "MetaRight": 0xFFEC,
    "CapsLock": 0xFFE5,
    "NumLock": 0xFF7F,
    "ScrollLock": 0xFF14,
    " ": 0x0020,
    "Space": 0x0020,
}


def _key_to_x11_keysym(key: str) -> int:
    """Convert key string to X11 keysym value."""
    # Check special keys first
    if key in KEYSYM_MAP:
        return KEYSYM_MAP[key]

    # Single ASCII character
    if len(key) == 1:
        code_point = ord(key)
        if 0x20 <= code_point <= 0x7E:
            return code_point
        # Unicode keysym
        return 0x01000000 + code_point

    return 0


@dataclass
class DesktopStreamReadyStatus:
    """Status indicating the desktop stream is ready."""

    type: str
    width: int
    height: int


@dataclass
class DesktopStreamErrorStatus:
    """Status indicating a desktop stream error."""

    type: str
    message: str


DesktopStreamStatusMessage = DesktopStreamReadyStatus | DesktopStreamErrorStatus


class DesktopNotSupportedError(Exception):
    """Raised when desktop streaming is not supported on the current platform.

    This typically occurs when the server returns HTTP 501 Not Implemented,
    indicating that desktop APIs are only available on Linux sandboxes.
    """

    def __init__(self, message: str = "Desktop streaming is not supported on this platform. Only Linux sandboxes support desktop APIs.") -> None:
        super().__init__(message)
        self.message = message


class DesktopStreamSession:
    """WebRTC desktop streaming session with Neko binary protocol input.

    This class manages a WebRTC connection to a desktop stream, handling:
    - Signaling via WebSocket
    - ICE negotiation
    - Media stream reception
    - Input events (mouse, keyboard) via Neko binary protocol

    Example:
        session = await agent.start_desktop()

        # Listen for video stream
        def on_track(track):
            print(f"Received track: {track}")
        session.on_track(on_track)

        # Wait for ready
        def on_ready(status):
            print(f"Desktop ready: {status.width}x{status.height}")
        session.on_ready(on_ready)

        # Send input
        session.move_mouse(100, 200)
        session.mouse_click("left")
        session.key_press("Enter")

        # Cleanup
        session.close()
    """

    def __init__(
        self,
        websocket: Any,
        *,
        rtc_config: RTCConfiguration | None = None,
    ) -> None:
        """Initialize the desktop stream session.

        Args:
            websocket: WebSocket connection for signaling (from websockets library)
            rtc_config: Optional RTC configuration for the peer connection
        """
        self._websocket = websocket
        self._rtc_config = rtc_config or RTCConfiguration(
            iceServers=[{"urls": "stun:stun.l.google.com:19302"}]
        )

        # WebRTC components
        self._pc: RTCPeerConnection | None = None
        self._data_channel: Any | None = None
        self._media_stream: Any | None = None
        self._connected = False
        self._pending_candidates: list[dict[str, Any]] = []
        self._cached_ready_status: DesktopStreamReadyStatus | None = None

        # Event listeners
        self._ready_listeners: set[Callable[[DesktopStreamReadyStatus], None]] = set()
        self._track_listeners: set[Callable[[Any], None]] = set()
        self._connect_listeners: set[Callable[[], None]] = set()
        self._disconnect_listeners: set[Callable[[], None]] = set()
        self._error_listeners: set[Callable[[DesktopStreamErrorStatus | Exception], None]] = set()

        # Closed state
        self._closed = False
        self._closed_future: asyncio.Future[None] = asyncio.get_event_loop().create_future()

        # Start message handler
        self._message_task: asyncio.Task[None] | None = None

    @property
    def closed(self) -> asyncio.Future[None]:
        """Future that resolves when the session is closed."""
        return self._closed_future

    def on_ready(self, listener: Callable[[DesktopStreamReadyStatus], None]) -> Callable[[DesktopStreamReadyStatus], None]:
        """Register a callback for when the desktop stream is ready.

        Args:
            listener: Callback function that receives the ready status.

        Returns:
            The registered handler (for use as a decorator).
        """
        self._ready_listeners.add(listener)
        # Deliver cached status to late listeners
        if self._cached_ready_status:
            listener(self._cached_ready_status)
        return listener

    def on_track(self, listener: Callable[[Any], None]) -> Callable[[Any], None]:
        """Register a callback for incoming media tracks.

        Args:
            listener: Callback function that receives the media stream/track.

        Returns:
            The registered handler (for use as a decorator).
        """
        self._track_listeners.add(listener)
        if self._media_stream:
            listener(self._media_stream)
        return listener

    def on_connect(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for when the WebRTC connection is established.

        Args:
            listener: Callback function with no arguments.

        Returns:
            The registered handler (for use as a decorator).
        """
        self._connect_listeners.add(listener)
        return listener

    def on_disconnect(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for when the WebRTC connection closes.

        Args:
            listener: Callback function with no arguments.

        Returns:
            The registered handler (for use as a decorator).
        """
        self._disconnect_listeners.add(listener)
        return listener

    def on_error(self, listener: Callable[[DesktopStreamErrorStatus | Exception], None]) -> Callable[[DesktopStreamErrorStatus | Exception], None]:
        """Register a callback for errors.

        Args:
            listener: Callback function that receives error information.

        Returns:
            The registered handler (for use as a decorator).
        """
        self._error_listeners.add(listener)
        return listener

    def get_media_stream(self) -> Any | None:
        """Get the current media stream if available."""
        return self._media_stream

    async def start(self) -> None:
        """Start the desktop stream session.

        This begins listening for WebSocket messages and initiates the
        WebRTC connection process.
        """
        self._message_task = asyncio.create_task(self._message_loop())

    async def _message_loop(self) -> None:
        """Main loop for handling WebSocket messages."""
        try:
            async for message in self._websocket:
                if isinstance(message, str):
                    await self._handle_message(message)
        except Exception as e:
            self._emit_error(e)
        finally:
            self._teardown_peer_connection()
            if not self._closed_future.done():
                self._closed_future.set_result(None)
            for listener in self._disconnect_listeners:
                try:
                    listener()
                except Exception:
                    pass

    async def _handle_message(self, data: str) -> None:
        """Handle a signaling message from the server."""
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            return

        event = msg.get("event", "")
        payload = msg.get("payload") or msg.get("data")

        if event == "system/init":
            await self._handle_system_init(payload)
        elif event in ("signal/provide", "signal/offer") or event == "signal/restart":
            await self._handle_signal_offer(payload)
        elif event == "signal/candidate":
            await self._handle_signal_candidate(payload)
        elif event == "signal/close":
            self._teardown_peer_connection()
        elif event == "system/disconnect":
            message = payload.get("message") if payload else None
            self._emit_error(Exception(message or "Server disconnected"))
            self.close()

    async def _handle_system_init(self, payload: dict[str, Any] | None) -> None:
        """Handle system/init message with screen size info."""
        if not payload:
            return

        screen_data = payload.get("screen_size")
        if screen_data:
            status = DesktopStreamReadyStatus(
                type="ready",
                width=int(screen_data.get("width", 0)),
                height=int(screen_data.get("height", 0)),
            )
            self._cached_ready_status = status
            for listener in self._ready_listeners:
                try:
                    listener(status)
                except Exception:
                    pass

        # Request control and signal
        await self._send_signaling("control/request", {})
        await self._send_signaling("signal/request", {"video": {}, "audio": {}})

    async def _handle_signal_offer(self, payload: dict[str, Any] | None) -> None:
        """Handle WebRTC offer from server."""
        if not payload or not payload.get("sdp"):
            return

        try:
            # Extract ICE servers from offer
            ice_servers = []
            neko_ice = payload.get("iceservers") or payload.get("ice")
            if neko_ice:
                for server in neko_ice:
                    if server.get("urls"):
                        ice_servers.append({"urls": server["urls"]})

            if not ice_servers:
                ice_servers = [{"urls": "stun:stun.l.google.com:19302"}]

            # Create peer connection
            config = RTCConfiguration(iceServers=ice_servers)
            self._pc = RTCPeerConnection(configuration=config)

            # Set up track handler
            @self._pc.on("track")
            def on_track(track: Any) -> None:
                self._media_stream = track
                for listener in self._track_listeners:
                    try:
                        listener(track)
                    except Exception:
                        pass

            # Set up ICE candidate handler
            @self._pc.on("icecandidate")
            async def on_icecandidate(candidate: RTCIceCandidate) -> None:
                if candidate:
                    await self._send_signaling("signal/candidate", {
                        "candidate": candidate.candidate,
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex,
                    })

            # Set up connection state handler
            @self._pc.on("connectionstatechange")
            async def on_connectionstatechange() -> None:
                if self._pc:
                    state = self._pc.connectionState
                    if state == "connected" and not self._connected:
                        self._connected = True
                        for listener in self._connect_listeners:
                            try:
                                listener()
                            except Exception:
                                pass
                    elif state in ("closed", "failed"):
                        self._emit_error(Exception(f"WebRTC connection {state}"))

            # Set up data channel handler (server creates channels in Neko v3)
            @self._pc.on("datachannel")
            def on_datachannel(channel: Any) -> None:
                self._data_channel = channel

            # Set remote description
            offer = RTCSessionDescription(sdp=payload["sdp"], type="offer")
            await self._pc.setRemoteDescription(offer)

            # Flush pending candidates
            for pending in self._pending_candidates:
                try:
                    candidate = RTCIceCandidate(
                        sdp=pending.get("candidate"),
                        sdpMid=pending.get("sdpMid"),
                        sdpMLineIndex=pending.get("sdpMLineIndex"),
                    )
                    await self._pc.addIceCandidate(candidate)
                except Exception:
                    pass
            self._pending_candidates = []

            # Create answer
            answer = await self._pc.createAnswer()

            # Enable stereo audio for Chromium
            if answer.sdp:
                answer.sdp = answer.sdp.replace(
                    "useinbandfec=1",
                    "useinbandfec=1;stereo=1"
                )

            await self._pc.setLocalDescription(answer)

            # Send answer
            await self._send_signaling("signal/answer", {"sdp": answer.sdp})

        except Exception as e:
            self._emit_error(e)

    async def _handle_signal_candidate(self, payload: dict[str, Any] | None) -> None:
        """Handle ICE candidate from server."""
        if not payload:
            return

        if not self._pc:
            # Buffer candidates until peer connection is ready
            self._pending_candidates.append(payload)
            return

        try:
            candidate = RTCIceCandidate(
                sdp=payload.get("candidate"),
                sdpMid=payload.get("sdpMid"),
                sdpMLineIndex=payload.get("sdpMLineIndex"),
            )
            await self._pc.addIceCandidate(candidate)
        except Exception as e:
            self._emit_error(e)

    async def _send_signaling(self, event: str, payload: Any) -> None:
        """Send a signaling message via WebSocket."""
        if self._websocket and not self._closed:
            try:
                await self._websocket.send(json.dumps({"event": event, "payload": payload}))
            except Exception:
                pass

    def _build_neko_msg(self, event: int, payload_size: int) -> tuple[bytes, memoryview]:
        """Build a Neko data channel message with 3-byte header (event + length)."""
        total_len = 3 + payload_size
        buf = bytearray(total_len)
        view = memoryview(buf)
        struct.pack_into("!B", buf, 0, event)
        struct.pack_into("!H", buf, 1, payload_size)
        return bytes(buf), view

    def move_mouse(self, x: int, y: int) -> None:
        """Move the mouse to the specified coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
        """
        # Move payload: X(uint16) + Y(uint16) = 4 bytes
        buf, view = self._build_neko_msg(NEKO_OP_MOVE, 4)
        struct.pack_into("!HH", buf, 3, x, y)
        self._send_data_channel(buf)

    def mouse_down(self, button: str | None = None, x: int | None = None, y: int | None = None) -> None:
        """Press a mouse button down.

        Args:
            button: Button name ("left", "middle", "right"). Defaults to "left".
            x: Optional X coordinate to move to first
            y: Optional Y coordinate to move to first
        """
        if x is not None and y is not None:
            self.move_mouse(x, y)

        # Button payload: Key(uint32) = 4 bytes
        buf, view = self._build_neko_msg(NEKO_OP_BTN_DOWN, 4)
        struct.pack_into("!I", buf, 3, _mouse_button_to_x11(button))
        self._send_data_channel(buf)

    def mouse_up(self, button: str | None = None, x: int | None = None, y: int | None = None) -> None:
        """Release a mouse button.

        Args:
            button: Button name ("left", "middle", "right"). Defaults to "left".
            x: Optional X coordinate to move to first
            y: Optional Y coordinate to move to first
        """
        if x is not None and y is not None:
            self.move_mouse(x, y)

        buf, view = self._build_neko_msg(NEKO_OP_BTN_UP, 4)
        struct.pack_into("!I", buf, 3, _mouse_button_to_x11(button))
        self._send_data_channel(buf)

    def mouse_click(self, button: str = "left", x: int | None = None, y: int | None = None) -> None:
        """Click a mouse button.

        Args:
            button: Button name ("left", "middle", "right"). Defaults to "left".
            x: Optional X coordinate to click at
            y: Optional Y coordinate to click at
        """
        self.mouse_down(button, x, y)
        self.mouse_up(button)

    def scroll(self, x: int, y: int, delta_x: int = 0, delta_y: int = 0) -> None:
        """Scroll the mouse wheel.

        Args:
            x: X coordinate
            y: Y coordinate
            delta_x: Horizontal scroll amount
            delta_y: Vertical scroll amount
        """
        self.move_mouse(x, y)

        # Scroll payload: DeltaX(int16) + DeltaY(int16) + ControlKey(uint8) = 5 bytes
        buf, view = self._build_neko_msg(NEKO_OP_SCROLL, 5)
        struct.pack_into("!hhB", buf, 3, delta_x, delta_y, 0)
        self._send_data_channel(buf)

    def key_down(self, key: str) -> None:
        """Press a key down.

        Args:
            key: Key name or character
        """
        keysym = _key_to_x11_keysym(key)
        if keysym == 0:
            return

        # Key payload: Key(uint32) = 4 bytes
        buf, view = self._build_neko_msg(NEKO_OP_KEY_DOWN, 4)
        struct.pack_into("!I", buf, 3, keysym)
        self._send_data_channel(buf)

    def key_up(self, key: str) -> None:
        """Release a key.

        Args:
            key: Key name or character
        """
        keysym = _key_to_x11_keysym(key)
        if keysym == 0:
            return

        buf, view = self._build_neko_msg(NEKO_OP_KEY_UP, 4)
        struct.pack_into("!I", buf, 3, keysym)
        self._send_data_channel(buf)

    def key_press(self, key: str) -> None:
        """Press and release a key.

        Args:
            key: Key name or character
        """
        self.key_down(key)
        self.key_up(key)

    def type_text(self, text: str) -> None:
        """Type a string of text.

        Args:
            text: Text to type
        """
        for char in text:
            self.key_press(char)

    def _send_data_channel(self, data: bytes) -> None:
        """Send data via the WebRTC data channel."""
        if self._data_channel and self._data_channel.readyState == "open":
            try:
                self._data_channel.send(data)
            except Exception:
                pass

    def _teardown_peer_connection(self) -> None:
        """Clean up the WebRTC peer connection."""
        if self._data_channel:
            try:
                self._data_channel.close()
            except Exception:
                pass
            self._data_channel = None

        if self._pc:
            try:
                asyncio.create_task(self._pc.close())
            except Exception:
                pass
            self._pc = None

        self._media_stream = None
        self._connected = False

    def _emit_error(self, error: DesktopStreamErrorStatus | Exception) -> None:
        """Emit an error to all listeners."""
        for listener in self._error_listeners:
            try:
                listener(error)
            except Exception:
                pass

    def close(self) -> None:
        """Close the desktop stream session."""
        if self._closed:
            return

        self._closed = True
        self._teardown_peer_connection()

        # Cancel message task
        if self._message_task and not self._message_task.done():
            self._message_task.cancel()

        # Close websocket
        if self._websocket:
            try:
                asyncio.create_task(self._websocket.close())
            except Exception:
                pass

        # Complete closed future if not already done
        if not self._closed_future.done():
            self._closed_future.set_result(None)
