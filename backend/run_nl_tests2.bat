@echo off
setlocal
set PYTHONPATH=C:\Users\Hello\OneDrive\Documents\mcpApps\backend
set PATH=C:\Users\Hello\AppData\Roaming\Python\Python314\Scripts;%PATH%
pytest tests/test_nl_translator.py -v --tb=short > nl_test_output.txt 2>&1
echo Test exit code: %ERRORLEVEL% >> nl_test_output.txt
