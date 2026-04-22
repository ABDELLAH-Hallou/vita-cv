#!/bin/bash
set -e

echo "🧹 Cleaning old builds..."
rm -rf dist/ build/ *.egg-info

echo "🔨 Building package..."
python -m build

echo "✅ Build complete!"
echo ""
echo "📦 Distribution files:"
ls -lh dist/

echo ""
echo "🧪 Upload to TestPyPI:"
python -m twine upload --repository testpypi dist/*