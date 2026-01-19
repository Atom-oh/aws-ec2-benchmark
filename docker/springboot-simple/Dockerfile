# Simple Spring Boot app for benchmarking (multi-arch)
FROM public.ecr.aws/amazoncorretto/amazoncorretto:21-al2023-headless AS builder

WORKDIR /build

# Install required tools
RUN yum install -y maven && yum clean all

# Create minimal Spring Boot application inline
RUN mkdir -p src/main/java/com/benchmark/demo

# Create pom.xml
RUN cat > pom.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.2.0</version>
        <relativePath/>
    </parent>
    <groupId>com.benchmark</groupId>
    <artifactId>demo</artifactId>
    <version>0.0.1-SNAPSHOT</version>
    <name>demo</name>
    <properties>
        <java.version>21</java.version>
    </properties>
    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-actuator</artifactId>
        </dependency>
    </dependencies>
    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
            </plugin>
        </plugins>
    </build>
</project>
EOF

# Create main application
RUN cat > src/main/java/com/benchmark/demo/DemoApplication.java << 'EOF'
package com.benchmark.demo;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@SpringBootApplication
@RestController
public class DemoApplication {
    public static void main(String[] args) {
        SpringApplication.run(DemoApplication.class, args);
    }

    @GetMapping("/")
    public String home() {
        return "Spring Boot Benchmark Demo";
    }

    @GetMapping("/health")
    public String health() {
        return "healthy";
    }
}
EOF

# Build the application
RUN mvn package -DskipTests -q

# Runtime stage
FROM public.ecr.aws/amazoncorretto/amazoncorretto:21-al2023-headless

WORKDIR /app
COPY --from=builder /build/target/*.jar app.jar

EXPOSE 8080

ENV JAVA_OPTS="-XX:+UseG1GC -XX:MaxGCPauseMillis=100"

ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar /app/app.jar"]
