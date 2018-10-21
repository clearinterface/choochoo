
from hashlib import md5
from os import stat
from shutil import get_terminal_size

from sqlalchemy import desc

from .date import to_time
from .schedule import ZERO
from ..squeal.database import add
from ch2.squeal.tables.fit import FileScan


def terminal_width(width=None):
    return get_terminal_size()[0] if width is None else width


def tui(command):
    def wrapper(*args, **kargs):
        return command(*args, **kargs)
    wrapper.tui = True
    wrapper.__doc__ = command.__doc__
    return wrapper


# https://stackoverflow.com/a/3431838
def md5_hash(file_path):
    hash = md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash.update(chunk)
    return hash.hexdigest()


def modified_files(log, s, paths, force=False):
    for file_path in paths:
        last_modified = to_time(stat(file_path).st_mtime)
        hash = md5_hash(file_path)

        path_scan = s.query(FileScan).filter(FileScan.path == file_path).one_or_none()
        if path_scan:
            if hash != path_scan.md5_hash:
                log.warn('File at %s appears to have changed since last read on %s')
                path_scan.md5_hash = hash
                path_scan.last_scan = ZERO
        else:
            path_scan = add(s, FileScan(path=file_path, md5_hash=hash, last_scan=to_time(ZERO)))
            s.flush()

        hash_scan = s.query(FileScan).filter(FileScan.md5_hash == hash).\
            order_by(desc(FileScan.last_scan)).limit(1).one()  # must exist as path_scan is a candidate
        if hash_scan.path != path_scan.path:
            log.warn('File at %s appears to be identical to file at %s' % (file_path, hash_scan.path))

        if force or last_modified > hash_scan.last_scan:
            path_scan.last_scan = last_modified
            yield file_path
        else:
            log.debug('Skipping %s (already scanned)' % file_path)


def for_modified_files(log, session, paths, callback, force=False):
    '''
    This takes a callback because we need to know whether to mark the file as read or not
    after processing.  The callback should return True on success.

    The session is used throughout, but not passed to the callback.  The callback can
    contain the same session as internal state, or create its own.  We avoid open
    transactions across the callback.
    '''

    for file_path in paths:

        last_modified = to_time(stat(file_path).st_mtime)
        hash = md5_hash(file_path)

        path_scan = session.query(FileScan).filter(FileScan.path == file_path).one_or_none()
        if path_scan:
            if hash != path_scan.md5_hash:
                log.warn('File at %s appears to have changed since last read on %s')
                path_scan.md5_hash = hash
                path_scan.last_scan = ZERO
        else:
            path_scan = add(session, FileScan(path=file_path, md5_hash=hash, last_scan=to_time(ZERO)))
            session.flush()

        hash_scan = session.query(FileScan).filter(FileScan.md5_hash == hash).\
            order_by(desc(FileScan.last_scan)).limit(1).one()  # must exist as path_scan is a candidate
        if hash_scan.path != path_scan.path:
            log.warn('File at %s appears to be identical to file at %s' % (file_path, hash_scan.path))

        session.commit()

        if force or last_modified > hash_scan.last_scan:
            if callback(file_path):
                log.debug('Marking %s as scanned' % file_path)
                path_scan.last_scan = last_modified
                session.commit()
            else:
                log.debug('Not marking %s as scanned' % file_path)
        else:
            log.debug('Skipping %s (already scanned)' % file_path)
