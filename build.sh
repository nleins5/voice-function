#!/usr/bin/env bash
# exit on error
set -o errexit

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Building React UI..."
npm install
npm run build:ui
echo "Build complete!"
