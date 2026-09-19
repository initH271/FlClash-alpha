FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git git-lfs unzip xz-utils zip python3 build-essential \
    clang cmake ninja-build pkg-config libgtk-3-dev libglu1-mesa \
    openjdk-17-jdk-headless openssh-server sudo && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    ANDROID_HOME=/opt/android-sdk ANDROID_SDK_ROOT=/opt/android-sdk \
    RUSTUP_HOME=/opt/rustup CARGO_HOME=/opt/cargo \
    PUB_CACHE=/root/.pub-cache RUSTUP_TOOLCHAIN=1.95.0
ENV PATH=/opt/flutter/bin:/usr/local/go/bin:/opt/cargo/bin:/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:$PATH
RUN curl -fsSL --retry 3 https://go.dev/dl/go1.26.4.linux-amd64.tar.gz | tar -xz -C /usr/local
RUN curl -fsSL --retry 3 https://sh.rustup.rs -o /tmp/rustup.sh && \
    sh /tmp/rustup.sh -y --profile minimal --default-toolchain 1.95.0 --target aarch64-linux-android && rm /tmp/rustup.sh
ENV TAR_OPTIONS=--no-same-owner
RUN git clone --depth 1 --branch 3.47.1 https://github.com/flutter/flutter.git /opt/flutter && \
    git config --global --add safe.directory /opt/flutter && \
    flutter config --no-analytics && flutter precache --android
RUN curl -fsSL --retry 3 https://dl.google.com/android/repository/commandlinetools-linux-15859902_latest.zip -o /tmp/android.zip && \
    echo '4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583  /tmp/android.zip' | sha256sum -c - && \
    mkdir -p /opt/android-sdk/cmdline-tools && unzip -q /tmp/android.zip -d /opt/android-sdk/cmdline-tools && \
    mv /opt/android-sdk/cmdline-tools/cmdline-tools /opt/android-sdk/cmdline-tools/latest && rm /tmp/android.zip && \
    yes | sdkmanager --licenses >/dev/null && \
    sdkmanager 'platform-tools' 'platforms;android-36' 'build-tools;36.0.0' 'ndk;28.2.13676358'
ENV ANDROID_NDK_HOME=/opt/android-sdk/ndk/28.2.13676358
RUN flutter config --android-sdk /opt/android-sdk && mkdir -p /run/sshd && ssh-keygen -A
