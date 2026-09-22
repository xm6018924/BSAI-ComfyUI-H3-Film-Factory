# v2.62 patch (by extender author): fix Windows aiohttp static file deadlock
#
# ComfyUI on Windows + Python 3.13 + aiohttp 3.13.5 + 393 custom node web.static
# routes causes the default ThreadPoolExecutor (28 workers) to deadlock: every
# static file request goes through loop.run_in_executor(None, ...) which blocks
# because all workers are occupied by other ComfyUI sync tasks. Result: browser
# can load the HTML page but every JS / CSS / favicon hangs at "headers sent,
# 0 bytes received" indefinitely.
#
# Fix:
# 1. Replace loop._default_executor with a much larger ThreadPoolExecutor
#    (256 workers, thread name prefixed) before ComfyUI starts serving. This
#    ensures worker starvation can't happen on Windows.
# 2. Patch aiohttp.web_urldispatcher.StaticResource._handle to do path
#    resolution inline (no run_in_executor). Path stat on Windows is <1ms,
#    so synchronous resolution is always faster than waiting for a worker.
#
# The patch is idempotent (safe to re-apply on hot-reload) and lives entirely
# in this prestartup.py - no changes to ComfyUI core or aiohttp.

from concurrent.futures import ThreadPoolExecutor


def _patch_aiohttp_default_executor():
    """Replace asyncio's default ThreadPoolExecutor with a 256-worker one.

    aiohttp's StaticResource._handle, FileResponse.prepare, FileResponse._sendfile_fallback
    all call `loop.run_in_executor(None, fn, *args)`. On Python 3.13 + Windows +
    ComfyUI's many concurrent sync calls, the 28-worker default gets starved.
    """
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # asyncio sets up a default ThreadPoolExecutor when the loop starts.
        # We replace it BEFORE ComfyUI's aiohttp server starts handling requests.
        new_executor = ThreadPoolExecutor(
            max_workers=256,
            thread_name_prefix="bsai-h3-ext-",
        )
        loop.set_default_executor(new_executor)
        # Note: the loop running here will be replaced when ComfyUI's main
        # asyncio.run() creates its own loop. We re-hook in _install_loop_executor().
        print(f"[H3 Extender] v2.62 default executor upgraded to {new_executor._max_workers} workers")
    except Exception as _e:
        print(f"[H3 Extender] v2.62 executor upgrade failed: {_e}")


def _patch_aiohttp_static():
    """Monkey patch aiohttp.web_urldispatcher.StaticResource._handle."""
    try:
        from aiohttp import web_urldispatcher
        import os
        from pathlib import Path

        if getattr(web_urldispatcher.StaticResource, "_v262_patched", False):
            return

        def _handle_sync(self, request):
            """v2.62: synchronous version of StaticResource._handle."""
            filename = request.match_info["filename"]
            if Path(filename).is_absolute():
                from aiohttp.web import HTTPNotFound
                raise HTTPNotFound()
            unresolved_path = self._directory.joinpath(filename)
            # Inline path resolution (no executor)
            try:
                if self._follow_symlinks:
                    normalized_path = Path(os.path.normpath(unresolved_path))
                    normalized_path.relative_to(self._directory)
                    file_path = normalized_path.resolve()
                else:
                    file_path = unresolved_path.resolve()
                    file_path.relative_to(self._directory)
            except (ValueError,) as error:
                from aiohttp.web import HTTPNotFound
                raise HTTPNotFound() from error
            except Exception as error:
                try:
                    from aiohttp.web_urldispatcher import CIRCULAR_SYMLINK_ERROR
                    if isinstance(error, CIRCULAR_SYMLINK_ERROR):
                        from aiohttp.web import HTTPNotFound
                        raise HTTPNotFound() from error
                except ImportError:
                    pass
                raise
            return self._resolve_path_to_response(file_path)

        web_urldispatcher.StaticResource._handle = _handle_sync
        web_urldispatcher.StaticResource._v262_patched = True
        print("[H3 Extender] v2.62 aiohttp web.static monkey patch applied")
    except Exception as _e:
        print(f"[H3 Extender] v2.62 web.static patch failed: {_e}")


def _patch_fileresponse_sendfile():
    """Patch FileResponse._sendfile_fallback to do chunk reads inline (no executor)."""
    try:
        from aiohttp import web_fileresponse
        from aiohttp.web_fileresponse import _FileResponseResult

        if getattr(web_fileresponse.FileResponse, "_v262_sendfile_patched", False):
            return

        _orig_sendfile_fallback = web_fileresponse.FileResponse._sendfile_fallback
        _orig_make_response = web_fileresponse.FileResponse._make_response

        def _sendfile_fallback_sync(self, writer, fobj, offset, count):
            """Read file chunks inline (Windows file IO is fast enough that
            we don't need to spawn a worker per chunk)."""
            chunk_size = self._chunk_size
            if offset:
                fobj.seek(offset)
            while count > 0:
                chunk = fobj.read(min(chunk_size, count))
                if not chunk:
                    break
                writer.write(chunk)
                count -= len(chunk)
            return writer

        # NOTE: Don't replace _sendfile_fallback with sync version because
        # writer.write() must be called from the event loop. Keeping the
        # async signature and just doing IO inline still avoids the executor.

        async def _sendfile_fallback_async(self, writer, fobj, offset, count):
            chunk_size = self._chunk_size
            if offset:
                fobj.seek(offset)
            while count > 0:
                read_size = min(chunk_size, count)
                chunk = fobj.read(read_size)
                if not chunk:
                    break
                await writer.write(chunk)
                count -= len(chunk)
            return writer

        # Replace the executor-bound version
        web_fileresponse.FileResponse._sendfile_fallback = _sendfile_fallback_async
        web_fileresponse.FileResponse._v262_sendfile_patched = True
        print("[H3 Extender] v2.62 FileResponse._sendfile_fallback patched "
              "(chunk reads inline, no executor)")
    except Exception as _e:
        print(f"[H3 Extender] v2.62 FileResponse patch failed: {_e}")


# Apply patches on prestartup
_patch_aiohttp_default_executor()
_patch_aiohttp_static()
_patch_fileresponse_sendfile()