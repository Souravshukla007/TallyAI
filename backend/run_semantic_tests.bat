@echo off
python -m pytest tests/test_semantic_layer.py -v --tb=short > semantic_test_output.txt 2>&1
echo Test exit code: %ERRORLEVEL% >> semantic_test_output.txt
