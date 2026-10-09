import os
import pathlib
import signal
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUN = ROOT / "run"


def resume_process(pid: int):
    if sys.platform == "win32":
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1F0FFF, False, pid)
            if handle:
                ctypes.windll.ntdll.NtResumeProcess(handle)
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass
    else:
        try:
            os.kill(pid, signal.SIGCONT)
        except Exception:
            pass


def kill_process(pid: int):
    resume_process(pid)
    try:
        if sys.platform == "win32":
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def main():
    if not RUN.exists():
        print("all stopped")
        return
    for pid_file in RUN.glob("*.pid"):
        try:
            txt = pid_file.read_text().strip()
            if txt:
                pid = int(txt)
                kill_process(pid)
        except Exception:
            pass
        try:
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass
    print("all stopped")


if __name__ == "__main__":
    main()
