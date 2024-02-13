# Copyright 2024 General Atomics
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#    http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from setuptools import setup
from setuptools import find_packages
import os
import versioneer


packages = [
    os.path.join("toksearch_d3d", package) for package in find_packages("toksearch_d3d")
]

setup(
    version=versioneer.get_version(),
    name="toksearch_d3d",
    packages=packages,
    zip_safe=False,
)
