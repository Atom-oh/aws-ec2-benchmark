# ASP.NET Core (Kestrel) — `dotnet publish -a <arch>` cross-targets on the build host; the final
# aspnet runtime stage only COPYs (framework-dependent, not self-contained).
FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:10.0.403 AS build
ARG TARGETARCH
WORKDIR /src
COPY Web.csproj ./
RUN case "$TARGETARCH" in amd64) A=x64 ;; arm64) A=arm64 ;; *) exit 1 ;; esac; dotnet restore -a $A
COPY Program.cs ./
RUN case "$TARGETARCH" in amd64) A=x64 ;; arm64) A=arm64 ;; *) exit 1 ;; esac; \
    dotnet publish -c Release -a $A --self-contained false --no-restore -o /out

FROM mcr.microsoft.com/dotnet/aspnet:10.0.14
WORKDIR /app
COPY --from=build /out ./
ENV DOTNET_gcServer=1
EXPOSE 8080
ENTRYPOINT ["dotnet", "Web.dll"]
