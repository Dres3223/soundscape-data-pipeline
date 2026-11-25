#!/bin/sh
# Entry point of the pipeline image: runs one stage of the pipeline.
# Settings come from environment variables (docker run --env-file .env ...).
set -eu

case "${1:-}" in
  ingest | features | detections | load)
    stage=$1
    shift
    exec python -m "soundscape.$stage" "$@"
    ;;
  -h | --help | "")
    echo "Usage: docker run --env-file .env <image> ingest|features|detections|load"
    ;;
  *)
    echo "Unknown stage: $1 (expected ingest, features, detections or load)" >&2
    exit 2
    ;;
esac
