@echo off
C:\Users\Hello\AppData\Roaming\Python\Python314\Scripts\pytest.exe tests/test_nl_translator.py -v --tb=short > nl_test_output.txt 2>&1
echo Test exit code: %ERRORLEVEL% >> nl_test_output.txt
