#!/usr/bin/env python3
"""
ParrotForwarder - Real-time telemetry and video forwarding from Parrot Anafi

Simple entry point that imports from the parrot_forwarder package.
"""

import sys
from parrot_forwarder.cli import main

if __name__ == '__main__':
    sys.exit(main())

