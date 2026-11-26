# PyInstaller build of PR7-TM: pyinstaller pr7tm.spec  ->  dist/PR7-TM/PR7-TM.exe  (folder build: starts fast)
#
# Windows Defender judges unknown, unsigned programs partly by how they look: a PyInstaller program with no file
# details and the stock (shared, much-copied) starter is a common false positive. So the .exe carries proper
# version details (Properties > Details), and CI builds PyInstaller's starter from source (see build.yml).
import re

from PyInstaller.utils.hooks import collect_all, collect_submodules
import sys
from pathlib import Path


root = Path(SPECPATH)
version = re.search(r'__version__ = "(.+?)"', (root / "pr7tm" / "__init__.py").read_text()).group(1)
nums = tuple(int(x) for x in (version.split(".") + ["0", "0", "0"])[:4])
details = None
if sys.platform == "win32":  # version resources exist only in Windows programs
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    details = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Paragon"),
            StringStruct("FileDescription", "Paragon PR7-TM terminal"),
            StringStruct("FileVersion", version),
            StringStruct("InternalName", "PR7-TM"),
            StringStruct("LegalCopyright", "Paragon"),
            StringStruct("OriginalFilename", "PR7-TM.exe"),
            StringStruct("ProductName", "Paragon PR7-TM"),
            StringStruct("ProductVersion", version)])]),
              VarFileInfo([VarStruct("Translation", [1033, 1200])])])

# pywinpty (ConPTY) keeps its DLLs and helper programs beside its module: take the whole package
winpty_datas, winpty_bins, winpty_hidden = collect_all("winpty") if sys.platform == "win32" else ([], [], [])

a = Analysis(
    [str(root / "tools" / "launcher.py")],
    pathex=[str(root)],
    datas=[(str(root / "pr7tm" / "fonts"), "pr7tm/fonts"), (str(root / "pr7tm" / "icons"), "pr7tm/icons")]
          + winpty_datas,
    binaries=winpty_bins,
    # QtNetwork's local socket brings the running PR7-TM to the front when it's started again.
    hiddenimports=["PySide6.QtNetwork", "winpty", "pyte", "paramiko", "cryptography"] + collect_submodules("keyring.backends") + winpty_hidden,  # keyring finds its backends at run time
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
              "PySide6.QtPrintSupport", "PIL"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PR7-TM", console=False, upx=False,  # no UPX: packed
          icon=str(root / "pr7tm" / "icons" / "app.ico"), version=details)          # .exes look worse still
coll = COLLECT(exe, a.binaries, a.datas, name="PR7-TM", upx=False)
