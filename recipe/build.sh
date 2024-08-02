#!/bin/bash

make -c src/ptdata_plugin
cp src/ptdata_plugin/libindex_plugin.so ${PREFIX}/lib

${PYTHON} -m pip install . --no-deps --ignore-installed -vv


