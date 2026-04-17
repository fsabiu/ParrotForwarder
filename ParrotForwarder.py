#!/usr/bin/env python3
"""Thin v1 shim. Real entry point is the ``parrot-forwarder`` console script."""
import sys
from parrot_forwarder.cli import main

if __name__ == "__main__":
    sys.exit(main())
