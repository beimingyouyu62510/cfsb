#!/bin/bash

echo "--- Start.sh: Pre-start Diagnostics ---"
echo "Current directory: $(pwd)"
echo "Listing files in current directory:"
ls -la

echo "---"
echo "Listing files in /app:"
ls -la /app

echo "--- Start.sh: Running application with Uvicorn ---"
# 使用 exec 可以确保信号被正确传递到 Uvicorn 进程
exec uvicorn backend.app:app --host 0.0.0.0 --port 8000
