#!/bin/bash
export PATH=/opt/homebrew/bin:/opt/homebrew/sbin:/opt/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
SEC="${1:-0}"
sleep "$SEC"
/opt/miniconda3/bin/python3 /Users/vadimkasse/Projects/stoneage/stoneage_generator.py
