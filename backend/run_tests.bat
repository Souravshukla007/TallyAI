@echo off
python -m pytest tests/test_credential_store.py tests/test_connection_manager.py -v --tb=short > test_output.txt 2>&1
echo Test exit code: %ERRORLEVEL% >> test_output.txt
