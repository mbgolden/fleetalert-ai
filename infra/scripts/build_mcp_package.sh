#!/bin/bash
# Builds backend/build/mcp_package -- the directory Terraform zips up as the
# hosted MCP server's deployment package (infra/modules/mcp_server). Must
# run before `terraform plan`/`apply`, like build_lambda_package.sh.
#
# The code comes from a separate repo, github.com/mbgolden/fleetalert-mcp,
# at a pinned tag (ADR-0025): bumping FLEETALERT_MCP_REF is how the demo
# picks up a new server release. mangum is the ASGI adapter for API
# Gateway; boto3 is not installed here because the Lambda runtime provides
# it (the package's `lambda` extra pulls it in for local tests only).
#
# Run from Linux (WSL/CI): the MCP SDK depends on cryptography and
# pydantic-core, both compiled wheels, and Lambda's runtime is Linux.
set -euo pipefail
cd "$(dirname "$0")/../../backend"

UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
REF="${FLEETALERT_MCP_REF:-v0.3.0}"

rm -rf build/mcp_package
mkdir -p build/mcp_package
"$UV" pip install --target build/mcp_package \
  --python-platform x86_64-manylinux2014 --python-version 3.12 \
  "fleetalert-mcp @ git+https://github.com/mbgolden/fleetalert-mcp@${REF}" \
  "mangum>=0.22,<0.23"

# Reproducible zip hash across runs with no real change -- see
# build_lambda_package.sh for why.
find build/mcp_package -exec touch -t 202601010000 {} +
echo "built fleetalert-mcp@${REF} into backend/build/mcp_package"
