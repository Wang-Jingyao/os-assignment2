#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
cargo fetch --locked
make build_user_programs generate_progs_rs
