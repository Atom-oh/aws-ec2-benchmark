# Spring Boot PetClinic - Full featured app for benchmarking (multi-arch)
FROM public.ecr.aws/amazoncorretto/amazoncorretto:21-al2023-headless AS builder

WORKDIR /build

# Install required tools
RUN yum install -y git maven tar gzip && yum clean all

# Clone and build PetClinic
RUN git clone https://github.com/spring-projects/spring-petclinic.git && \
    cd spring-petclinic && \
    ./mvnw package -DskipTests -q

# Runtime stage
FROM public.ecr.aws/amazoncorretto/amazoncorretto:21-al2023-headless

WORKDIR /app
COPY --from=builder /build/spring-petclinic/target/*.jar app.jar

EXPOSE 8080

ENV JAVA_OPTS="-XX:+UseG1GC -XX:MaxGCPauseMillis=100"

ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar /app/app.jar"]
