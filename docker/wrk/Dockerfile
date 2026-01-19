FROM alpine:3.19 AS builder

RUN apk add --no-cache \
    build-base \
    git \
    openssl-dev \
    openssl-libs-static \
    linux-headers \
    perl \
    unzip

WORKDIR /build
# Clone wrk and build with bundled LuaJIT
# Using single-threaded build for QEMU emulation compatibility
RUN git clone https://github.com/wg/wrk.git && \
    cd wrk && \
    make WITH_OPENSSL=/usr && \
    strip wrk

FROM alpine:3.19

RUN apk add --no-cache \
    openssl \
    libgcc

COPY --from=builder /build/wrk/wrk /usr/local/bin/wrk

ENTRYPOINT ["/usr/local/bin/wrk"]
CMD ["--help"]
