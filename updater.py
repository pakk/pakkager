"""
Compares the current version of an embedded pakkager package with the parent product on a pakkager server.

If the server's version is newer, then download the newest version and replace the current working version.
"""
import errno
import os
import zipfile
import logging
from subprocess import call
from platform import system
from argparse import ArgumentParser, Namespace
from urllib.request import urlretrieve

logger = logging.getLogger(__name__)
handler = logging.FileHandler(os.path.join(os.path.dirname(os.path.realpath(__file__)), "log.txt"))
formatter = logging.Formatter("%(asctime)s %(name)-12s %(levelname)-8s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

def unix_pid_exists(pid):
    """Check whether pid exists in the current process table.
    UNIX only.
    """
    if pid < 0:
        return False
    if pid == 0:
        # According to "man 2 kill" PID 0 refers to every process
        # in the process group of the calling process.
        # On certain systems 0 is a valid PID but we have no way
        # to know that in a portable fashion.
        raise ValueError('invalid PID 0')
    try:
        os.kill(pid, 0)
    except OSError as err:
        if err.errno == errno.ESRCH:
            # ESRCH == No such process
            return False
        elif err.errno == errno.EPERM:
            # EPERM clearly means there's a process to deny access to
            return True
        else:
            # According to "man 2 kill" possible error values are
            # (EINVAL, EPERM, ESRCH)
            raise
    else:
        return True

def update_windows(parser: Namespace):
    pass

def update_darwin(parser: Namespace):
    endpoint = f"{parser.server}product/{parser.product}/latest/darwin"
    logger.debug(f"getting file from {endpoint}")
    local_filename = urlretrieve(endpoint)[0]
    
    logger.debug(f"downloaded file from endpoint to {local_filename}, extracting to {parser.directory}")
    with zipfile.ZipFile(local_filename, 'r') as in_zip:
            in_zip.extractall(parser.directory)

    logger.debug("re-executing updated app")
    call(["open", "-a", parser.directory])

def update_linux(parser: Namespace):
    pass

def main():
    parser = ArgumentParser()
    parser.add_argument("-s", "--server", dest="server", help="The url of the pakkager server to resolve and query against.")
    parser.add_argument("-p", "--product", dest="product", help="The product identifier to be compared against the server.")
    parser.add_argument("-P", "--pid", dest="pid", help="The pid of the process that should be closed before updating.", type=int)
    parser.add_argument("-d", "--directory", dest="directory", help="The path to the application.")
    args = parser.parse_args()

    current_platform = system()
    logger.debug(f"CURRENT_PLATFORM = {current_platform}")
    if current_platform == "Windows":
        update_windows(args)
    elif current_platform == "Darwin":
        logger.debug(f"waiting for pid {args.pid} to exit")
        while True:
            if not unix_pid_exists(args.pid):
                break

        logger.debug("pid closed")
        logger.debug("updating for darwin")
        update_darwin(args)


if __name__ == "__main__":
    main()
