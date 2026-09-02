#!/bin/bash
set -e

cd /home/ayushraj/plantae

git fetch origin
git reset --hard origin/main

docker compose build

docker compose up -d

docker image prune -f

# Fail deploy if static files didn't land where Apache expects them
if [ -z "$(ls -A /home/ayushraj/plantae/static 2>/dev/null)" ]; then
  echo "ERROR: static/ directory is empty after deploy!"
  exit 1
fi