# default-npc carries the cnb CLI, skills and commit signing the NPC agent relies on.
# versionBy only hashes this file, so the base is pinned; bump the digest to pick up a newer default-npc.
FROM cnbcool/default-npc:latest@sha256:e1fcb0839c32b5ed738976674575b696be34b339b8fdfd2bfe607062e25e20c6
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    xz-utils unzip zip build-essential clang cmake ninja-build pkg-config libgtk-3-dev libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*
ENV RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo RUSTUP_TOOLCHAIN=1.95.0 \
    PUB_CACHE=/root/.pub-cache
ENV PATH=/opt/flutter/bin:/usr/local/go/bin:/opt/cargo/bin:$PATH
RUN curl -fsSL --retry 3 https://go.dev/dl/go1.26.8.linux-amd64.tar.gz -o /tmp/go.tar.gz && \
    echo 'd0f743b33e8d8945e6b1f432edd15785c70507121d6e2a723b21285eddf8b57b  /tmp/go.tar.gz' | sha256sum -c - && \
    tar -xzf /tmp/go.tar.gz -C /usr/local && rm /tmp/go.tar.gz
RUN curl -fsSL --retry 3 https://sh.rustup.rs -o /tmp/rustup.sh && \
    sh /tmp/rustup.sh -y --profile minimal --default-toolchain 1.95.0 && rm /tmp/rustup.sh
ENV TAR_OPTIONS=--no-same-owner
RUN git clone --depth 1 --branch 3.47.1 https://github.com/flutter/flutter.git /opt/flutter && \
    git config --global --add safe.directory /opt/flutter && \
    flutter config --no-analytics --no-cli-animations && \
    flutter create --platforms=linux /tmp/warm && cd /tmp/warm && flutter test && rm -rf /tmp/warm
