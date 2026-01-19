FROM alpine:3.19 AS builder

RUN apk add --no-cache \
    build-base \
    git \
    openssl-dev \
    openssl-libs-static \
    linux-headers \
    perl \
    unzip \
    zlib-dev \
    zlib-static

WORKDIR /build
# Clone wrk2 (Coordinated Omission corrected version)
# Using single-threaded build for QEMU emulation compatibility
RUN git clone https://github.com/giltene/wrk2.git && \
    cd wrk2 && \
    make WITH_OPENSSL=/usr && \
    strip wrk

FROM alpine:3.19

RUN apk add --no-cache \
    openssl \
    libgcc

COPY --from=builder /build/wrk2/wrk /usr/local/bin/wrk2

ENTRYPOINT ["/usr/local/bin/wrk2"]
CMD ["--help"]
