#!/usr/bin/env bash

pip install pipenv
# Install all the dependencies 
pipenv install --system --deploy 

# Clean up the cache
rm -rf ~/.cache/pip


