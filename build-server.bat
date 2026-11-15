@echo off
setlocal

rem Build and push the polyvox server image for the supplied version and latest.
rem Usage: build-server.bat ^<tag^> (initial release: v1.0.0)
if "%~1"=="" goto :usage
if not "%~2"=="" goto :usage

set "POLYVOX_TAG=%~1"
set "IMAGE=jchristn77/polyvox-server"
set "BUILDER=cloud-jchristn77-jchristn77"
set "ROOT_DIR=%~dp0"

powershell -NoProfile -NonInteractive -Command "if ($env:POLYVOX_TAG -cnotmatch '^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$') { exit 1 }"
if errorlevel 1 (
    echo Error: supply a valid Docker image tag.
    exit /b 1
)

rem Use Armada's preconfigured Docker Build Cloud builder. Run docker login first.
docker buildx inspect "%BUILDER%" >nul
if errorlevel 1 exit /b %errorlevel%

pushd "%ROOT_DIR%" || exit /b 1
echo Building and pushing %IMAGE%:%POLYVOX_TAG% and %IMAGE%:latest...
docker buildx build ^
    --builder "%BUILDER%" ^
    --platform linux/amd64,linux/arm64/v8 ^
    --provenance=false --sbom=false ^
    --build-arg API_MODE=true ^
    -f dockerfile-cpu ^
    -t "%IMAGE%:%POLYVOX_TAG%" ^
    -t "%IMAGE%:latest" ^
    --push .
set "EXITCODE=%errorlevel%"
popd
exit /b %EXITCODE%

:usage
echo Usage: %~nx0 ^<tag^>
echo Example: %~nx0 v1.0.0
exit /b 1
