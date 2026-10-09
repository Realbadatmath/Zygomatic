#!/bin/bash
# Kill Flask dashboard process on Linux
PORT=${FLASK_PORT:-5000}
PIDS=$(lsof -ti tcp:$PORT 2>/dev/null)
if [ -z "$PIDS" ]; then
    echo "No process found on port $PORT"
else
    echo "Killing process(es) on port $PORT: $PIDS"
    kill -9 $PIDS
    echo "Done"
fi
