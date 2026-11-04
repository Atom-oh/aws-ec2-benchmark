# Go net/http — cross-compiled on the build host (GOARCH=$TARGETARCH), static binary on scratch.
ARG GO_VERSION=1.27.3
FROM --platform=$BUILDPLATFORM public.ecr.aws/docker/library/golang:${GO_VERSION} AS build
ARG TARGETARCH
WORKDIR /src
COPY go.mod main.go ./
RUN CGO_ENABLED=0 GOOS=linux GOARCH=$TARGETARCH go build -trimpath -ldflags="-s -w" -o /out/server .

FROM scratch
COPY --from=build /out/server /server
EXPOSE 8080
ENTRYPOINT ["/server"]
