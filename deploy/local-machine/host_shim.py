"""Host-rewriting TCP relay for the Hermes dashboard tunnel.

Listens on 127.0.0.2:9119 (hermes.local), rewrites the Host header of each
HTTP request head to the loopback value the dashboard accepts, and forwards
to the SSH tunnel on 127.0.0.1:19119. After a WebSocket 101 upgrade the
connection becomes a transparent byte splice, so live dashboard sessions work.
"""
import asyncio

LISTEN = ("127.0.0.2", 9119)
UPSTREAM = ("127.0.0.1", 19119)
TARGET_HOST = b"127.0.0.1:9119"


async def rewrite_head(reader):
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = await reader.read(4096)
        if not chunk:
            return None
        head += chunk
        if len(head) > 65536:
            return None
    head_part, rest = head.split(b"\r\n\r\n", 1)
    lines = head_part.split(b"\r\n")
    is_upgrade = any(line.lower().startswith(b"upgrade:") for line in lines)
    out = []
    for line in lines:
        lowered = line.lower()
        if lowered.startswith(b"host:"):
            out.append(b"Host: " + TARGET_HOST)
        elif lowered.startswith(b"origin:"):
            out.append(b"Origin: http://" + TARGET_HOST)
        elif lowered.startswith(b"connection:") and not is_upgrade:
            # Force one request per connection: only the first request head is
            # rewritten, so keep-alive would leak unrewritten Host headers.
            out.append(b"Connection: close")
        else:
            out.append(line)
    if not is_upgrade and not any(l.lower().startswith(b"connection:") for l in out):
        out.append(b"Connection: close")
    return b"\r\n".join(out) + b"\r\n\r\n" + rest


async def splice(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(client_reader, client_writer):
    try:
        first = await rewrite_head(client_reader)
        if first is None:
            client_writer.close()
            return
        up_reader, up_writer = await asyncio.open_connection(*UPSTREAM)
        up_writer.write(first)
        await up_writer.drain()
        await asyncio.gather(
            splice(client_reader, up_writer),
            splice(up_reader, client_writer),
        )
    except Exception:
        try:
            client_writer.close()
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(handle, *LISTEN)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
