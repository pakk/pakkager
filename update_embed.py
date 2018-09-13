
import os as _pakk_os
import platform as _pakk_platform
import shutil as _pakk_shutil
import subprocess as _pakk_subprocess
import sys as _pakk_sys
import urllib.request as _pakk_request
import re as _pakk_re

# CREATE_NEW_CONSOLE = 0x00000010
# pid = subprocess.Popen([sys.executable, temp_file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
def _pakk_cmp_version(left: str, right: str) -> int:
    def cmp(cmp_left, cmp_right):
        return (cmp_left > cmp_right) - (cmp_left < cmp_right)
    def normalize(norm_vec):
        return [int(x) for x in _pakk_re.sub(r'(\.0+)*$', '', norm_vec).split(".")]
    return cmp(normalize(left), normalize(right))

def _pakk_check_should_update() -> bool:
    with _pakk_request.urlopen(f"[%__pakk_server__%]product/[%__pakk_product__%]/latest/version") as response:
        # if our version is >= the latest version, then we dont need to update.
        lversion = response.read().decode("utf-8")
        return _pakk_cmp_version("[%__pakk_version__%]", lversion) < 0

def _pakk_check_update():
    current_platform = _pakk_platform.system().lower()
    if current_platform == "darwin":
        # check to see if there is a new version to download, and if there is then continue
        if not _pakk_check_should_update():
            return

        # copy embedded python runtime to temp folder
        temp_dir = _pakk_os.path.join(_pakk_os.environ["TMPDIR"], "com.pakk.pakk")
        temp_exec_dir = _pakk_os.path.join(temp_dir, "python")
        temp_exec = _pakk_os.path.join(temp_exec_dir, "python")
        _pakk_shutil.rmtree(temp_dir)
        _pakk_os.makedirs(temp_exec_dir)
        _pakk_shutil.copy2(_pakk_sys.executable, temp_exec_dir)
        _pakk_shutil.copytree("../Frameworks", _pakk_os.path.join(temp_dir, "Frameworks"))
        _pakk_shutil.copytree("./lib", _pakk_os.path.join(temp_dir, "lib"))
        _pakk_shutil.copytree("./include", _pakk_os.path.join(temp_dir, "include"))

        # download the latest updater script
        temp_updater_file = _pakk_os.path.join(temp_dir, "updater.py")
        _ = _pakk_request.urlretrieve("[%__pakk_server__%]updater", temp_updater_file)[0]

        # execute updater script - it should wait for this script to close before it tries updating the app.
        # We use '{os.getcwd()}/../../' for the directory argument because os.getcwd() will always be
        # set to `*.App/Contents/Resources` - and we want that `*.App` file/folder.
        exec_cmd = [
            temp_exec,
            temp_updater_file,
            "--server", "[%__pakk_server__%]",
            "--product", "[%__pakk_product__%]",
            "--pid", str(_pakk_os.getpid()),
            "--directory", _pakk_os.path.join(_pakk_os.getcwd(), "..", ".."),
        ]
        _pakk_subprocess.Popen(exec_cmd, cwd=temp_dir)

        # immediately close this program
        _pakk_sys.exit()

    elif current_platform == "windows":
        pass

_pakk_check_update()
