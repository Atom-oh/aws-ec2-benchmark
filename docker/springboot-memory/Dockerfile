# 메모리 부하 Spring Boot 앱 — Java 바이트코드는 아키텍처 무관이라 빌드는 빌드 호스트에서 1회(QEMU 불필요),
# 런타임 단계만 대상 아키텍처의 Corretto 이미지(패치 버전 고정)를 쓴다.
FROM --platform=$BUILDPLATFORM public.ecr.aws/docker/library/maven:3.9.9-amazoncorretto-21 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -q -B dependency:go-offline
COPY src ./src
RUN mvn -q -B package -DskipTests

FROM public.ecr.aws/amazoncorretto/amazoncorretto:21.0.13-al2023-headless
WORKDIR /app
COPY --from=build /src/target/app.jar /app/app.jar
EXPOSE 8080
# JVM 옵션(힙 크기·G1)은 서버 템플릿의 JAVA_OPTS로 지정
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/app.jar"]
