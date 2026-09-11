#!/bin/sh
set -eu

workdir="${ERA_AUTOMATION_WORKDIR:-/data/automation_work}"
mkdir -p "$workdir"
chown research:research "$workdir"

exec runuser -u research -- "$@"
