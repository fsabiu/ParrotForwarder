#!/bin/bash

# Script to discover local IP from enp0s8 interface and output IP and ffplay command

# Extract IP address from enp0s8 interface using ip command
# The command looks for the inet address in the enp0s8 interface output
IP=$(ip a show enp0s8 | grep -oP 'inet \K[0-9.]+' | head -1)

# Check if IP was found
if [ -z "$IP" ]; then
    echo "Error: Could not find IP address for enp0s8 interface"
    exit 1
fi

# Output the IP address (line 1)
echo "$IP"

# Output the ffplay command (line 2)
echo "ffplay -rtsp_transport tcp rtsp://$IP:8554/parrot_stream"
