"""Zajętość dysków — poziome paski used/free per zamontowany system plików.
Towarzysz wykresu DISK r (ten pokazuje I/O, ten pokazuje pojemność). Dane: psutil."""
import psutil
from PySide6 import QtCore, QtGui, QtWidgets

from kokpit.ui.theme.palette import DIM_FG, alert_color

_REAL_FS = {"ext4", "ext3", "ext2", "xfs", "btrfs", "vfat", "ntfs", "exfat", "f2fs", "zfs"}
_GiB = 1024 ** 3


def format_gib(b: float) -> str:
    return f"{b / _GiB:.1f}"


def disk_usages() -> list[tuple[str, int, int]]:
    """(mountpoint, used, total) dla realnych systemów plików, posortowane po pojemności.
    Pomija pseudo-fs (tmpfs/overlay/loop) i duplikaty urządzeń (bind mounts)."""
    out: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    try:
        parts = psutil.disk_partitions(all=False)
    except Exception:
        return out
    for part in parts:
        if part.fstype.lower() not in _REAL_FS or part.device in seen:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        seen.add(part.device)
        out.append((part.mountpoint, u.used, u.total))
    out.sort(key=lambda r: r[2], reverse=True)
    return out


class DiskUsage(QtWidgets.QWidget):
    _BAR_H = 16
    _ROW_GAP = 32
    _TOP = 22

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[tuple[str, int, int]] = disk_usages()
        self.setMinimumWidth(180)
        self.setMinimumHeight(self._TOP + max(1, len(self._rows)) * self._ROW_GAP + 6)

    def refresh(self) -> None:
        self._rows = disk_usages()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        f = p.font()
        f.setBold(True)
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(QtGui.QColor("#5fb8d6"))
        p.drawText(2, 12, "DISK USAGE")
        w = self.width() - 4
        small = p.font()
        small.setBold(False)
        small.setPointSize(8)
        for i, (mount, used, total) in enumerate(self._rows):
            frac = (used / total) if total else 0.0
            y = self._TOP + i * self._ROW_GAP
            track = QtCore.QRectF(2, y, w, self._BAR_H)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor("#16263a"))            # tor
            p.drawRoundedRect(track, 3, 3)
            col = QtGui.QColor(alert_color(frac * 100, high=80, crit=92))
            fill = QtCore.QRectF(2, y, max(2.0, w * frac), self._BAR_H)
            p.setBrush(col)
            p.drawRoundedRect(fill, 3, 3)
            # tekst na pasku: mount + % | wolne GiB / total
            p.setFont(small)
            p.setPen(QtGui.QColor("#0a0f1c"))
            p.drawText(QtCore.QRectF(6, y, w - 8, self._BAR_H),
                       QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                       f"{mount}  {frac * 100:.0f}%")
            p.setPen(QtGui.QColor(DIM_FG))
            p.drawText(QtCore.QRectF(2, y + self._BAR_H, w, 12),
                       QtCore.Qt.AlignRight,
                       f"{format_gib(total - used)} GiB free / {format_gib(total)}")
            p.setFont(f)
        p.end()
