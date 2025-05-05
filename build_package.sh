#!/bin/bash

python3 -m venv .venv
source .venv/bin/activate
pip install build
python -m build