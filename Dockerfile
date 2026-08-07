# Layered build image: walkero OS4 PPC toolchain + Python 3.12 (as the
# CPython build-python) + clib4 v2.3 SDK (walkero ships v2.1).
#
# CPython's configure requires PYTHON_FOR_BUILD to match the target
# major.minor for freezing modules.
FROM walkero/amigagccondocker:os4-gcc11

# Install Python 3.12 via deadsnakes so we get a proper venv-capable
# interpreter separate from the system 3.14.
RUN apt-get update && \
    apt-get install -y --no-install-recommends software-properties-common && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev \
        pkg-config make \
        curl ca-certificates binutils zstd && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Upgrade clib4 SDK from v2.1 (bundled with walkero image) to v2.3.
# Pulls the pre-built .deb from Andrea Palmatè's github release, unpacks
# it, and copies the SDK include/lib bits into the walkero SDK tree.
# Preserves the existing clib4.library runtime files at the SDK root
# (host-side cross-compile only cares about include/lib; the .library
# file lives guest-side and is only relevant at runtime).
RUN cd /tmp && \
    curl -fsSL -o clib4.deb \
      https://github.com/AmigaLabs/clib4/releases/download/v2.3/clib4-v2.3_amd64.deb && \
    mkdir clib4-pkg && cd clib4-pkg && \
    ar x /tmp/clib4.deb && \
    zstd -d data.tar.zst -o data.tar && \
    tar -xf data.tar && \
    rm -rf /opt/ppc-amigaos/ppc-amigaos/SDK/clib4/include \
           /opt/ppc-amigaos/ppc-amigaos/SDK/clib4/lib && \
    cp -a usr/ppc-amigaos/SDK/clib4/include /opt/ppc-amigaos/ppc-amigaos/SDK/clib4/ && \
    cp -a usr/ppc-amigaos/SDK/clib4/lib     /opt/ppc-amigaos/ppc-amigaos/SDK/clib4/ && \
    cd / && rm -rf /tmp/clib4.deb /tmp/clib4-pkg

# Verify.
RUN python3.12 --version && \
    ls -la /opt/ppc-amigaos/ppc-amigaos/SDK/clib4/lib/libc.a | head -1
