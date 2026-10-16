@echo off
rem Windows launcher for the artifact-editor MCP server. POSIX twin: launch
rem Bare "python3" on Windows is usually the Store stub; "python" is the real
rem interpreter. Fall back to the py launcher if python is missing (exit 9009).
rem
rem The interpreter found here only RESOLVES the runtime -- plugin_runtime's
rem `serve` then execs the runtime's own python, which is the one that has the
rem wheels. See the POSIX twin for why bare python3 was the CONNECTION_CLOSED.
python "%~dp0plugin_runtime.py" serve "%~dp0artifact_app_server.py" %*
if %errorlevel%==9009 py "%~dp0plugin_runtime.py" serve "%~dp0artifact_app_server.py" %*
