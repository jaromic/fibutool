#!/bin/bash

[ -z "$1" ] && { echo "usage $0 <workdir>" ; exit 1 ; }
[ -d test_data ] && { echo "Remove old test data first." ; exit 1 ; }
mkdir test_data
cp -avi "$1"/* test_data/