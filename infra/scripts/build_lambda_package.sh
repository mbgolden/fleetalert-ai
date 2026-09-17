#!/bin/bash
# Builds backend/build/lambda_package -- the directory Terraform zips up as
# every Lambda function's deployment package (infra/modules/lambda_function
# zips whatever `source_dir` points at). Must run before `terraform plan`/
# `apply`, since the archive_file data source reads this directory directly.
#
# Run from Linux (WSL/CI), not native Windows -- pydantic-core (a transitive
# anthropic dependency) ships as a platform-specific compiled wheel, and
# Lambda's runtime is Linux. Building here means the fetched wheel already
# matches, avoiding the exact class of problem documented in
# project-fleetalert-ai memory re: WSL vs Windows for this repo.
set -euo pipefail
cd "$(dirname "$0")/../../backend"

UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

rm -rf build/lambda_package
mkdir -p build/lambda_package
"$UV" pip install --target build/lambda_package .
