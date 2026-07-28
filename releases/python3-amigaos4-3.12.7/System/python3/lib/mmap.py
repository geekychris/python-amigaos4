# mmap module stub for platforms without native memory mapping (e.g. AmigaOS 4)

class mmap:
    def __init__(self, *args, **kwargs):
        raise OSError("mmap is not supported on AmigaOS 4")

ACCESS_READ = 1
ACCESS_WRITE = 2
ACCESS_COPY = 3
ACCESS_DEFAULT = 4
PAGESIZE = 4096
MADV_NORMAL = 0
