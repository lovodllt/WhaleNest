"""Locks and process ownership shared by the host launchers."""
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import psutil

WINDOWS = os.name == 'nt'


def ensure_utf8():
    if WINDOWS and not sys.flags.utf8_mode:
        os.execv(sys.executable,[sys.executable,'-X','utf8',*sys.argv])


def node_entry(command, entry):
    path=Path(shutil.which(command) or command)
    if path.suffix.lower() in ('.cmd','.bat'):
        path=path.parent/entry
        if not path.is_file():
            raise FileNotFoundError('没有找到命令对应的 Node 入口：'+str(path))
    return str(path.resolve()) if path.is_file() else command


def acquire_lock(handle, blocking=True):
    if not WINDOWS:
        import fcntl
        fcntl.flock(handle,fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return
    import msvcrt
    # Every process locks byte zero, including a newly created empty file.
    while True:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            return
        except OSError as error:
            if error.errno not in (errno.EACCES,errno.EAGAIN,errno.EDEADLK):
                raise
            if not blocking:
                raise BlockingIOError(error.errno,'Another instance holds this lock') from error
            time.sleep(.05)


def release_lock(handle):
    if WINDOWS:
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
    else:
        import fcntl
        fcntl.flock(handle,fcntl.LOCK_UN)


@contextmanager
def file_lock(path, blocking=True):
    with Path(path).open('a+b') as handle:
        acquire_lock(handle,blocking)
        try:
            yield handle
        finally:
            release_lock(handle)


def lock_held(path):
    try:
        with file_lock(path,False):
            return False
    except BlockingIOError:
        return True


def process_record(pid, script):
    process=psutil.Process(pid)
    return {'pid':pid,'created':process.create_time(),'executable':process.exe(),
            'script':str(Path(script).resolve())}


def owned_process(record):
    if not isinstance(record,dict):
        return None
    try:
        process=psutil.Process(record['pid'])
        if (not process.is_running() or process.status()==psutil.STATUS_ZOMBIE or
                process.create_time()!=record['created'] or
                os.path.normcase(process.exe())!=os.path.normcase(record['executable'])):
            return None
        directory=Path(process.cwd())
        expected=Path(record['script'])
        if any((directory/arg).resolve()==expected for arg in process.cmdline()[1:]):
            return process
    except (KeyError,ValueError,OSError,psutil.Error):
        pass
    return None


def detached_options():
    return ({'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
            if WINDOWS else {'start_new_session':True})


def terminate_tree(process):
    try:
        processes=list(reversed(process.children(recursive=True)))+[process]
    except psutil.NoSuchProcess:
        return
    for child in processes:
        try:child.terminate()
        except psutil.NoSuchProcess:pass
    _,alive=psutil.wait_procs(processes,timeout=2)
    for child in alive:
        try:child.kill()
        except psutil.NoSuchProcess:pass
    psutil.wait_procs(alive,timeout=2)


def watch_stop(path, callback):
    def watch():
        while not Path(path).exists():
            time.sleep(.25)
        callback()
    threading.Thread(target=watch,daemon=True).start()
