#!/bin/bash

# WANControl CLI Wrapper
# This script executes the WANControl CLI python module.

# Determine the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Set PYTHONPATH to include the script directory so 'wancontrol' package can be found
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Set default config path if not set
if [ -z "$WANCONTROL_CONFIG" ]; then
    export WANCONTROL_CONFIG="/etc/wancontrol/config.yaml"
fi

# Execute the CLI module
python3 -m wancontrol.cli "$@"
