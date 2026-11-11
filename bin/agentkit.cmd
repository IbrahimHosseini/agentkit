@echo off
setlocal DisableDelayedExpansion
python -I -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
if errorlevel 1 goto use_python3
(
python -I "%~dp0..\lib\agentkit.py" %*
exit /b
)
:use_python3
python3 -I -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
if errorlevel 1 goto use_py
(
python3 -I "%~dp0..\lib\agentkit.py" %*
exit /b
)
:use_py
py -3 -I -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
if errorlevel 1 goto missing
(
py -3 -I "%~dp0..\lib\agentkit.py" %*
exit /b
)
:missing
echo agentkit requires Python 3.9 or newer. Install Python and reopen your terminal. 1>&2
exit /b 1
