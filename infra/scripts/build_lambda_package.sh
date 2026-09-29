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
# Pin the target explicitly: jsonschema pulls in rpds-py (compiled), and
# the wheels must match Lambda's python3.12 x86_64 runtime regardless of
# which Python the CI runner image happens to ship.
"$UV" pip install --target build/lambda_package \
  --python-platform x86_64-manylinux2014 --python-version 3.12 .

# Normalize mtimes so the zip Terraform's archive_file builds is
# byte-reproducible across runs with no real code change -- pip/uv give
# every installed file a real install-time mtime, which otherwise makes
# every `terraform plan` show all Lambda functions as "to change" purely
# from a hash difference, even when nothing actually changed.
find build/lambda_package -exec touch -t 202601010000 {} +
