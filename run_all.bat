@echo off
rem Run the VentTRACE pipeline, in order, logging each step.
rem
rem   run_all.bat            - 01 through 07
rem   run_all.bat 02 03      - only those steps

setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0"
if errorlevel 1 (
    echo unable to enter repository directory: %~dp0 1>&2
    exit /b 1
)
setlocal EnableDelayedExpansion

if not exist "config\config.json" (
    echo config\config.json missing - copy config\config_template.json config\config.json 1>&2
    popd
    exit /b 1
)

set "ALL_STEPS=01_cohort 02_index_paralytic 03_context 04_covariates 05_table_one 06_reference_cpt 07_artifact_manifest"
set "STEPS="
set /a STEP_COUNT=0

if "%~1"=="" (
    set "STEPS=%ALL_STEPS%"
    set /a STEP_COUNT=7
) else (
    call :select_steps %*
    if errorlevel 1 (
        popd
        exit /b 1
    )
)

for /f "usebackq delims=" %%T in (`powershell.exe -NoProfile -Command "[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')"`) do set "RUN_TIMESTAMP=%%T"
if not defined RUN_TIMESTAMP (
    echo unable to create UTC run timestamp 1>&2
    popd
    exit /b 1
)

set "LOG_DIR=output\final_no_phi\logs\run_!RUN_TIMESTAMP!"
if not exist "!LOG_DIR!" mkdir "!LOG_DIR!"
if errorlevel 1 (
    echo unable to create log directory: !LOG_DIR! 1>&2
    popd
    exit /b 1
)

uv sync --quiet
if errorlevel 1 (
    echo uv sync failed 1>&2
    popd
    exit /b 1
)

echo logs: !LOG_DIR!

for %%S in (!STEPS!) do (
    echo.
    echo === %%S ===
    uv run python "code\%%S.py" > "!LOG_DIR!\%%S.log" 2>&1
    set "STEP_STATUS=!ERRORLEVEL!"
    type "!LOG_DIR!\%%S.log"
    if not "!STEP_STATUS!"=="0" (
        echo FAILED at %%S - see !LOG_DIR!\%%S.log 1>&2
        popd
        exit /b !STEP_STATUS!
    )
    echo --- %%S ok
)

set "FILE_COUNT="
for /f "usebackq delims=" %%C in (`uv run python -c "from pathlib import Path; print(sum(p.is_file() for p in Path('output/final_no_phi').rglob('*')))"`) do set "FILE_COUNT=%%C"
if not defined FILE_COUNT (
    echo unable to count files in output\final_no_phi 1>&2
    popd
    exit /b 1
)

echo.
echo done: !STEP_COUNT! steps, !FILE_COUNT! files in output\final_no_phi
popd
exit /b 0

:select_steps
if "%~1"=="" exit /b 0
set "WANT=%~1"
call :string_length "!WANT!" WANT_LENGTH
set "MATCHED="

for %%S in (%ALL_STEPS%) do (
    set "CANDIDATE=%%S"
    call set "PREFIX=%%CANDIDATE:~0,!WANT_LENGTH!%%"
    if /i "!PREFIX!"=="!WANT!" (
        if defined STEPS (
            set "STEPS=!STEPS! %%S"
        ) else (
            set "STEPS=%%S"
        )
        set /a STEP_COUNT+=1
        set "MATCHED=1"
    )
)

if not defined MATCHED (
    echo no step matches: !WANT! 1>&2
    exit /b 1
)

shift
goto select_steps

:string_length
set "LENGTH_VALUE=%~1"
set /a LENGTH_RESULT=0

:string_length_loop
if defined LENGTH_VALUE (
    set "LENGTH_VALUE=!LENGTH_VALUE:~1!"
    set /a LENGTH_RESULT+=1
    goto string_length_loop
)

set "%~2=!LENGTH_RESULT!"
exit /b 0
