@echo off
setlocal DisableDelayedExpansion
set "ERRORLEVEL="
rem Resolve executable interpreters explicitly: a nested .cmd must not take over this batch.
set "AGENTKIT_PY_PREFIX="
for %%N in (python.exe python3.exe) do (
  for /f "delims=" %%P in ('where %%N 2^>nul') do (
    "%%P" -I -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
    if not errorlevel 1 (
      set "AGENTKIT_PY=%%P"
      goto run_core
    )
  )
)
for /f "delims=" %%P in ('where py.exe 2^>nul') do (
  "%%P" -3 -I -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
  if not errorlevel 1 (
    set "AGENTKIT_PY=%%P"
    set "AGENTKIT_PY_PREFIX=-3"
    goto run_core
  )
)
echo agentkit requires Python 3.9 or newer. Install Python and reopen your terminal. 1>&2
exit /b 1
:run_core
rem Leave batch context before the synchronous core can purge this launcher.
(goto) 2>nul & "%AGENTKIT_PY%" %AGENTKIT_PY_PREFIX% -I "%~dp0..\lib\agentkit.py" %*
