@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "JAVA_HOME_CANDIDATE="

if defined AFTERSALES_JAVA_HOME set "JAVA_HOME_CANDIDATE=%AFTERSALES_JAVA_HOME%"

if not defined JAVA_HOME_CANDIDATE if exist "%PROJECT_DIR%.java-home.local" (
    set /p JAVA_HOME_CANDIDATE=<"%PROJECT_DIR%.java-home.local"
)

if not defined JAVA_HOME_CANDIDATE if defined JAVA_HOME (
    set "JAVA_HOME_CANDIDATE=%JAVA_HOME%"
)

if not defined JAVA_HOME_CANDIDATE (
    echo [ERROR] JDK 21 is not configured for this project.
    echo [ERROR] Create ".java-home.local" in the project root, for example:
    echo [ERROR]   C:\Program Files\Java\jdk-21
    echo [ERROR] You can also set AFTERSALES_JAVA_HOME before running mvnw.
    exit /b 1
)

set "JAVA_HOME_CANDIDATE=%JAVA_HOME_CANDIDATE:"=%"

if not exist "%JAVA_HOME_CANDIDATE%\bin\java.exe" (
    echo [ERROR] java.exe not found under "%JAVA_HOME_CANDIDATE%".
    exit /b 1
)

set "JAVA_VERSION="
if exist "%JAVA_HOME_CANDIDATE%\release" (
    for /f "tokens=2 delims==" %%i in ('findstr /b /c:"JAVA_VERSION=" "%JAVA_HOME_CANDIDATE%\release"') do (
        set "JAVA_VERSION=%%~i"
    )
)
set "JAVA_VERSION=%JAVA_VERSION:"=%"

if not defined JAVA_VERSION (
    echo [ERROR] Cannot detect JAVA_VERSION from "%JAVA_HOME_CANDIDATE%\release".
    exit /b 1
)

echo %JAVA_VERSION% | findstr /b /c:"21" >nul
if errorlevel 1 (
    echo [ERROR] This project requires JDK 21, but found "%JAVA_VERSION%".
    exit /b 1
)

set "JAVA_HOME=%JAVA_HOME_CANDIDATE%"
set "PATH=%JAVA_HOME%\bin;%PATH%"

where mvn.cmd >nul 2>nul
if errorlevel 1 (
    call mvn %*
) else (
    call mvn.cmd %*
)

exit /b %ERRORLEVEL%
