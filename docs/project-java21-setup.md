# Project Java 21 Setup

This project is pinned to `Java 21`.

## Recommended setup

1. Install a local JDK 21.
2. Create `D:\ecommerce-after-sales-system-codex-test-ai-module-merge\.java-home.local`
3. Put the JDK root path on the first line, for example:

```text
C:\Program Files\Java\jdk-21
```

## Commands

PowerShell:

```powershell
.\mvnw.cmd -v
.\mvnw.cmd -q -DskipTests compile
.\mvnw.cmd spring-boot:run
```

If PowerShell script execution is allowed, this also works:

```powershell
powershell -ExecutionPolicy Bypass -File .\mvnw.ps1 -v
powershell -ExecutionPolicy Bypass -File .\mvnw.ps1 -q -DskipTests compile
powershell -ExecutionPolicy Bypass -File .\mvnw.ps1 spring-boot:run
```

Command Prompt:

```bat
mvnw.cmd -v
mvnw.cmd -q -DskipTests compile
mvnw.cmd spring-boot:run
```

## Optional override

Instead of `.java-home.local`, you can set a per-shell variable:

```powershell
$env:AFTERSALES_JAVA_HOME = 'C:\Program Files\Java\jdk-21'
.\mvnw.ps1 -v
```
