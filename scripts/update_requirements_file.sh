#!/bin/sh

echo "### THIS FILE IS GENERATED, DO NOT EDIT" > requirements.txt
pipenv lock --keep-outdated -r >> requirements.txt
