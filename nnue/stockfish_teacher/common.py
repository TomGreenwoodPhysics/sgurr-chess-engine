"""I/O confined to the external-data line; no self-play process management."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CACHE = ROOT / "data/stockfish_teacher/cache"
CLANG = Path("C:/msys64/clang64/bin/clang++.exe")
MAX_DOWNLOAD = 20 * 1024**3


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while b := f.read(4 << 20):
            h.update(b)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@contextlib.contextmanager
def lock(path):
    """OS lock releases on process death, so stale PID files never block resume."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        f.seek(0, 2)
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f"Another process owns {path}") from exc
        try:
            yield
        finally:
            f.seek(0)
            if os.name == "nt":
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def space_check(path, required):
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    free = shutil.disk_usage(path).free
    print(f"Disk {path}: free={free:,} bytes; required={required:,}", flush=True)
    if free < required:
        raise RuntimeError("Insufficient free space")


def verified(path, spec):
    path = Path(path)
    if not path.is_file() or path.stat().st_size != spec["bytes"]:
        raise RuntimeError(f"Missing or incorrect file size: {path}")
    actual = sha256(path)
    if actual != spec["sha256"].lower():
        raise RuntimeError(f"SHA-256 mismatch: {path}: {actual}")
    return actual


def download(spec, directory=CACHE, opener=urllib.request.urlopen):
    """Pinned HTTP object, append only after validating 206 and Content-Range.

    A completed file is rehashed on every invocation. No replacement on mismatch.
    Partial bytes survive interruption. A changed spec or ignored Range fails.
    Final checksum is authoritative even if the server has no ETag.
    """
    size = spec["bytes"]
    if not isinstance(size, int) or not 0 < size < MAX_DOWNLOAD:
        raise ValueError("Each download must be positive and below 20 GiB")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", spec["sha256"]):
        raise ValueError("A pinned SHA-256 is required")
    name = spec["file"]
    if Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("Download file must be a basename")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / name
    partial = dest.with_name(name + ".partial")
    meta_path = dest.with_name(name + ".download.json")
    identity = {k: spec[k] for k in ("url", "file", "bytes", "sha256")}
    print(f"Download: {identity['url']}\nDestination: {dest}\nExpected: {size:,} bytes ({size/1024**3:.3f} GiB)", flush=True)
    with lock(dest.with_name(name + ".lock")):
        if dest.exists():
            verified(dest, spec)
            atomic_json(meta_path, {"identity": identity, "verified_sha256": spec["sha256"], "complete": True})
            print("Existing artifact verified; no download needed", flush=True)
            return dest
        meta = read_json(meta_path) if meta_path.exists() else {"identity": identity}
        if meta.get("identity") != identity:
            raise RuntimeError("Resume metadata differs from requested artifact")
        if partial.exists() and not meta_path.exists():
            raise RuntimeError("Unidentified partial file; preserve it and choose a fresh cache directory")
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > size:
            raise RuntimeError("Partial file is larger than expected; leaving it untouched")
        space_check(directory, size - offset + (256 << 20))
        atomic_json(meta_path, meta)
        if offset < size:
            headers = {"Accept-Encoding": "identity", "User-Agent": "Sgurr-StockfishTeacher/1"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
                if (meta.get("etag") or "").startswith('"'):
                    headers["If-Range"] = meta["etag"]
            req = urllib.request.Request(spec["url"], headers=headers)
            with opener(req, timeout=60) as response:
                status = response.status
                length = response.headers.get("Content-Length")
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    raise RuntimeError("Unexpected HTTP content encoding")
                if offset or status == 206:
                    expected = f"bytes {offset}-{size-1}/{size}"
                    if status != 206 or response.headers.get("Content-Range") != expected:
                        raise RuntimeError("Server ignored/misreported Range; partial file preserved")
                elif status != 200:
                    raise RuntimeError(f"Unexpected HTTP status {status}")
                if length is not None and int(length) != size - offset:
                    raise RuntimeError("HTTP Content-Length differs from pinned size")
                etag = response.headers.get("ETag")
                if offset and meta.get("etag") and etag != meta["etag"]:
                    raise RuntimeError("ETag changed during resume")
                meta["etag"] = etag
                atomic_json(meta_path, meta)
                last = time.monotonic()
                with partial.open("ab" if partial.exists() else "xb") as out:
                    while offset < size:
                        data = response.read(min(4 << 20, size - offset))
                        if not data:
                            raise RuntimeError(f"Interrupted download at {offset:,}/{size:,}; rerun to resume")
                        out.write(data)
                        offset += len(data)
                        if time.monotonic() - last >= 5:
                            out.flush()
                            print(f"Downloaded {offset:,}/{size:,} ({100*offset/size:.1f}%)", flush=True)
                            last = time.monotonic()
                    if response.read(1):
                        raise RuntimeError("Server sent more than the pinned size")
                    out.flush()
                    os.fsync(out.fileno())
        actual = verified(partial, spec)
        if dest.exists():
            raise RuntimeError("Destination appeared during download; refusing overwrite")
        partial.rename(dest)
        atomic_json(meta_path, {**meta, "verified_sha256": actual, "complete": True})
        print(f"Verified SHA-256 {actual}", flush=True)
        return dest


def run(cmd, log, *, cwd=ROOT, env=None, input_text=None, timeout=None):
    cmd = list(map(str, cmd))
    actual_env = os.environ.copy()
    actual_env.pop("SGR_EVALFILE", None)
    actual_env.update({"PYTHONUNBUFFERED": "1", **(env or {})})
    print(f"cwd={Path(cwd).resolve()}\ncommand={subprocess.list2cmdline(cmd)}", flush=True)
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    # File output remains visible and durable even if the parent is interrupted.
    with log.open("a", encoding="utf-8") as f:
        f.write(f"\ncommand={json.dumps(cmd)} cwd={str(cwd)}\n")
        f.flush()
        p = subprocess.Popen(cmd, cwd=cwd, env=actual_env, stdin=subprocess.PIPE,
                             stdout=f, stderr=subprocess.STDOUT, text=True)
        try:
            p.communicate(input_text, timeout=timeout)
        except BaseException:
            terminate_owned(p)
            raise
        if p.returncode:
            raise RuntimeError(f"Command exited {p.returncode}; see {log}")


def terminate_owned(process):
    """Terminate only this live child and its descendants, never by image name."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        process.kill()
    process.wait(timeout=30)


def busy_processes():
    if os.name != "nt":
        return []
    # Get-Process works under the repository sandbox; tasklist can fail there.
    output = subprocess.check_output(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                                      "Get-Process | Select-Object -ExpandProperty ProcessName"], text=True, timeout=20)
    names = [line.strip().lower() for line in output.splitlines()]
    return [name + ".exe" for name in names if name in ("trackmania", "fastchess") or name.startswith("datagen")]


def require_idle():
    busy = busy_processes()
    if busy:
        raise RuntimeError(f"Training/timed games deferred while these are running: {busy}. No process was stopped.")


def idle_load_sample():
    """Observe whole-machine load before a timed match; never stop other work."""
    result = {"cpu_percent": None, "gpu_percent": None}
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        def sample():
            values = [wintypes.FILETIME() for _ in range(3)]
            if not ctypes.windll.kernel32.GetSystemTimes(*(ctypes.byref(v) for v in values)):
                raise RuntimeError("Cannot inspect CPU idle time")
            return [v.dwLowDateTime + (v.dwHighDateTime << 32) for v in values]
        before = sample()
        time.sleep(1)
        after = sample()
        idle, kernel, user = [b - a for a, b in zip(before, after)]
        result["cpu_percent"] = 100 * (1 - idle / max(1, kernel + user))
    smi = shutil.which("nvidia-smi")
    if smi:
        output = subprocess.check_output([smi, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], text=True, timeout=15)
        result["gpu_percent"] = max(int(x.strip()) for x in output.splitlines())
    if any(v is not None and v > 15 for v in result.values()):
        raise RuntimeError(f"Machine is busy: {result}; match deferred")
    return result
