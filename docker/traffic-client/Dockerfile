# Supply the existing digest-pinned benchmark/wrk runtime image.
# Build traffic-client on the host with CGO_ENABLED=0 GOOS=linux GOARCH=amd64.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY traffic-client /usr/local/bin/traffic-client
ENTRYPOINT ["/usr/local/bin/traffic-client"]
