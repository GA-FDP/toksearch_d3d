![](ts_logo_blue.png)

# Welcome to TokSearch DIII-D

TokSearch is a Python package for parallel retrieving, processing, and filtering of arbitrary-dimension fusion experimental data. TokSearch provides a high level API for extracting information from many shots, along with useful classes for low level data retrieval and manipulation.

This is the documentation for the DIII-D TokSearch package. For the general TokSearch documentation, please visit the [TokSearch documentation page](https://ga-fdp.github.io/toksearch/).

## Installation

TokSearch DIII-D is available on the `ga-fdp` conda channel. 

In the near future, we will provide a way to install TokSearch directly from PyPI using pip.


### Installation with Conda in an existing environment

To install in an existing conda environment, run:



```bash
conda install -c ga-fdp -c conda-forge toksearch_d3d
```

or equivalently

```bash
conda install -c conda-forge ga-fdp::toksearch_d3d
```

You can substitute `mamba` for `conda` if you prefer.

### Installation with Conda in a new environment
Optionally, you can create a new environment:

```bash
mamba create -n toksearch_d3d -c ga-fdp -c conda-forge toksearch_d3d
```

### Installation from Source

At the moment, the cleanest way to install TokSearch from source is to first set up a Conda/Mamba environment with the required dependencies, and then install TokSearch from the local clone of the repository. Here are the steps:

First, clone the repository, then from the root directory of the repository, run:

```bash
mamba env create -f environment.yml
```

or

```bash
conda env create -f environment.yml
```

You can also specify the ```-p``` flag to specify the path to the environment. For example:

```bash
mamba env create -f environment.yml -p /path/to/env
```

Then, activate the environment:

```bash
conda activate toksearch # or whatever you named the environment
```

Finally, install TokSearch itself:

```bash
pip install -e .
```

